"""Search adapter for legislation indexed by the Vlaamse Codex."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from src.models import (
    ReferenceType,
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------


BASE_URL = "https://codex.opendata.api.vlaanderen.be"
DOCUMENT_URL = "https://codex.vlaanderen.be/Zoeken/Document.aspx?DID={doc_id}"

# Supported category -> Codex document-type IDs and display labels.
CODEX_TYPES: dict[str, list[tuple[int, str]]] = {
    ReferenceType.DECREE: [
        (1000008, "Gecodificeerd Decreet"),
        (1000013, "Bijzonder Decreet"),
        (1000001, "Decreet"),
    ],
    ReferenceType.LAW: [
        (1000017, "Grondwet"),
        (1000020, "Wetboek"),
        (1000011, "Gecoördineerde Wet"),
        (1000016, "Bijzondere Wet"),
        (1000005, "Wet"),
    ],
    ReferenceType.EXECUTIVE_ORDER: [
        (1000002, "Besluit van de Vlaamse Regering"),
        (1000004, "Ministerieel besluit"),
        (1000003, "Koninklijk Besluit"),
    ],
    ReferenceType.REGULATION: [
        (1000054, "Verordening"),
        (1000055, "Gedelegeerde Verordening"),
    ],
    ReferenceType.CIRCULAR: [
        (1000007, "Omzendbrief"),
    ],
    ReferenceType.AGREEMENT: [
        (1000006, "Samenwerkingsakkoord"),
        (1000022, "Protocol"),
        (1000014, "Verdrag"),
    ],
}

_LEADING_ARTICLE = re.compile(r"^(de|het)\s+", re.IGNORECASE)


@dataclass
class _CodexPage:
    """Internal result of one Codex HTTP request."""

    items: list[dict] = field(default_factory=list)
    total_available: int | None = None
    truncated: bool = False
    error: SearchError | None = None


# ---------------------------------------------------------------------------
# Vlaamse Codex adapter
# ---------------------------------------------------------------------------


class CodexSearch(LegislationSearch):
    """Search Vlaamse Codex by title and optional document category.

    A category search fans out over the Codex type IDs belonging to that
    category. When every typed request is empty, the same normalized title is
    retried once without a type restriction to preserve recall.
    """

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30)
        self._owns_client = client is None

    def close(self) -> None:
        """Close the HTTP client only when this adapter created it."""
        if self._owns_client:
            self._client.close()

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        **kwargs,
    ) -> SearchOutcome:
        """Return candidates plus completeness and source-failure evidence."""
        opschrift = _LEADING_ARTICLE.sub("", query)
        retrieved_at = datetime.now(timezone.utc)

        if doc_type and doc_type in CODEX_TYPES:
            pages = [
                self._advanced_search(opschrift, type_id)
                for type_id, _ in CODEX_TYPES[doc_type]
            ]
            if any(page.items for page in pages):
                return self._to_outcome(pages, retrieved_at)

            # Preserve recall when every typed page produced no candidates.
            pages.append(self._advanced_search(opschrift))
            return self._to_outcome(pages, retrieved_at)

        return self._to_outcome(
            [self._advanced_search(opschrift)],
            retrieved_at,
        )

    def _advanced_search(
        self, opschrift: str, type_id: int | None = None
    ) -> _CodexPage:
        """Call Codex once without converting failure into an empty result."""
        body: dict = {"Opschrift": opschrift}
        if type_id is not None:
            body["WetgevingDocumentTypeId"] = type_id

        try:
            response = self._client.post(
                f"{BASE_URL}/api/WetgevingDocument/GeavanceerdZoeken",
                json=body,
            )
        except httpx.TimeoutException as error:
            return _CodexPage(
                error=SearchError(
                    backend="codex",
                    kind=SearchErrorKind.TIMEOUT,
                    message=f"Codex request timed out: {error}",
                    retryable=True,
                )
            )
        except httpx.HTTPError as error:
            return _CodexPage(
                error=SearchError(
                    backend="codex",
                    kind=SearchErrorKind.NETWORK,
                    message=f"Codex request failed: {error}",
                    retryable=True,
                )
            )

        if response.status_code != 200:
            return _CodexPage(
                error=SearchError(
                    backend="codex",
                    kind=SearchErrorKind.HTTP,
                    message=f"Codex returned HTTP {response.status_code}",
                    retryable=(
                        response.status_code >= 500
                        or response.status_code in {408, 429}
                    ),
                    status_code=response.status_code,
                )
            )

        try:
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError("response body is not an object")
            items = data["ResultatenLijst"]
            if not isinstance(items, list):
                raise TypeError("ResultatenLijst is not a list")
            total = data.get("GevondenDocumenten")
            if not isinstance(total, int):
                total = None
        except (KeyError, TypeError, ValueError) as error:
            return _CodexPage(
                error=SearchError(
                    backend="codex",
                    kind=SearchErrorKind.INVALID_RESPONSE,
                    message=f"Codex returned an invalid response: {error}",
                    retryable=False,
                )
            )

        return _CodexPage(
            items=items,
            total_available=total,
            truncated=total is not None and len(items) < total,
        )

    @classmethod
    def _to_outcome(
        cls,
        pages: list[_CodexPage],
        retrieved_at: datetime,
    ) -> SearchOutcome:
        """Merge all attempted Codex pages into one transparent outcome."""
        items = [item for page in pages for item in page.items]
        errors = [page.error for page in pages if page.error is not None]
        results, conversion_errors = cls._to_results(items, retrieved_at)
        errors.extend(conversion_errors)

        totals = [page.total_available for page in pages]
        total_available = sum(totals) if all(v is not None for v in totals) else None
        return SearchOutcome(
            candidates=results,
            complete=not errors,
            truncated=any(page.truncated for page in pages),
            total_available=total_available,
            backend_request_count=len(pages),
            errors=errors,
        )

    @staticmethod
    def _to_results(
        items: list[dict], retrieved_at: datetime
    ) -> tuple[list[SearchResult], list[SearchError]]:
        """Convert valid rows while retaining malformed-row failures."""
        seen = set()
        results = []
        errors = []
        for item in items:
            try:
                raw_doc_id = item["Id"]
                title = item["Opschrift"]
                if raw_doc_id is None or not str(raw_doc_id).strip():
                    raise ValueError("Id is empty")
                if not isinstance(title, str) or not title.strip():
                    raise ValueError("Opschrift is empty or not text")
                doc_id = str(raw_doc_id)
            except (KeyError, TypeError, ValueError) as error:
                errors.append(
                    SearchError(
                        backend="codex",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"Codex result row is incomplete: {error}",
                        retryable=False,
                    )
                )
                continue
            if doc_id in seen:
                continue
            seen.add(doc_id)
            results.append(
                SearchResult(
                    title=title,
                    url=DOCUMENT_URL.format(doc_id=doc_id),
                    source="codex",
                    doc_id=doc_id,
                    retrieved_at=retrieved_at,
                    metadata={
                        "document_date": item.get("Datum"),
                        "publication_date": item.get("BSDatum"),
                    },
                )
            )
        return results, errors
