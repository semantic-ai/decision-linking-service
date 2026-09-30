"""Search adapter for Stad Gent municipal regulations."""

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.models import (
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


BASE_URL = "https://stad.gent/nl/reglementen"
PAGE_SIZE = 12
REGULATION_TYPES = {
    "Aanvullende reglementen op het wegverkeer": "6534",
    "Ander reglement": "6529",
    "Belastingreglement": "6526",
    "Burgemeestersbesluit": "6540",
    "Politiereglement": "6531",
    "Retributiereglement": "6527",
    "Subsidiereglement": "6532",
}
_REGULATION_TYPES_BY_NORMALIZED_NAME = {
    " ".join(label.split()).casefold(): (label, value)
    for label, value in REGULATION_TYPES.items()
}
_REGULATION_TYPES_BY_ID = {
    value: (label, value) for label, value in REGULATION_TYPES.items()
}
_TOTAL_RESULTS_PATTERN = re.compile(r"Er zijn\s+([\d.]+)\s+resultaten", re.IGNORECASE)


def normalize_regulation_type(regulation_type: str | None) -> tuple[str, str] | None:
    """Return the canonical label and form value for a regulation type."""
    if regulation_type is None or not regulation_type.strip():
        return None
    value = regulation_type.strip()
    if value in _REGULATION_TYPES_BY_ID:
        return _REGULATION_TYPES_BY_ID[value]
    try:
        return _REGULATION_TYPES_BY_NORMALIZED_NAME[" ".join(value.split()).casefold()]
    except KeyError as error:
        supported = ", ".join(REGULATION_TYPES)
        raise ValueError(
            f"Unknown Stad Gent regulation type {regulation_type!r}; "
            f"supported values: {supported}"
        ) from error


def regulation_url(href: str) -> str:
    """Return the canonical official URL for one regulation result."""
    url = urljoin(BASE_URL, href)
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "stad.gent":
        return ""
    if not parsed.path.startswith("/nl/reglementen/"):
        return ""
    return url


class ReglementSearch(LegislationSearch):
    """Search the public Stad Gent Reglementen listing."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=20)
        self._owns_client = client is None

    def close(self) -> None:
        """Close the HTTP client only when this adapter created it."""
        if self._owns_client:
            self._client.close()

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        *,
        regulation_type: str | None = None,
        page: int = 0,
    ) -> SearchOutcome:
        """Return regulation candidates and source completeness evidence."""
        if page < 0:
            raise ValueError("page must not be negative")

        canonical_type = normalize_regulation_type(regulation_type)
        params = {
            "search": query,
            "page": str(page),
        }
        if canonical_type:
            _, type_id = canonical_type
            params[f"regulation_type[{type_id}]"] = type_id

        retrieved_at = datetime.now(timezone.utc)
        try:
            response = self._client.get(BASE_URL, params=params)
        except httpx.TimeoutException as error:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="reglement",
                        kind=SearchErrorKind.TIMEOUT,
                        message=f"Stad Gent regulation search timed out: {error}",
                        retryable=True,
                    )
                ],
            )
        except httpx.HTTPError as error:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="reglement",
                        kind=SearchErrorKind.NETWORK,
                        message=f"Stad Gent regulation search failed: {error}",
                        retryable=True,
                    )
                ],
            )

        if response.status_code != 200:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="reglement",
                        kind=SearchErrorKind.HTTP,
                        message=(
                            "Stad Gent regulation search returned HTTP "
                            f"{response.status_code}"
                        ),
                        retryable=(
                            response.status_code >= 500
                            or response.status_code in {408, 429}
                        ),
                        status_code=response.status_code,
                    )
                ],
            )

        try:
            rows, total_available, truncated = self._parse_html(response.text)
        except Exception as error:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="reglement",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=(
                            "Stad Gent regulation search page could not be parsed: "
                            f"{error}"
                        ),
                        retryable=False,
                    )
                ],
            )

        candidates = []
        errors = []
        seen_ids: set[str] = set()
        for row in rows:
            missing_fields = [
                field for field in ("id", "title", "url") if not row[field]
            ]
            if missing_fields:
                errors.append(
                    SearchError(
                        backend="reglement",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=(
                            "Stad Gent regulation row is missing: "
                            + ", ".join(missing_fields)
                        ),
                        retryable=False,
                    )
                )
                continue
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            candidates.append(self._to_result(row, retrieved_at, page))

        return SearchOutcome(
            candidates=candidates,
            complete=not errors,
            truncated=truncated,
            total_available=total_available,
            backend_request_count=1,
            errors=errors,
        )

    @staticmethod
    def _parse_html(html: str) -> tuple[list[dict], int | None, bool]:
        """Extract regulation rows, total count, and pagination evidence."""
        soup = BeautifulSoup(html, "html.parser")
        view = soup.select_one(".view-regulations")
        if view is None:
            raise ValueError("response has no regulations view")

        total_available = None
        header = view.select_one(".filter-page-label")
        if header:
            match = _TOTAL_RESULTS_PATTERN.search(header.get_text(" ", strip=True))
            if match:
                total_available = int(match.group(1).replace(".", ""))

        rows = []
        for article in view.select("article.node--type-regulation"):
            title_element = article.select_one("h3")
            link_element = article.select_one(".node__links a[href]")
            metadata = {}
            for item in article.select("dl.list .list__content"):
                label = item.select_one("dt")
                value = item.select_one("dd")
                if not label or not value:
                    continue
                metadata[label.get_text(" ", strip=True)] = value.get_text(
                    " ", strip=True
                )
            tag_element = article.select_one(".tag")
            rows.append(
                {
                    "id": article.get("data-nid"),
                    "title": (
                        title_element.get_text(" ", strip=True)
                        if title_element
                        else ""
                    ),
                    "url": (
                        regulation_url(link_element.get("href", ""))
                        if link_element
                        else ""
                    ),
                    "type": (
                        tag_element.get_text(" ", strip=True)
                        if tag_element
                        else ""
                    ),
                    "approval_body": metadata.get("Orgaan van goedkeuring", ""),
                    "approval_date": metadata.get("Datum van goedkeuring", ""),
                    "announcement_date": metadata.get(
                        "Datum van bekendmaking", ""
                    ),
                }
            )

        truncated = view.select_one('a[rel="next"]') is not None
        if total_available is not None and total_available > len(rows):
            truncated = truncated or len(rows) == PAGE_SIZE
        return rows, total_available, truncated

    @staticmethod
    def _to_result(row: dict, retrieved_at: datetime, page: int) -> SearchResult:
        """Convert a parsed regulation row to a source result."""
        return SearchResult(
            title=row["title"],
            url=row["url"],
            source="reglement",
            doc_id=row["id"],
            retrieved_at=retrieved_at,
            metadata={
                "type": row["type"],
                "approval_body": row["approval_body"],
                "approval_date": row["approval_date"],
                "announcement_date": row["announcement_date"],
                "page": page,
            },
        )