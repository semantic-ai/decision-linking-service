"""Search adapter for official Belgian and European legislation."""

import logging
import ipaddress
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit
import re
import random
import socket
import time

import httpx
from bs4 import BeautifulSoup
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
BELGIAN_LEGISLATION_HOST = "ejustice.just.fgov.be"
BELGIAN_LEGISLATION_HOST_ALIASES = frozenset(
    {BELGIAN_LEGISLATION_HOST, "www.ejustice.just.fgov.be"}
)
BELGIAN_FOD_HOST = "economie.fgov.be"
BELGIAN_DECREE_PATH = f"{BELGIAN_LEGISLATION_HOST}/eli/besluit"
BELGIAN_DECREE_TYPES = {"decree", "executive_order"}
BELGIAN_DECREE_WEBSITES = [
    BELGIAN_LEGISLATION_HOST,
    BELGIAN_FOD_HOST,
]
MAX_RESULTS = 10
DDGS_BACKENDS = ("yahoo", "bing", "duckduckgo", "brave")
MAX_ATTEMPTS = len(DDGS_BACKENDS)
DDGS_TIMEOUT_SECONDS = 10
BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 60.0
BACKOFF_JITTER_SECONDS = 2.0
PAGE_TIMEOUT_SECONDS = 10.0
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
NUMAC_PATTERN = re.compile(r"(?<!\d)(\d{10})(?!\d)")
CELEX_PATTERN = re.compile(r"(?<!\w)(\d{4}[A-Z]\d{4})(?!\w)", re.IGNORECASE)
CELEX_URI_PATTERN = re.compile(
    r"celex:([0-9A-Z][0-9A-Z_-]*)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _extract_doc_id(url: str) -> str:
    """Extract a CELEX or Belgian NUMAC identifier from a result URL."""
    parsed = urlsplit(url)
    query_values = parse_qs(parsed.query)
    for value in query_values.get("uri", []):
        match = CELEX_URI_PATTERN.fullmatch(value)
        if match:
            return match.group(1)

    for key in ("cn", "numac"):
        for value in query_values.get(key, []):
            if re.fullmatch(r"\d{10}", value):
                return value

    match = re.search(r"(?<!\d)(\d{10})(?!\d)", parsed.path)
    return match.group(1) if match else ""


def _extract_url_evidence(url: str) -> dict:
    """Extract identifiers that are already present in the discovery URL."""
    evidence: dict = {}
    parsed = urlsplit(url)
    query_values = parse_qs(parsed.query)
    for value in query_values.get("uri", []):
        celex_match = CELEX_URI_PATTERN.fullmatch(value)
        if celex_match:
            evidence["celex"] = celex_match.group(1).upper()
            break
        if re.fullmatch(r"nim:[^\s]+", value, re.IGNORECASE):
            evidence["eur_lex_uri"] = value
            break

    for key in ("cn", "numac"):
        for value in query_values.get(key, []):
            if re.fullmatch(r"\d{10}", value):
                evidence["numac"] = value
                return evidence

    path_match = NUMAC_PATTERN.search(parsed.path)
    if path_match:
        evidence["numac"] = path_match.group(1)
    return evidence


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            value = element.get("content", "") or element.get_text(" ", strip=True)
            value = " ".join(value.split())
            if value:
                return value
    return None


def _canonical_url(soup: BeautifulSoup, page_url: str) -> str | None:
    element = soup.select_one('link[rel="canonical"][href]')
    if not element:
        return None
    return urljoin(page_url, element["href"].strip())


def _legal_source_url(soup: BeautifulSoup, page_url: str) -> str | None:
    candidates: list[str] = []
    for element in soup.select("a[href]"):
        candidate = urljoin(page_url, element["href"].strip())
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or (parsed.hostname or "").casefold() not in BELGIAN_LEGISLATION_HOST_ALIASES
        ):
            continue
        if "cn" in parse_qs(parsed.query) or "/eli/" in parsed.path:
            candidates.append(candidate)
    return candidates[0] if candidates else None


def _page_title(soup: BeautifulSoup) -> str | None:
    return _first_text(soup, ("h1", "meta[property='og:title']", "title"))


def _meta_value(soup: BeautifulSoup, names: tuple[str, ...]) -> str | None:
    normalized_names = {name.casefold() for name in names}
    for element in soup.select("meta[name], meta[property]"):
        name = (element.get("name") or element.get("property") or "").casefold()
        content = element.get("content", "").strip()
        if name in normalized_names and content:
            return content
    return None


