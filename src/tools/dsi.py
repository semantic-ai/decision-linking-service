"""Search adapter for DSI (Digitale Stedenbouwkundige Informatie) spatial planning instruments."""

import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from src.models import (
    LegislationSearch,
    SearchError,
    SearchErrorKind,
    SearchOutcome,
    SearchResult,
)


logger = logging.getLogger(__name__)

BASE_URL = "https://dsi.omgeving.vlaanderen.be"
GRAPHQL_URL = f"{BASE_URL}/graphql"
GEMEENTES_URL = f"{BASE_URL}/api/keuzelijsten/gemeentes"
DEFAULT_PAGE_SIZE = 25

PROCEDURE_CODES = {
    "gewBVO", "gemONT", "proONT", "gewCPR", "WRG", "gemSVO", "proSVO",
    "HOV", "APA", "gemBVO", "BPA", "gemCPR", "gewRUP", "proCPR", "gewROO",
    "gewONT", "gemRUP", "proRUP", "gemROO", "proROO", "GWP", "gewSVO", "WOR",
}

PROCEDURE_ALIASES: dict[str, tuple[str, bool]] = {
    "gewestplan": ("GWP", False),
    "gwp": ("GWP", False),
    "grup": ("gewRUP", False),
    "gewrup": ("gewRUP", False),
    "gewestelijk rup": ("gewRUP", False),
    "gewestelijk ruimtelijk uitvoeringsplan": ("gewRUP", False),
    "gemrup": ("gemRUP", False),
    "gemeentelijk rup": ("gemRUP", False),
    "gemeentelijk ruimtelijk uitvoeringsplan": ("gemRUP", False),
    "prorup": ("proRUP", False),
    "provinciaal rup": ("proRUP", False),
    "provinciaal ruimtelijk uitvoeringsplan": ("proRUP", False),
    "rup": ("RUP", True),  # True = family pattern (code=like="RUP")
    "ruimtelijk uitvoeringsplan": ("RUP", True),
    "bpa": ("BPA", False),
    "bijzonder plan van aanleg": ("BPA", False),
    "apa": ("APA", False),
    "algemeen plan van aanleg": ("APA", False),
    "svo": ("SVO", True),
    "stedenbouwkundige verordening": ("SVO", True),
    "gewestelijke stedenbouwkundige verordening": ("gewSVO", False),
    "gemeentelijke stedenbouwkundige verordening": ("gemSVO", False),
    "provinciale stedenbouwkundige verordening": ("proSVO", False),
    "gewsvo": ("gewSVO", False),
    "gemsvo": ("gemSVO", False),
    "prosvo": ("proSVO", False),
    "bvo": ("BVO", True),
    "bouwverordening": ("BVO", True),
    "bouwreglement": ("BVO", True),
    "algemeen bouwreglement": ("BVO", True),
    "gewestelijke bouwverordening": ("gewBVO", False),
    "gemeentelijke bouwverordening": ("gemBVO", False),
    "gewbvo": ("gewBVO", False),
    "gembvo": ("gemBVO", False),
    "roo": ("ROO", True),
    "rooilijnplan": ("ROO", True),
}

_COMMON_MUNICIPALITY_NIS: dict[str, str] = {
    "gent": "44021",
    "antwerpen": "11002",
    "brugge": "31005",
    "leuven": "24062",
    "aalst": "41002",
    "mechelen": "12025",
    "kortrijk": "34022",
    "hasselt": "71022",
    "sint-niklaas": "46021",
    "oostende": "35013",
    "genk": "71016",
    "roeselare": "36015",
    "beveren": "46003",
    "dendermonde": "42006",
    "turnhout": "13040",
    "vilvoorde": "23088",
    "lokeren": "46014",
    "geel": "13008",
    "halle": "23027",
    "lier": "12021",
}

_PREFIX_PATTERN = re.compile(
    r"^(?:origineel\s+)?(?:gewestelijke?|gemeentelijke?|provinciale?|algemene?)?\s*"
    r"(?:ruimtelijk\s+uitvoeringsplan|gewestplan|bijzonder\s+plan\s+van\s+aanleg|"
    r"algemeen\s+plan\s+van\s+aanleg|stedenbouwkundige\s+verordening|bouwverordening|"
    r"bouwreglement|verordening|rooilijnplan|grup|gemrup|prorup|rup|bpa|apa|gwp|svo|bvo|roo)"
    r"(?:\s+inzake\s+|\s+betreffende\s+|\s+voor\s+|\s+op\s+|\s+|[:\-–—]\s*)",
    re.IGNORECASE,
)

