"""Search adapters for local decisions published through LBLOD sources.

The public :class:`LblodSearch` adapter tries the structured Centrale
Vindplaats SPARQL endpoint first and falls back to the fresher Lokaal Beslist
JSON:API when the SPARQL search yields no candidates.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape

import httpx

from src.models import (
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


# ---------------------------------------------------------------------------
# Source configuration and query normalization
# ---------------------------------------------------------------------------


SPARQL_ENDPOINT = "https://centrale-vindplaats.lblod.info/sparql"
LOKAAL_BESLIST_API = "https://lokaalbeslist.vlaanderen.be"
LOKAAL_BESLIST_URL = "https://lokaalbeslist.vlaanderen.be/agendapunten/{uuid}"

DECISION_NUMBER_RE = re.compile(r"\d{4}_\w+_\d+")

_STOP_WORDS = frozenset(
    "de het een van in op aan het voor met tot uit door over als om bij "
    "dat die dit deze den des der werd werden is was zijn naar geen er "
    "maar ook nog wel dan niet meer al zo te en of je ze we hij zij hun "
    "januari februari maart april mei juni juli augustus september oktober "
    "november december "
    "raad raadsbesluit besluit beslissing zitting gemeenteraad "
    "gemeenteraadsbesluit vast bureau college burgemeester schepenen "
    "raad maatschappelijk welzijn goedkeuring goedgekeurd nr "
    "bestuur dagelijks artikel art lid".split()
)


@dataclass
class _RawRows:
    """Internal rows returned by one LBLOD backend request."""

    rows: list[dict] = field(default_factory=list)
    error: SearchError | None = None


def _clean_text(html: str) -> str:
    """Remove simple markup and normalize whitespace in source text."""
    if not html:
        return ""
    text = unescape(re.sub(r"<[^>]+>", "", html))
    return re.sub(r"\s+", " ", text).strip(" ,")


def _extract_keywords(query: str) -> list[str]:
    """Return ordered, unique discovery terms from a local-decision reference."""
    text = DECISION_NUMBER_RE.sub("", query)
    text = re.sub(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", "", text)
    text = re.sub(r"\d{4}", "", text)
    tokens = re.findall(r"[a-zA-ZÀ-ÿ]{3,}", text.lower())
    keywords = [token for token in tokens if token not in _STOP_WORDS]
    seen: set[str] = set()
    result: list[str] = []
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            result.append(keyword)
    return result


def _rank_results(
    results: list[SearchResult], query: str, session_date: str | None
) -> list[SearchResult]:
    """Rank candidates by identity evidence, then optional session-date distance."""
    query_lower = query.lower()
    query_keywords = _extract_keywords(query)

    def sort_key(result: SearchResult) -> tuple[int, int]:
        title_lower = result.title.lower()
        desc_lower = result.metadata.get("description", "").lower()
        combined = title_lower + " " + desc_lower

        decision_numbers = DECISION_NUMBER_RE.findall(query)
        if decision_numbers and any(
            decision_number in result.title for decision_number in decision_numbers
        ):
            tier = 0
        elif query_lower in title_lower:
            tier = 1
        elif query_keywords and all(kw in title_lower for kw in query_keywords):
            tier = 1
        elif query_keywords and all(kw in combined for kw in query_keywords):
            tier = 2
        elif query_keywords and any(kw in combined for kw in query_keywords):
            tier = 3
        else:
            tier = 4

        date_dist = 9999
        if session_date and result.metadata.get("session_date"):
            try:
                target = datetime.strptime(session_date, "%Y-%m-%d")
                actual = datetime.strptime(result.metadata["session_date"], "%Y-%m-%d")
                date_dist = abs((target - actual).days)
            except ValueError:
                pass

        return (tier, date_dist)

    results.sort(key=sort_key)
    return results


# ---------------------------------------------------------------------------
# SPARQL search against Centrale Vindplaats
# ---------------------------------------------------------------------------

_QUERY_PREFIXES = """\
PREFIX besluit: <http://data.vlaanderen.be/ns/besluit#>
PREFIX dct:     <http://purl.org/dc/terms/>
PREFIX generiek: <https://data.vlaanderen.be/ns/generiek#>
PREFIX mandaat: <http://data.vlaanderen.be/ns/mandaat#>
PREFIX mu:      <http://mu.semte.ch/vocabularies/core/>
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
"""

_CORE_PATTERN = """\
  ?session a besluit:Zitting ;
           prov:startedAtTime ?startedAt ;
           besluit:isGehoudenDoor ?temporalGoverningBody ;
           besluit:behandelt ?agendaItem .

  ?agendaItem a besluit:Agendapunt ;
              dct:title ?title .
  OPTIONAL {{ ?agendaItem dct:description ?description . }}
  OPTIONAL {{ ?agendaItem mu:uuid ?uuid . }}

  ?temporalGoverningBody
      (generiek:isTijdspecialisatieVan|mandaat:isTijdspecialisatieVan)
      ?governingBody .
  ?governingBody besluit:bestuurt ?administrativeUnit ;
                 skos:prefLabel ?governingBodyName .
  ?administrativeUnit skos:prefLabel ?municipalityName .

  FILTER(LCASE(STR(?municipalityName)) = "{municipality_lower}")