def _extract_numac_from_page(soup: BeautifulSoup, page_url: str) -> str | None:
    for candidate in (page_url, _canonical_url(soup, page_url) or ""):
        match = NUMAC_PATTERN.search(candidate)
        if match:
            return match.group(1)
    legal_url = _legal_source_url(soup, page_url)
    if legal_url:
        match = NUMAC_PATTERN.search(legal_url)
        if match:
            return match.group(1)
    for element in soup.select("meta[name], meta[property]"):
        value = element.get("content", "")
        match = NUMAC_PATTERN.search(value)
        if match:
            return match.group(1)
    return None


def _extract_celex_from_page(soup: BeautifulSoup, page_url: str) -> str | None:
    for candidate in (page_url, _canonical_url(soup, page_url) or ""):
        match = CELEX_PATTERN.search(candidate)
        if match:
            return match.group(1).upper()
    for element in soup.select("meta[name], meta[property]"):
        value = element.get("content", "")
        match = CELEX_PATTERN.search(value)
        if match:
            return match.group(1).upper()
    return None


def _common_page_evidence(soup: BeautifulSoup, page_url: str) -> dict:
    evidence: dict = {}
    canonical_url = _canonical_url(soup, page_url)
    page_title = _page_title(soup)
    if canonical_url:
        evidence["canonical_url"] = canonical_url
    if page_title:
        evidence["page_title"] = page_title
    return evidence


def _extract_ejustice_page(soup: BeautifulSoup, page_url: str) -> dict:
    evidence = _common_page_evidence(soup, page_url)
    numac = _extract_numac_from_page(soup, page_url)
    celex = _extract_celex_from_page(soup, page_url)
    if numac:
        evidence["numac"] = numac
    if celex:
        evidence["celex"] = celex
    return evidence


def _extract_eurlex_page(soup: BeautifulSoup, page_url: str) -> dict:
    evidence = _common_page_evidence(soup, page_url)
    celex = _extract_celex_from_page(soup, page_url)
    if celex:
        evidence["celex"] = celex
    return evidence


def _extract_remi_page(soup: BeautifulSoup, page_url: str) -> dict:
    evidence = _common_page_evidence(soup, page_url)
    legal_url = _legal_source_url(soup, page_url)
    numac = _extract_numac_from_page(soup, page_url)
    if legal_url:
        evidence["legal_source_url"] = legal_url
    if numac:
        evidence["numac"] = numac
    return evidence


def _extract_fod_legislation_page(soup: BeautifulSoup, page_url: str) -> dict:
    evidence = _common_page_evidence(soup, page_url)
    legal_url = _legal_source_url(soup, page_url)
    numac = _extract_numac_from_page(soup, page_url)
    if legal_url:
        evidence["legal_source_url"] = legal_url
    if numac:
        evidence["numac"] = numac
    return evidence


def _extract_fod_publication_page(soup: BeautifulSoup, page_url: str) -> dict:
    evidence = _common_page_evidence(soup, page_url)
    update_date = _meta_value(
        soup,
        ("dateModified", "date.modified", "article:modified_time"),
    )
    if not update_date:
        element = soup.select_one("time[datetime]")
        update_date = element.get("datetime") if element else None
    if update_date:
        evidence["update_date"] = update_date
    return evidence