_DECISION_PREFIX_PATTERN = re.compile(
    r"^(?:besluit\s+van\s+de\s+vlaamse\s+regering\s+(?:van\s+\d{1,2}\s+[a-z]+\s+\d{4}\s+)?(?:tot\s+vaststelling\s+van\s+(?:een\s+)?|houdende\s+(?:vaststelling\s+van\s+(?:een\s+)?|de\s+|een\s+)?|ter\s+uitvoering\s+van\s+|tot\s+uitvoering\s+van\s+)?|"
    r"gemeenteraadsbesluit\s+(?:van\s+\d{1,2}\s+[a-z]+\s+\d{4}\s+)?(?:tot\s+|houdende\s+)?)\s*",
    re.IGNORECASE,
)

_SUFFIX_PATTERN = re.compile(
    r"(?:,\s*|\s+)(?:definitief\s+vastgesteld|goedgekeurd\s+op|goedgekeurd\s+door|goedgekeurd\s+bij|"
    r"goedgekeurd|vastgesteld\s+op|vastgesteld\s+bij|vastgesteld|definitief\s+goedgekeurd|"
    r"definitively\s+established|approved\s+on|approved|gewijzigd\s+bij|gewijzigd\s+op|gewijzigd|"
    r"van\s+\d{1,2}\s+[a-z]+\s+\d{4}|"
    r"\(vlaanderen\)|\(belgium/flanders\)|\(vlaams\s+gewest\)).*$",
    re.IGNORECASE,
)

_MUNICIPALITY_SUFFIX_PATTERN = re.compile(
    r"(?:,\s*|\s+)van\s+(?:de\s+)?(?:stad|gemeente)?\s*[a-zA-Z\-]+$",
    re.IGNORECASE,
)

_QUOTE_CHARS = "'\"‘’“”«»` "