"""


class SparqlSearch(LegislationSearch):
    """Search agenda items through the Centrale Vindplaats SPARQL endpoint.

    The SPARQL snapshot can lag behind Lokaal Beslist. Use JsonApiSearch
    when fresher data is needed.
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
        *,
        municipality: str,
        governing_body: str | None = None,
        session_date: str | None = None,
    ) -> SearchOutcome:
        """Search by decision number, keywords, or a supplied session date.

        The municipality filter is always required.  Governing-body and date
        filters are relaxed after an empty keyword search, while municipality
        identity is never relaxed.
        """
        retrieved_at = datetime.now(timezone.utc)
        extra_filters = self._build_extra_filters(governing_body, session_date)
        decision_numbers = DECISION_NUMBER_RE.findall(query)
        keywords = _extract_keywords(query)
        errors: list[SearchError] = []
        backend_request_count = 0

        if decision_numbers:
            raw = self._search_decision_number(
                decision_numbers[0], municipality, extra_filters
            )
            backend_request_count += 1
            if raw.error:
                errors.append(raw.error)
            if raw.rows:
                return self._finalize(
                    raw.rows,
                    retrieved_at,
                    query,
                    session_date,
                    errors,
                    backend_request_count,
                )

        if keywords:
            raw = self._search_keywords(keywords, municipality, extra_filters)
            backend_request_count += 1
            if raw.error:
                errors.append(raw.error)
            if raw.rows:
                return self._finalize(
                    raw.rows,
                    retrieved_at,
                    query,
                    session_date,
                    errors,
                    backend_request_count,
                )
            if extra_filters:
                raw = self._search_keywords(keywords, municipality, "")
                backend_request_count += 1
                if raw.error:
                    errors.append(raw.error)
                if raw.rows:
                    return self._finalize(
                        raw.rows,
                        retrieved_at,
                        query,
                        session_date,
                        errors,
                        backend_request_count,
                    )

        if session_date:
            raw = self._search_date_only(municipality, session_date, governing_body)
            backend_request_count += 1
            if raw.error:
                errors.append(raw.error)
            if raw.rows:
                return self._finalize(
                    raw.rows,
                    retrieved_at,
                    query,
                    session_date,
                    errors,
                    backend_request_count,
                )

        return SearchOutcome(
            complete=not errors,
            backend_request_count=backend_request_count,
            errors=errors,
        )

    def _search_keywords(
        self, keywords: list[str], municipality: str, extra_filters: str
    ) -> _RawRows:
        conditions = []
        for kw in keywords:
            escaped = kw.replace('"', '\\"')
            conditions.append(
                f'    (CONTAINS(LCASE(STR(?title)), "{escaped}")'
                f' || CONTAINS(LCASE(STR(?description)), "{escaped}"))'
            )
        keyword_filter = "  FILTER(\n" + "\n    && ".join(conditions) + "\n  )\n"
        return self._execute(
            self._build_query(municipality, keyword_filter + extra_filters)
        )

    def _search_decision_number(
        self, number: str, municipality: str, extra_filters: str
    ) -> _RawRows:
        escaped = number.replace('"', '\\"')
        f = (
            f"  FILTER(\n"
            f'    CONTAINS(STR(?title), "{escaped}")\n'
            f'    || CONTAINS(STR(?description), "{escaped}")\n'
            f"  )\n"
        )
        return self._execute(self._build_query(municipality, f + extra_filters))

    def _search_date_only(
        self, municipality: str, session_date: str, governing_body: str | None
    ) -> _RawRows:
        date_filter = f'  FILTER(SUBSTR(STR(?startedAt), 1, 10) = "{session_date}")\n'
        gb_filter = ""
        if governing_body:
            gb_filter = f'  FILTER(CONTAINS(LCASE(STR(?governingBodyName)), "{governing_body.lower()}"))\n'
        return self._execute(self._build_query(municipality, date_filter + gb_filter))

    def _build_query(self, municipality: str, filters: str) -> str:
        core = _CORE_PATTERN.format(municipality_lower=municipality.lower())
        return (
            _QUERY_PREFIXES
            + "SELECT DISTINCT ?agendaItem ?title ?description ?startedAt\n"
            + "                ?governingBodyName ?municipalityName ?uuid\n"
            + "WHERE {\n"
            + core
            + filters
            + "}\nLIMIT 20\n"
        )

    @staticmethod
    def _build_extra_filters(
        governing_body: str | None, session_date: str | None
    ) -> str:
        parts = []
        if session_date:
            parts.append(f'  FILTER(SUBSTR(STR(?startedAt), 1, 10) = "{session_date}")')
        if governing_body:
            parts.append(
                f'  FILTER(CONTAINS(LCASE(STR(?governingBodyName)), "{governing_body.lower()}"))'
            )
        return "\n".join(parts) + ("\n" if parts else "")

    def _execute(self, sparql: str) -> _RawRows:
        """Execute one SPARQL query without hiding transport or parse failures."""
        try:
            response = self._client.get(
                SPARQL_ENDPOINT,
                params={"query": sparql},
                headers={"Accept": "application/sparql-results+json"},
            )
        except httpx.TimeoutException as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-sparql",
                    kind=SearchErrorKind.TIMEOUT,
                    message=f"LBLOD SPARQL request timed out: {error}",
                    retryable=True,
                )
            )
        except httpx.HTTPError as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-sparql",
                    kind=SearchErrorKind.NETWORK,
                    message=f"LBLOD SPARQL request failed: {error}",
                    retryable=True,
                )
            )

        if response.status_code != 200:
            return _RawRows(
                error=SearchError(
                    backend="lblod-sparql",
                    kind=SearchErrorKind.HTTP,
                    message=f"LBLOD SPARQL returned HTTP {response.status_code}",
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
            result_envelope = data["results"]
            if not isinstance(result_envelope, dict):
                raise TypeError("SPARQL results is not an object")
            bindings = result_envelope["bindings"]
            if not isinstance(bindings, list):
                raise TypeError("SPARQL bindings is not a list")
        except (KeyError, TypeError, ValueError) as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-sparql",
                    kind=SearchErrorKind.INVALID_RESPONSE,
                    message=f"LBLOD SPARQL returned an invalid response: {error}",
                    retryable=False,
                )
            )
        return _RawRows(rows=bindings)

    def _finalize(
        self,
        bindings: list[dict],
        retrieved_at: datetime,
        query: str,
        session_date: str | None,
        errors: list[SearchError],
        backend_request_count: int,
    ) -> SearchOutcome:
        results, conversion_errors = self._to_results(bindings, retrieved_at)
        all_errors = [*errors, *conversion_errors]
        return SearchOutcome(
            candidates=_rank_results(results, query, session_date),
            complete=not all_errors,
            truncated=len(bindings) >= 20,
            backend_request_count=backend_request_count,
            errors=all_errors,
        )

    @staticmethod
    def _to_results(
        bindings: list[dict], retrieved_at: datetime
    ) -> tuple[list[SearchResult], list[SearchError]]:
        """Convert valid SPARQL bindings while retaining malformed rows."""
        seen: set[str] = set()
        results: list[SearchResult] = []
        errors: list[SearchError] = []
        for binding in bindings:
            try:
                uuid = binding.get("uuid", {}).get("value", "")
                agenda_uri = binding["agendaItem"]["value"]
                title = _clean_text(binding["title"]["value"])
                session = binding["startedAt"]["value"][:10]
                body = binding["governingBodyName"]["value"]
                municipality = binding["municipalityName"]["value"]
                if not title:
                    raise ValueError("title is empty")
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                errors.append(
                    SearchError(
                        backend="lblod-sparql",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"LBLOD SPARQL binding is incomplete: {error}",
                        retryable=False,
                    )
                )
                continue
            doc_id = uuid or agenda_uri
            if doc_id in seen:
                continue
            seen.add(doc_id)

            url = LOKAAL_BESLIST_URL.format(uuid=uuid) if uuid else agenda_uri
            description = _clean_text(binding.get("description", {}).get("value", ""))

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    source="lblod",
                    doc_id=doc_id,
                    retrieved_at=retrieved_at,
                    metadata={
                        "session_date": session,
                        "governing_body": body,
                        "municipality": municipality,
                        "description": description,
                    },
                )
            )
        return results, errors


