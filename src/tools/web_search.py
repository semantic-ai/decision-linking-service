"""Search adapter for official Belgian and European legislation."""

import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
import re
import random
import time

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

from src.models import (
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


WEBSITES = [
    "ejustice.just.fgov.be",
    "eur-lex.europa.eu",
    "www.remi.legal",
]
MAX_RESULTS = 10
DDGS_BACKENDS = ("yahoo", "bing", "duckduckgo", "brave")
MAX_ATTEMPTS = len(DDGS_BACKENDS)
DDGS_TIMEOUT_SECONDS = 10
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 60.0
BACKOFF_JITTER_SECONDS = 2.0

logger = logging.getLogger(__name__)


def _extract_doc_id(url: str) -> str:
    """Extract a CELEX or Belgian NUMAC identifier from a result URL."""
    parsed = urlsplit(url)
    query_values = parse_qs(parsed.query)
    for value in query_values.get("uri", []):
        match = re.fullmatch(r"celex:([0-9A-Z]+)", value, re.IGNORECASE)
        if match:
            return match.group(1)

    for key in ("cn", "numac"):
        for value in query_values.get(key, []):
            if re.fullmatch(r"\d{10}", value):
                return value

    match = re.search(r"(?<!\d)(\d{10})(?!\d)", parsed.path)
    return match.group(1) if match else ""


class WebSearch(LegislationSearch):
    """Search DDGS and retain results from configured legal websites."""

    def close(self) -> None:
        """This adapter owns no persistent upstream client."""

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        **kwargs,
    ) -> SearchOutcome:
        """Return legal search candidates and structured DDGS failures."""
        del doc_type, kwargs
        retrieved_at = datetime.now(timezone.utc)
        raw_results: list | None = None
        last_error: SearchError | None = None
        backend_request_count = 0
        truncated = False
        saw_empty_provider_result = False

        for attempts in range(1, MAX_ATTEMPTS + 1):
            backend = DDGS_BACKENDS[min(attempts - 1, len(DDGS_BACKENDS) - 1)]
            attempt_results: list = []
            attempt_truncated = False
            attempt_failed = False

            try:
                for website in WEBSITES:
                    search_query = f"{query} site:{website}"
                    logger.info(
                        "[search_web] attempt=%s provider=%s query=%r",
                        attempts,
                        backend,
                        search_query,
                    )
                    backend_request_count += 1
                    try:
                        site_results = list(
                            DDGS(timeout=DDGS_TIMEOUT_SECONDS).text(
                                search_query,
                                region="be-nl",
                                max_results=MAX_RESULTS,
                                backend=backend,
                            )
                        )
                    except TimeoutException:
                        raise
                    except RatelimitException:
                        raise
                    except DDGSException as error:
                        logger.info(
                            "[search_web] provider=%s website=%s no results: %s",
                            backend,
                            website,
                            error,
                        )
                        continue
                    attempt_results.extend(site_results)
                    attempt_truncated = (
                        attempt_truncated or len(site_results) >= MAX_RESULTS
                    )
                if not attempt_results:
                    saw_empty_provider_result = True
                    last_error = None
                    logger.info(
                        "[search_web] provider=%s returned no candidates; "
                        "trying the next provider",
                        backend,
                    )
                    continue
                raw_results = attempt_results
                truncated = attempt_truncated
                logger.info("[search_web] raw_results=%r", raw_results)
                break
            except TimeoutException as error:
                attempt_failed = True
                logger.warning(
                    "[search_web] attempt=%s timed out: %s",
                    attempts,
                    error,
                )
                last_error = SearchError(
                    backend="web_search",
                    kind=SearchErrorKind.TIMEOUT,
                    message=f"DDGS request timed out: {error}",
                    retryable=True,
                )
            except RatelimitException as error:
                attempt_failed = True
                logger.warning(
                    "[search_web] attempt=%s rate-limited: %s",
                    attempts,
                    error,
                )
                last_error = SearchError(
                    backend="web_search",
                    kind=SearchErrorKind.NETWORK,
                    message=f"DDGS request was rate-limited: {error}",
                    retryable=True,
                )
            except Exception as error:
                attempt_failed = True
                logger.warning(
                    "[search_web] attempt=%s failed with %s: %s",
                    attempts,
                    type(error).__name__,
                    error,
                )
                last_error = SearchError(
                    backend="web_search",
                    kind=SearchErrorKind.NETWORK,
                    message=f"DDGS request failed: {error}",
                    retryable=True,
                )
            if attempt_failed and attempts < MAX_ATTEMPTS:
                delay = min(
                    BACKOFF_BASE_SECONDS * 2 ** (attempts - 1),
                    BACKOFF_MAX_SECONDS,
                )
                delay += random.uniform(0, BACKOFF_JITTER_SECONDS)
                time.sleep(delay)
        if raw_results is None:
            if saw_empty_provider_result and last_error is None:
                raw_results = []
            else:
                return SearchOutcome(
                    complete=False,
                    backend_request_count=backend_request_count,
                    errors=[last_error],
                )
        seen: set[str] = set()
        results: list[SearchResult] = []
        errors: list[SearchError] = []
        for row in raw_results:
            try:
                if not isinstance(row, dict):
                    raise ValueError("result row is not an object")
                title = row["title"]
                href = row["href"]
                body = row["body"]
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("title is empty or not text")
                if not isinstance(href, str) or not href.strip():
                    raise ValueError("href is empty or not text")
                if not isinstance(body, str) or not body.strip():
                    raise ValueError("body is empty or not text")
                url = href.strip()
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname not in WEBSITES:
                    continue
            except (KeyError, TypeError, ValueError) as error:
                errors.append(
                    SearchError(
                        backend="web_search",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"DDGS result row is incomplete: {error}",
                        retryable=False,
                    )
                )
                continue

            if url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=title.strip(),
                    url=url,
                    source="web_search",
                    doc_id=_extract_doc_id(url),
                    retrieved_at=retrieved_at,
                    metadata={"snippet": body.strip()},
                )
            )
        return SearchOutcome(
            candidates=results,
            complete=not errors,
            truncated=truncated,
            backend_request_count=backend_request_count,
            errors=errors,
        )