def _escape_rsql(value: str) -> str:
    """Escape special characters for an RSQL filter inside GraphQL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _clean_query(raw_query: str) -> str:
    """Strip bounding quotation marks, decision headers, prefixes and trailing citation prose."""
    text = raw_query.strip(_QUOTE_CHARS)
    if re.match(r"^[A-Z]{3,6}_\d{5}_", text):
        return text
    text = _DECISION_PREFIX_PATTERN.sub("", text).strip(_QUOTE_CHARS)
    text = _SUFFIX_PATTERN.sub("", text).strip(_QUOTE_CHARS)
    text = _MUNICIPALITY_SUFFIX_PATTERN.sub("", text).strip(_QUOTE_CHARS)
    cleaned = _PREFIX_PATTERN.sub("", text).strip(_QUOTE_CHARS)
    cleaned = cleaned.strip(_QUOTE_CHARS)
    cleaned = _PREFIX_PATTERN.sub("", cleaned).strip(_QUOTE_CHARS)
    return cleaned if cleaned else raw_query.strip(_QUOTE_CHARS)


def normalize_municipality_name(name: str) -> str:
    """Normalize a municipality name for lookup."""
    norm = " ".join(name.strip().casefold().split())
    for prefix in ("stad ", "gemeente "):
        if norm.startswith(prefix):
            norm = norm[len(prefix):].strip()
    return norm


def resolve_procedure_code(code_or_name: str | None) -> tuple[str, bool] | None:
    """Return canonical procedure code and whether it should use family prefix matching."""
    if not code_or_name or not code_or_name.strip():
        return None
    val = code_or_name.strip()
    if val in PROCEDURE_CODES:
        return val, False
    val_norm = " ".join(val.casefold().split())
    if val_norm in PROCEDURE_ALIASES:
        return PROCEDURE_ALIASES[val_norm]
    for supported in PROCEDURE_CODES:
        if supported.casefold() == val_norm:
            return supported, False
    return val, False


class DsiSearch(LegislationSearch):
    """Search DSI Plannen en Verordeningen via the public GraphQL endpoint."""

    _cached_gemeentes: dict[str, str] = {}

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=20, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        """Close the HTTP client only when this adapter created it."""
        if self._owns_client:
            self._client.close()

    def _resolve_niscode(self, municipality: str | None) -> str | None:
        """Resolve a municipality name or numeric NIS code to a canonical NIS code."""
        if not municipality or not municipality.strip():
            return None
        cleaned = municipality.strip()
        if cleaned.isdigit():
            return cleaned

        norm = normalize_municipality_name(cleaned)
        if norm in self._cached_gemeentes:
            return self._cached_gemeentes[norm]
        if norm in _COMMON_MUNICIPALITY_NIS:
            return _COMMON_MUNICIPALITY_NIS[norm]

        self._load_gemeentes_cache()
        return self._cached_gemeentes.get(norm)

    def _load_gemeentes_cache(self) -> None:
        """Load and cache municipality NIS codes from DSI keuzelijsten endpoint."""
        try:
            response = self._client.get(GEMEENTES_URL)
            if response.status_code == 200:
                data = response.json()
                items = data.get("_embedded", {}).get("gemeentes", [])
                for item in items:
                    name = item.get("naam")
                    nis = item.get("niscode")
                    if name and nis:
                        self._cached_gemeentes[normalize_municipality_name(name)] = str(nis)
        except Exception as error:
            logger.warning("Failed to fetch DSI gemeentes keuzelijst: %s", error)

    def search(
        self,
        query: str,
        doc_type: str | None = None,
        *,
        municipality: str | None = None,
        niscode: str | None = None,
        procedure_code: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SearchOutcome:
        """Return spatial planning candidates and source completeness evidence."""
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = DEFAULT_PAGE_SIZE

        retrieved_at = datetime.now(timezone.utc)
        filter_parts: list[str] = []

        # 1. Query filter (naam and algplanid)
        raw_trimmed = query.strip(_QUOTE_CHARS)
        cleaned = _clean_query(raw_trimmed)
        variants: list[str] = [cleaned] if cleaned else []
        if raw_trimmed and raw_trimmed not in variants:
            variants.append(raw_trimmed)
        if cleaned and re.search(r"[\-–—]\s*deel\s+", cleaned, re.IGNORECASE):
            no_deel = re.sub(r"[\-–—]\s*deel\s+", "", cleaned, flags=re.IGNORECASE).strip()
            if no_deel and no_deel not in variants:
                variants.append(no_deel)
        if cleaned:
            compound_match = re.search(r"(\w+?)s?verordening(?:\s+\d{4})?$", cleaned, re.IGNORECASE)
            if compound_match:
                topic = compound_match.group(1).strip()
                if topic and topic.casefold() not in ("stedenbouwkundige", "bouw", "algemene", "gewestelijke", "gemeentelijke"):
                    if topic not in variants:
                        variants.append(topic)

        if variants:
            or_clauses = []
            for var in variants:
                esc = _escape_rsql(var)
                or_clauses.append(f'naam=like=\\"{esc}\\"')
                or_clauses.append(f'algplanid=like=\\"{esc}\\"')
            filter_parts.append(f"({','.join(or_clauses)})")

        # 2. Municipality / NIS code filter
        resolved_nis = niscode.strip() if niscode and niscode.strip() else None
        if not resolved_nis and municipality:
            resolved_nis = self._resolve_niscode(municipality)
        if resolved_nis:
            filter_parts.append(f'actieveFaseContour=ingemeente=\\"{_escape_rsql(resolved_nis)}\\"')

        # 3. Procedure code filter
        proc_target = procedure_code or doc_type
        proc_resolved = resolve_procedure_code(proc_target)
        if proc_resolved:
            code_val, is_family = proc_resolved
            esc_code = _escape_rsql(code_val)
            if is_family:
                filter_parts.append(f'code=like=\\"{esc_code}\\"')
            else:
                filter_parts.append(f'code==\\"{esc_code}\\"')

        # 4. Status filter
        if status and status.strip():
            esc_status = _escape_rsql(status.strip().upper())
            filter_parts.append(f'status==\\"{esc_status}\\"')

        rsql_filter = ";".join(filter_parts)
        filter_arg = f', filter: "{rsql_filter}"' if rsql_filter else ""

        graphql_query = f"""{{
  dossiers(page: {page}, size: {page_size}{filter_arg}, sort: "naam") {{
    page size total
    content {{
      id algplanid naam status omschrijving ficheLink
      datumBesluitTotGoedkeuring herinterpretatie
      plannendeOverheid {{ id naam }}
    }}
  }}
}}"""

        try:
            response = self._client.post(GRAPHQL_URL, json={"query": graphql_query})
        except httpx.TimeoutException as error:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="dsi",
                        kind=SearchErrorKind.TIMEOUT,
                        message=f"DSI GraphQL search timed out: {error}",
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
                        backend="dsi",
                        kind=SearchErrorKind.NETWORK,
                        message=f"DSI GraphQL search failed: {error}",
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
                        backend="dsi",
                        kind=SearchErrorKind.HTTP,
                        message=f"DSI GraphQL search returned HTTP {response.status_code}",
                        retryable=response.status_code >= 500 or response.status_code in {408, 429},
                        status_code=response.status_code,
                    )
                ],
            )

        try:
            payload = response.json()
        except Exception as error:
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="dsi",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"DSI search response could not be parsed as JSON: {error}",
                        retryable=False,
                    )
                ],
            )

        if "errors" in payload and not payload.get("data"):
            err_msg = payload["errors"][0].get("message", "Unknown GraphQL error")
            return SearchOutcome(
                complete=False,
                backend_request_count=1,
                errors=[
                    SearchError(
                        backend="dsi",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message=f"DSI GraphQL returned error: {err_msg}",
                        retryable=False,
                    )
                ],
            )

        dossiers = payload.get("data", {}).get("dossiers") or {}
        total_available = dossiers.get("total")
        content = dossiers.get("content", [])

        candidates: list[SearchResult] = []
        errors: list[SearchError] = []
        seen_ids: set[str] = set()

        for item in content:
            item_id = item.get("id") or ""
            algplanid = item.get("algplanid") or ""
            naam = item.get("naam") or ""
            fiche_link = item.get("ficheLink") or ""
            if not fiche_link and item_id:
                fiche_link = f"{BASE_URL}/fiche-detail/{item_id}"

            missing_fields: list[str] = []
            if not item_id and not algplanid:
                missing_fields.append("id")
            if not naam and not algplanid:
                missing_fields.append("naam")
            if not fiche_link:
                missing_fields.append("url")

            if missing_fields:
                errors.append(
                    SearchError(
                        backend="dsi",
                        kind=SearchErrorKind.INVALID_RESPONSE,
                        message="DSI dossier item is missing: " + ", ".join(missing_fields),
                        retryable=False,
                    )
                )
                continue

            dedup_key = algplanid or item_id
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)

            candidates.append(self._to_result(item, retrieved_at, page, fiche_link))

        truncated = False
        if total_available is not None:
            truncated = (page * page_size) < total_available

        return SearchOutcome(
            candidates=candidates,
            complete=not errors,
            truncated=truncated,
            total_available=total_available,
            backend_request_count=1,
            errors=errors,
        )

    @staticmethod
    def _to_result(
        item: dict,
        retrieved_at: datetime,
        page: int,
        fiche_link: str,
    ) -> SearchResult:
        """Convert a DSI dossier content item to a source SearchResult."""
        algplanid = item.get("algplanid") or ""
        item_id = item.get("id") or ""
        plan_type = algplanid.split("_")[0] if "_" in algplanid else ""

        overheid_data = item.get("plannendeOverheid")
        overheid_name = overheid_data.get("naam") if isinstance(overheid_data, dict) else ""

        metadata: dict[str, object] = {
            "algplanid": algplanid,
            "plan_type": plan_type,
            "status": item.get("status") or "",
            "approval_date": item.get("datumBesluitTotGoedkeuring") or "",
            "plannende_overheid": overheid_name,
            "dossier_id": item_id,
            "page": page,
        }
        if item.get("herinterpretatie") is not None:
            metadata["herinterpretatie"] = item["herinterpretatie"]

        return SearchResult(
            title=item.get("naam") or algplanid,
            url=fiche_link,
            source="dsi",
            doc_id=algplanid or item_id,
            retrieved_at=retrieved_at,
            metadata=metadata,
        )