# ---------------------------------------------------------------------------
# JSON:API search against Lokaal Beslist (mu-search / Elasticsearch backend)
# ---------------------------------------------------------------------------
#
# Supported filters (all combinable):
#   filter[title]               — tokenized text search, space-separated words = AND
#   filter[sessions][planned-start]                     — exact date YYYY-MM-DD
#   filter[sessions][governing-body][name]              — governing body name
#   filter[sessions][governing-body][administrative-unit][name] — municipality
#   sort=-sessions.planned-start  (descending by date)
#   page[size]=N
#
# NOT supported on the API (despite what the web UI search shows):
#   - "exact phrase" quoting
#   - OF (OR operator)
#   - EN (AND operator, implicit anyway)
#   - -exclusion
#   - :gte:/:lte: range modifiers (returns 406)
#
# The web frontend search bar uses a separate mu-search route with Elasticsearch
# simple_query_string syntax; the JSON:API filter[title] is plain tokenized AND.


class JsonApiSearch(LegislationSearch):
    """Search agenda items through the Lokaal Beslist JSON:API.

    Has fresher data than the SPARQL endpoint. Supports tokenized keyword
    search on title combined with municipality/date/governing-body filters.
    """

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=60)
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
        municipality: str,
        governing_body: str | None = None,
        session_date: str | None = None,
    ) -> SearchOutcome:
        """Search title candidates within one required municipality.

        Exact decision numbers are tried before extracted keywords.  When the
        constrained requests are empty, the adapter retries without date and
        governing-body filters but retains the municipality restriction.
        """
        decision_numbers = DECISION_NUMBER_RE.findall(query)
        keywords = _extract_keywords(query)
        title_candidates = self._title_candidates(decision_numbers, keywords)
        if not title_candidates:
            return SearchOutcome()

        items: list[dict] = []
        errors: list[SearchError] = []
        backend_request_count = 0
        for title_q in title_candidates:
            raw = self._fetch(
                title_q,
                municipality,
                governing_body,
                session_date,
            )
            backend_request_count += 1
            if raw.error:
                errors.append(raw.error)
            items = raw.rows
            if items:
                break

        # Relax: drop date/governing-body constraints
        if not items and (session_date or governing_body):
            for title_q in title_candidates:
                raw = self._fetch(title_q, municipality, None, None)
                backend_request_count += 1
                if raw.error:
                    errors.append(raw.error)
                items = raw.rows
                if items:
                    break

        if not items:
            return SearchOutcome(
                complete=not errors,
                backend_request_count=backend_request_count,
                errors=errors,
            )

        retrieved_at = datetime.now(timezone.utc)
        results, conversion_errors = self._to_results(
            items,
            municipality,
            retrieved_at,
        )
        errors.extend(conversion_errors)
        return SearchOutcome(
            candidates=_rank_results(results, query, session_date),
            complete=not errors,
            truncated=len(items) >= 20,
            backend_request_count=backend_request_count,
            errors=errors,
        )

    def _fetch(
        self,
        title_query: str,
        municipality: str,
        governing_body: str | None,
        session_date: str | None,
    ) -> _RawRows:
        params: dict[str, str] = {
            "filter[title]": title_query,
            "filter[sessions][governing-body][administrative-unit][name]": municipality,
            "page[size]": "20",
        }
        if governing_body:
            params["filter[sessions][governing-body][name]"] = governing_body
        if session_date:
            params["filter[sessions][planned-start]"] = session_date
        try:
            response = self._client.get(
                f"{LOKAAL_BESLIST_API}/agenda-items",
                params=params,
                headers={"Accept": "application/vnd.api+json"},
            )
        except httpx.TimeoutException as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-json-api",
                    kind=SearchErrorKind.TIMEOUT,
                    message=f"LBLOD JSON:API request timed out: {error}",
                    retryable=True,
                )
            )
        except httpx.HTTPError as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-json-api",
                    kind=SearchErrorKind.NETWORK,
                    message=f"LBLOD JSON:API request failed: {error}",
                    retryable=True,
                )
            )

        if response.status_code != 200:
            return _RawRows(
                error=SearchError(
                    backend="lblod-json-api",
                    kind=SearchErrorKind.HTTP,
                    message=f"LBLOD JSON:API returned HTTP {response.status_code}",
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
            items = data["data"]
            if not isinstance(items, list):
                raise TypeError("JSON:API data is not a list")
        except (KeyError, TypeError, ValueError) as error:
            return _RawRows(
                error=SearchError(
                    backend="lblod-json-api",
                    kind=SearchErrorKind.INVALID_RESPONSE,
                    message=f"LBLOD JSON:API returned an invalid response: {error}",
                    retryable=False,
                )
            )
        return _RawRows(rows=items)

    @staticmethod
    def _title_candidates(
        decision_numbers: list[str], keywords: list[str]
    ) -> list[str]:
        """Build best-first title queries; the API treats multiple words as AND."""
        candidates: list[str] = []
        candidates.extend(decision_numbers)
        long_kws = [kw for kw in keywords if len(kw) >= 6]
        if long_kws:
            # Combine top keywords into one query (API does tokenized AND)
            candidates.append(" ".join(long_kws[:4]))
        for kw in sorted(keywords, key=len, reverse=True):
            if len(kw) >= 6:
                candidates.append(kw)
        return list(dict.fromkeys(candidates))

    def _to_results(
        self, items: list[dict], municipality: str, retrieved_at: datetime
    ) -> tuple[list[SearchResult], list[SearchError]]:
        """Convert valid JSON:API items while retaining malformed rows."""
        results: list[SearchResult] = []
        errors: list[SearchError] = []
        for item in items:
            try:
                attrs = item.get("attributes", {})
                item_id = item["id"]
                title = _clean_text(attrs.get("title", ""))
                description = _clean_text(attrs.get("description", ""))
                if not item_id:
                    raise ValueError("id is empty")
                if not title:
                    raise ValueError("title is empty")
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                errors.append(
                    SearchError(
                        backend="lblod-json-api",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"LBLOD JSON:API item is incomplete: {error}",
                        retryable=False,
                    )
                )
                continue
            url = LOKAAL_BESLIST_URL.format(uuid=item_id)

            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    source="lblod",
                    doc_id=item_id,
                    retrieved_at=retrieved_at,
                    metadata={
                        "session_date": "",
                        "governing_body": "",
                        "municipality": municipality,
                        "description": description,
                        "via": "json-api",
                    },
                )
            )
        return results, errors


