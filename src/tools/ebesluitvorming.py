"""Search adapter for City of Ghent eBesluitvorming agenda items."""

from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from src.models import (
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Source configuration and URL construction
# ---------------------------------------------------------------------------


BASE_URL = "https://ebesluitvorming.gent.be"
SUPPORTED_RESULT_TYPES = frozenset({"MEETING_ITEM"})


def agenda_item_url(meeting_id: str, agenda_item_id: str) -> str:
    """Build the stable public URL represented by a search-result row.

    The live search page uses ``href="#"`` and stores the real identity in
    ``data-meeting-id`` and ``data-id``. Treating the anchor as a normal link
    therefore produces a useless URL.
    """

    if not meeting_id or not agenda_item_id:
        return ""
    return f"{BASE_URL}/zittingen/{meeting_id}/agendapunten/{agenda_item_id}"


# Friendly governing-body names mapped to the current and historical site IDs.
ORGANEN_MAPPING = {
    "Burgemeester": {
        "15.1217.4000.8630": "Burgemeester",
        "21.0119.8818.6924": "voorzitter raad",
    },
    "College van Burgemeester en Schepenen": {
        "15.1217.3599.9736": "College van Burgemeester en Schepenen",
        "21.0407.0310.0500": "college van burgemeester en schepenen - personeel",
        "18.1218.0717.0462": "college van burgemeester en schepenen / vast bureau",
        "18.1218.4846.3824": "college van burgemeester en schepenen / vast bureau - personeel",
    },
    "Gemeenteraad": {
        "15.1217.9161.0380": "Gemeenteraad",
        "15.1217.1925.8810": "Gemeenteraad - Vragenuurtje",
        "18.1218.7317.6450": "gemeenteraad / raad voor maatschappelijk welzijn",
    },
    "Raad voor Maatschappelijk Welzijn": {
        "16.0105.8137.7685": "Raad voor Maatschappelijk Welzijn",
        "18.1218.7317.6450": "gemeenteraad / raad voor maatschappelijk welzijn",
    },
    "Vast Bureau": {
        "15.1016.3959.7507": "Vast Bureau",
        "15.1016.7034.6757": "Vast Bureau Personeel",
        "18.1218.0717.0462": "college van burgemeester en schepenen / vast bureau",
        "18.1218.4846.3824": "college van burgemeester en schepenen / vast bureau - personeel",
    },
    "Commissies": {
        "15.1217.9114.7219": "Overlegcommissie",
        "15.1217.0843.6858": "Themacommissie",
        "15.1217.2291.7775": "Commissie Cultuur, Sport en Feesten",
        "15.1217.4528.0843": "Commissie Haven, Economie en Financiën",
        "15.1217.5673.1838": "Commissie Onderwijs, Personeel en FM",
        "15.1217.2111.6700": "Commissie Openbare Werken, Mobiliteit en Stedenbouw",
        "15.1217.3688.6889": "Commissie Algemene Zaken, Intercommunales en Bevolking",
        "15.1217.0110.7182": "Commissie Welzijn, Werk en Milieu",
        "15.1217.7272.8474": "Commissie Verzelfstandiging",
        "19.0308.2762.5667": "commissie vrije tijd, publiekszaken en pensioenen",
        "19.0308.9575.2070": "commissie mobiliteit, openbaar domein, economie en werk",
        "19.0308.6064.3056": "commissie onderwijs, welzijn en participatie",
        "19.0308.6235.0828": "commissie stedenbouw, stadsontwikkeling en wonen",
        "19.0308.3650.7800": "commissie algemene zaken, financiën en burgerzaken",
        "19.0308.4325.0235": "commissie milieu, natuur, personeel en FM",
        "22.0124.5299.1131": "technische subcommissie Gent 2030",
        "22.0706.9608.8955": "verenigde commissie",
        "22.1013.1977.3173": "technische subcommissie Gentspoort",
        "25.0106.1297.3283": "commissie vrije tijd, openbaar groen, openbare netheid en klimaat (VOGOK)",
        "25.0106.1943.5956": "commissie welzijn, werk, onderwijs, participatie en personeel (WWOPP)",
        "25.0106.0633.0454": "commissie mobiliteit, architectuur, stadsontwikkeling, stedenbouw en erfgoed (MASSE)",
        "25.0106.1636.3952": "commissie facilitair beheer, jeugd, economie, wonen en digitalisering (FJEWD)",
        "25.0106.1332.9183": "commissie financiën, administratieve vereenvoudiging, burgerzaken en  algemene zaken (FABAZ)",
    },
    "Politiecollege": {
        "26.0602.9290.5890": "politiecollege",
        "26.0629.5274.9487": "politiecollege - personeel",
    },
    "SVK (Sociaal Verhuurkantoor)": {
        "16.0108.3182.4355": "Algemene Vergadering SVK",
        "16.0119.1647.7907": "Raad van Beheer SVK",
    },
}

_ORGAN_BY_NORMALIZED_NAME = {
    " ".join(name.split()).casefold(): name for name in ORGANEN_MAPPING
}


def normalize_organ_name(organ: str | None) -> str | None:
    """Return a canonical configured organ name or reject an unknown filter."""
    if organ is None or not organ.strip():
        return None
    normalized = " ".join(organ.split()).casefold()
    try:
        return _ORGAN_BY_NORMALIZED_NAME[normalized]
    except KeyError as error:
        supported = ", ".join(ORGANEN_MAPPING)
        raise ValueError(
            f"Unknown Ghent governing body {organ!r}; supported values: {supported}"
        ) from error


# ---------------------------------------------------------------------------
# Ghent eBesluitvorming adapter
# ---------------------------------------------------------------------------


class EBesluitvormingSearch(LegislationSearch):
    """Search and parse the public City of Ghent decision-search page.

    A friendly governing-body filter may represent multiple current and
    historical site identifiers.  Results from those requests are merged and
    deduplicated by agenda-item ID while preserving source order.
    """

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
        organ: str | None = None,
        meeting_date_start: str | None = None,
        meeting_date_end: str | None = None,
        title: str | None = None,
        type_id: str | None = None,
        page_size: int = 100,
    ) -> SearchOutcome:
        """Return Ghent candidates plus completeness and failure evidence.

        Parameters
        ----------
        query
            Full-text query sent to the public search endpoint.
        organ
            Optional friendly governing-body name from ``ORGANEN_MAPPING``.
            Matching is whitespace- and case-insensitive. Unknown non-empty
            values are rejected instead of silently disabling the filter.
        meeting_date_start, meeting_date_end
            Optional date boundaries accepted by the source endpoint.
        title
            Optional title or exact decision-number filter.
        type_id
            Optional source publication-classification identifier.
        page_size
            Number of rows requested from the first result page.
        """
        retrieved_at = datetime.now(timezone.utc)
        canonical_organ = normalize_organ_name(organ)
        organ_ids = (
            list(ORGANEN_MAPPING[canonical_organ]) if canonical_organ else [None]
        )
        all_rows: list[dict] = []
        seen_ids: set[str] = set()
        errors: list[SearchError] = []
        backend_request_count = 0
        truncated = False

        for organ_id in organ_ids:
            params = {"query": query, "page": "0", "pageSize": str(page_size)}
            if organ_id:
                params["organId"] = organ_id
            if meeting_date_start:
                params["meetingDateStart"] = meeting_date_start
            if meeting_date_end:
                params["meetingDateEnd"] = meeting_date_end
            if title:
                params["title"] = title
            if type_id:
                params["typeId"] = type_id

            backend_request_count += 1
            try:
                response = self._client.get(f"{BASE_URL}/zoeken", params=params)
            except httpx.TimeoutException as error:
                errors.append(
                    SearchError(
                        backend="ebesluitvorming",
                        kind=SearchErrorKind.TIMEOUT,
                        message=f"Ghent search request timed out: {error}",
                        retryable=True,
                    )
                )
                continue
            except httpx.HTTPError as error:
                errors.append(
                    SearchError(
                        backend="ebesluitvorming",
                        kind=SearchErrorKind.NETWORK,
                        message=f"Ghent search request failed: {error}",
                        retryable=True,
                    )
                )
                continue

            if response.status_code != 200:
                errors.append(
                    SearchError(
                        backend="ebesluitvorming",
                        kind=SearchErrorKind.HTTP,
                        message=(
                            "Ghent search returned HTTP "
                            f"{response.status_code} for organ_id={organ_id}"
                        ),
                        retryable=(
                            response.status_code >= 500
                            or response.status_code in {408, 429}
                        ),
                        status_code=response.status_code,
                    )
                )
                continue

            try:
                rows = self._parse_html(response.text)
            except Exception as error:
                errors.append(
                    SearchError(
                        backend="ebesluitvorming",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"Ghent search page could not be parsed: {error}",
                        retryable=False,
                    )
                )
                continue

            truncated = truncated or len(rows) >= page_size
            for row in rows:
                # The general search page also returns written questions and
                # other records that do not have an agenda-item public URL.
                # They are valid source rows, but outside this adapter's
                # agenda-item contract rather than malformed responses.
                if row["type"] not in SUPPORTED_RESULT_TYPES:
                    continue
                missing_fields = [
                    field for field in ("id", "meeting_id", "title") if not row[field]
                ]
                if missing_fields:
                    errors.append(
                        SearchError(
                            backend="ebesluitvorming",
                            kind=SearchErrorKind.INVALID_RESPONSE,
                            message=(
                                "Ghent search row is missing: "
                                + ", ".join(missing_fields)
                            ),
                            retryable=False,
                        )
                    )
                    continue
                if row["id"] in seen_ids:
                    continue
                seen_ids.add(row["id"])
                all_rows.append(row)

        return SearchOutcome(
            candidates=self._to_results(all_rows, retrieved_at),
            complete=not errors,
            truncated=truncated,
            total_available=None,
            backend_request_count=backend_request_count,
            errors=errors,
        )

    @staticmethod
    def _parse_html(html: str) -> list[dict]:
        """Extract result identity and metadata from Ghent search-page HTML."""
        soup = BeautifulSoup(html, "html.parser")
        result_container = soup.select_one(".search-results")
        if result_container is None:
            # A search page with zero matches drops the results container but
            # still renders the search form; only a different page is malformed.
            if soup.select_one("#searchForm") is not None:
                return []
            raise ValueError("response has no search-results container")
        rows = []
        result_elements = result_container.select("a.result-row")

        for element in result_elements:
            title_element = element.select_one("p.title")
            organ_element = element.select_one("p.metadata span.organ")
            date = None
            for date_element in element.select("p.metadata span.date"):
                if not date_element.has_attr("hidden") and date_element.get_text(
                    strip=True
                ):
                    date = date_element.get_text(strip=True)
                    break
            rows.append(
                {
                    "id": element.get("data-id"),
                    "type": element.get("data-type"),
                    "meeting_id": element.get("data-meeting-id"),
                    "title": (
                        title_element.get_text(strip=True) if title_element else ""
                    ),
                    "organ": (
                        organ_element.get_text(strip=True) if organ_element else ""
                    ),
                    "date": date,
                    "content_published": (
                        element.get("data-content-published") == "true"
                    ),
                }
            )
        return rows

    @staticmethod
    def _to_results(rows: list[dict], retrieved_at: datetime) -> list[SearchResult]:
        """Convert parsed HTML rows to stable public search results."""
        return [
            SearchResult(
                title=row["title"],
                url=agenda_item_url(row["meeting_id"], row["id"]),
                source="ebesluitvorming",
                doc_id=row["id"],
                retrieved_at=retrieved_at,
                metadata={
                    "type": row["type"],
                    "meeting_id": row["meeting_id"],
                    "organ": row["organ"],
                    "date": row["date"],
                    "content_published": row["content_published"],
                },
            )
            for row in rows
        ]