def _extract_page_evidence(page_url: str, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    hostname = (urlsplit(page_url).hostname or "").casefold()
    if hostname == BELGIAN_LEGISLATION_HOST:
        return _extract_ejustice_page(soup, page_url)
    if hostname == "eur-lex.europa.eu":
        return _extract_eurlex_page(soup, page_url)
    if hostname == "www.remi.legal":
        return _extract_remi_page(soup, page_url)
    if hostname == BELGIAN_FOD_HOST:
        path = urlsplit(page_url).path.casefold()
        if any(part in path for part in ("wetgeving", "legislation", "regelgeving")):
            return _extract_fod_legislation_page(soup, page_url)
        return _extract_fod_publication_page(soup, page_url)
    return {}


def _site_filter(website: str, doc_type: str | None) -> str:
    """Prefer the official ELI decision path when searching Belgian decrees."""
    if website == BELGIAN_LEGISLATION_HOST and doc_type in BELGIAN_DECREE_TYPES:
        return BELGIAN_DECREE_PATH
    return website


def _websites(doc_type: str | None) -> list[str]:
    """Add the FOD Economie index only for Belgian decree searches."""
    return (
        BELGIAN_DECREE_WEBSITES
        if doc_type in BELGIAN_DECREE_TYPES
        else WEBSITES
    )


class WebSearch(LegislationSearch):
    """Search DDGS and retain results from configured legal websites."""

    def __init__(self):
        self._client: httpx.Client | None = None
        self._active_websites: tuple[str, ...] = tuple(WEBSITES)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=PAGE_TIMEOUT_SECONDS,
                follow_redirects=False,
                headers={"User-Agent": "decision-linking-service/1.0"},
            )
        return self._client

    @staticmethod
    def _validate_fetch_url(
        url: str,
        websites: tuple[str, ...],
    ) -> tuple[bool, str]:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if parsed.scheme != "https" or not hostname:
            return False, "URL is not an HTTPS URL"
        if hostname.casefold() not in {website.casefold() for website in websites}:
            return False, "URL host is not allowlisted"
        try:
            addresses = socket.getaddrinfo(
                hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except (socket.gaierror, ValueError) as error:
            return False, f"host resolution failed: {error}"
        for _, _, _, _, address in addresses:
            ip_address = ipaddress.ip_address(address[0])
            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_reserved
                or ip_address.is_unspecified
            ):
                return False, "URL resolves to a disallowed address"
        return True, ""

    def _fetch_page(self, url: str) -> tuple[str | None, int | None, str | None]:
        """Fetch one bounded HTML page from the active legal host allowlist."""
        websites = self._active_websites
        current_url = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                valid, reason = self._validate_fetch_url(current_url, websites)
                if not valid:
                    return None, None, reason
                with self._get_client().stream(
                    "GET", current_url, follow_redirects=False
                ) as response:
                    response_url = str(response.url)
                    valid, reason = self._validate_fetch_url(response_url, websites)
                    if not valid:
                        return None, response.status_code, f"redirect rejected: {reason}"
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            return None, response.status_code, "redirect has no location"
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        return None, response.status_code, f"HTTP status {response.status_code}"
                    content_type = response.headers.get("content-type", "").lower()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_PAGE_BYTES:
                            return None, response.status_code, "response body exceeds size limit"
                    if response.status_code == 202 and not body:
                        return "", response.status_code, None
                    if not content_type.startswith("text/html"):
                        return None, response.status_code, "response content type is not text/html"
                    return (
                        body.decode(response.encoding or "utf-8", errors="replace"),
                        response.status_code,
                        None,
                    )
            return None, None, "too many redirects"
        except Exception as error:
            logger.info("[search_web] page fetch failed url=%s: %s", url, error)
            return None, None, f"page fetch failed: {type(error).__name__}"

    def _enrich_result(self, result: SearchResult) -> None:
        html, status_code, error = self._fetch_page(result.url)
        result.metadata["enrichment"] = {
            "fetched": html is not None,
            "status_code": status_code,
            "error": error,
        }
        if html is None or error:
            return
        try:
            evidence = _extract_page_evidence(result.url, html)
        except Exception as parse_error:
            result.metadata["enrichment"] = {
                "fetched": True,
                "status_code": status_code,
                "error": f"page parse failed: {type(parse_error).__name__}",
            }
            return
        result.metadata.update(evidence)
        if result.doc_id:
            return
        legal_source_url = result.metadata.get("legal_source_url", "")
        result.doc_id = _extract_doc_id(legal_source_url)

    def close(self) -> None:
        """Close the lazily-created page-fetch client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        **kwargs,
    ) -> SearchOutcome:
        """Return legal search candidates and structured DDGS failures."""
        del kwargs
        websites = _websites(doc_type)
        self._active_websites = tuple(websites)
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
                for website in websites:
                    search_query = f"{query} site:{_site_filter(website, doc_type)}"
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
        seen_urls: set[str] = set()
        seen_identities: dict[str, set[str]] = {}
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
                if parsed.scheme != "https" or parsed.hostname not in websites:
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

            if url in seen_urls:
                continue
            seen_urls.add(url)
            result = SearchResult(
                title=title.strip(),
                url=url,
                source="web_search",
                doc_id=_extract_doc_id(url),
                retrieved_at=retrieved_at,
                metadata={"snippet": body.strip(), **_extract_url_evidence(url)},
            )
            self._enrich_result(result)
            if result.doc_id:
                source_url = result.metadata.get("legal_source_url", "")
                if result.doc_id in seen_identities:
                    previous_sources = seen_identities[result.doc_id]
                    if source_url and previous_sources and source_url not in previous_sources:
                        results.append(result)
                        previous_sources.add(source_url)
                    continue
                seen_identities[result.doc_id] = {source_url} if source_url else set()
                results.append(result)
                continue
            results.append(result)
        return SearchOutcome(
            candidates=results,
            complete=not errors,
            truncated=truncated,
            backend_request_count=backend_request_count,
            errors=errors,
        )