# ---------------------------------------------------------------------------
# Composite: tries SPARQL first, falls back to JSON:API
# ---------------------------------------------------------------------------


class LblodSearch(LegislationSearch):
    """Combine structured SPARQL search with the fresher JSON:API fallback."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=60)
        self._owns_client = client is None
        self.sparql = SparqlSearch(client=self._client)
        self.json_api = JsonApiSearch(client=self._client)

    def close(self) -> None:
        """Close the HTTP client shared by both internal adapters."""
        if self._owns_client:
            self._client.close()

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        *,
        municipality: str,
        governing_body: str | None = None,
        session_date: str | None = None,
    ) -> SearchOutcome:
        """Return SPARQL candidates, or JSON:API candidates when none are found."""
        sparql = self.sparql.search(
            query,
            doc_type,
            municipality=municipality,
            governing_body=governing_body,
            session_date=session_date,
        )
        if sparql.candidates:
            return sparql

        json_api = self.json_api.search(
            query,
            doc_type,
            municipality=municipality,
            governing_body=governing_body,
            session_date=session_date,
        )
        return SearchOutcome(
            candidates=json_api.candidates,
            complete=sparql.complete and json_api.complete,
            truncated=sparql.truncated or json_api.truncated,
            total_available=json_api.total_available,
            backend_request_count=(
                sparql.backend_request_count + json_api.backend_request_count
            ),
            errors=[*sparql.errors, *json_api.errors],
        )
