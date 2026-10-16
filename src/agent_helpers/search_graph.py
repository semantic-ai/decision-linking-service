"""Structured LangGraph workflow for resolving one legal reference.

Graph: Classify reference -> Fetch guidelines -> Search candidates
    -> Validate candidates -> END, with one bounded fallback pivot.

Classification selects one authoritative source, its complete guideline is
fetched once per pass, and the candidate-search node may call only that source
tool until it has enough evidence or reaches the Python-enforced call limit. A
single bounded fallback pass is allowed only after unresolved validation.
"""

import json
import logging
import re
from time import perf_counter
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agent_helpers.models import (
    AttemptTrace,
    ClassifiedReference,
    DocumentContext,
    ResolutionStatus,
    ResolutionReasonCode,
    SearchGraphState,
    SearchSource,
    ValidationDecision,
)
from src.agent_helpers.prompts import PromptSet
from src.agent_helpers.search_execution import (
    candidate_for_model as _candidate_for_model,
    execute_candidate_search,
)
from src.models import SearchResult


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool configuration
# ---------------------------------------------------------------------------


SEARCH_TOOL_BY_SOURCE = {
    SearchSource.CODEX: "search_codex",
    SearchSource.WEB_SEARCH: "search_web",
    SearchSource.EBESLUITVORMING: "search_ebesluitvorming",
    SearchSource.LBLOD: "search_lblod",
    SearchSource.REGLEMENT: "search_reglement",
    SearchSource.DSI: "search_dsi",
}

REQUIRED_TOOLS = {
    *SEARCH_TOOL_BY_SOURCE.values(),
    "fetch_guidelines",
}

# ---------------------------------------------------------------------------
# State and prompt helpers
# ---------------------------------------------------------------------------


def initial_search_state(
    reference: str,
    document_context: DocumentContext | None = None,
) -> SearchGraphState:
    """Build the complete initial state expected by the compiled graph."""
    logger.info("Graph start reference=%r", reference)
    return {
        "reference": reference,
        "document_context": document_context,
        "classified_reference": None,
        "guidelines": "",
        "guideline_error": "",
        "attempt_count": 0,
        "trace": [],
        "candidates": [],
        "resolution_status": ResolutionStatus.UNRESOLVED,
        "reason_code": ResolutionReasonCode.SOURCE_NO_MATCH,
        "results": [],
        "reason": "",
        "caveat": None,
        "proposed_guideline_lesson": None,
        "source_queue": [],
        "current_source": None,
        "pivot_count": 0,
    }


def _serialize_json(value: Any) -> str:
    """Serialize prompt and tool context as readable, Unicode-preserving JSON."""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _format_document_context_guidance(context: DocumentContext) -> str:
    """Format origin metadata as fallback-only classification guidance."""
    values = context.model_dump(mode="json", exclude_none=True)
    return f"""Document origin context (fallbacks only):
{_serialize_json(values)}

Use this context only to fill classification fields that the supplied reference
does not establish. Facts stated by the reference always take precedence. In
particular, an explicitly named municipality, governing body, governmental
level, or source must not be replaced by this context; a reference to a
decision made by another city remains associated with that city.

When the reference is silent, use the supplied origin and its associated
governmental levels as defaults: local decisions may default to the context
municipality and governing body, while general legislation may default to the
context's indicated jurisdiction or, when the context describes a municipality
of origin, its associated regional and Belgian federal levels according to the
instrument's wording. Context is not proof of a fact and should not override a
contrary cue. Keep a field unknown when neither the reference nor this context
provides a reasonable fallback. If the reference has a recognizable legal type
and date and the fallback context resolves its governmental level, select the
corresponding supported source rather than leaving source null merely because
the title is generic: use ebesluitvorming for a Ghent local decision, web_search
for federal or European legislation, and codex for regional legislation. Leave
source null only when the reference and fallback context still do not identify
a supported source safely, or when they identify an unsupported municipality
or source."""


def _format_search_context_guidance(context: DocumentContext) -> str:
    """Format document and reference context as search qualifiers."""
    values = context.model_dump(mode="json", exclude_none=True)
    return f"""Reference and document context (discovery qualifiers):
{_serialize_json(values)}

Use concrete qualifiers such as streets, house numbers, projects, objects,
municipalities, governing bodies, and decision numbers as search terms when
they help distinguish the requested instrument. Keep the canonical reference
unchanged: never promote a qualifier into its title or date, and do not treat
context alone as proof of a candidate."""


def _format_validation_context_guidance(context: DocumentContext) -> str:
    """Format document and reference context as candidate evidence."""
    values = context.model_dump(mode="json", exclude_none=True)
    return f"""Reference and document context (disambiguation evidence):
{_serialize_json(values)}

When candidates share a date and generic subject, prefer the candidate whose
official title or metadata matches the contextual street, project, address,
municipality, governing body, or other concrete qualifier. Context is
supporting evidence, not proof: if the candidates do not establish a match,
keep the outcome ambiguous rather than selecting by rank alone."""


def _format_classified_reference(
    reference: ClassifiedReference,
    *,
    include_locators: bool,
) -> str:
    """Serialize only the normalized facts beneficial to one model operation."""
    excluded = {"reason"}
    if not include_locators:
        excluded.update({"article", "paragraph", "subsection", "point"})
    return _serialize_json(reference.model_dump(mode="json", exclude=excluded))


def _format_search_context(trace: list[AttemptTrace], guideline_error: str) -> str:
    """Serialize only search attempts and operational errors for validation."""
    return _serialize_json(
        {
            "guideline_error": guideline_error or None,
            "attempts": [attempt.model_dump(mode="json") for attempt in trace],
        }
    )


def _format_candidates_for_prompt(candidates: list[SearchResult]) -> str:
    """Serialize compact candidates with indices that the validator may select."""
    indexed = [
        {"index": index, **_candidate_for_model(candidate)}
        for index, candidate in enumerate(candidates)
    ]
    return _serialize_json(indexed) if indexed else "[]"


def _dedupe_by_identifier(candidates: list[SearchResult]) -> list[SearchResult]:
    """Collapse candidates that share one official identifier.

    ``_extract_doc_id`` preserves the source casing of a CELEX or NUMAC value, so
    case-variant representations of the same instrument otherwise reach the
    validator as competing candidates. Candidates without an identifier are kept
    and keyed by URL so distinct records are never merged.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[SearchResult] = []
    for candidate in candidates:
        identifier = candidate.doc_id.strip().upper() if candidate.doc_id else ""
        key = (candidate.source, identifier or candidate.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


MAX_VALIDATION_CANDIDATES = 50


_DUTCH_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}


def _parse_reglement_date(value: Any) -> date | None:
    """Parse the Dutch date format returned in Reglementen metadata."""
    if not isinstance(value, str):
        return None
    match = re.search(
        r"\b(\d{1,2})\s+([a-z]+)\s+(\d{4})\b",
        value.casefold(),
    )
    if not match or match.group(2) not in _DUTCH_MONTHS:
        return None
    try:
        return date(
            int(match.group(3)),
            _DUTCH_MONTHS[match.group(2)],
            int(match.group(1)),
        )
    except ValueError:
        return None


def _is_current_reglement_equivalent(
    classified: ClassifiedReference,
    candidate: SearchResult,
) -> bool:
    """Recognize a later official page for a dated regulation reference."""
    if (
        classified.source != SearchSource.REGLEMENT
        or classified.document_date is None
        or candidate.source != SearchSource.REGLEMENT
        or not classified.title
    ):
        return False

    title_similarity = SequenceMatcher(
        None,
        classified.title.casefold(),
        candidate.title.casefold(),
    ).ratio()
    if title_similarity < 0.9:
        return False

    metadata = candidate.metadata
    if "reglement" not in str(metadata.get("type", "")).casefold():
        return False
    return any(
        (candidate_date := _parse_reglement_date(metadata.get(field)))
        and candidate_date > classified.document_date
        for field in ("approval_date", "announcement_date")
    )


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


class SearchGraphBuilder:
    """Build and compile the linear legal-reference search graph.

    Parameters
    ----------
    llm
        Chat model used for classification, bounded candidate search, and
        validation.
    tools
        Required MCP tools keyed by their MCP name.
    prompts
        Validated prompts used by the three model-driven operations.
    max_search_attempts
        Maximum source-tool calls allowed inside candidate search.

    Raises
    ------
    ValueError
        If one or more required MCP tools are missing.
    """

    def __init__(
        self,
        *,
        llm,
        tools: dict[str, Any],
        prompts: PromptSet,
        max_search_attempts: int = 3,
        max_pivots: int = 1,
    ):
        missing = REQUIRED_TOOLS - set(tools)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"MCP server is missing required tools: {names}")

        self.llm = llm
        self.tools = tools
        self.prompts = prompts
        self.max_search_attempts = max_search_attempts
        self.max_pivots = max_pivots
        self._reference_classifier = llm.with_structured_output(ClassifiedReference)
        self._validator = llm.with_structured_output(ValidationDecision)

    # ------------------------------------------------------------------
    # Node: CLASSIFY REFERENCE
    # ------------------------------------------------------------------
    async def classify_reference_node(self, state: SearchGraphState) -> dict:
        """Normalize the reference, classify its type, and select one source.

        Missing values stay null.  Python additionally prevents an LBLOD call
        without the municipality required by that source's schema.
        """
        started_at = perf_counter()
        classified = await self._reference_classifier.ainvoke(
            [
                SystemMessage(content=self.prompts.classify_reference),
                *(
                    [
                        SystemMessage(
                            content=_format_document_context_guidance(context)
                        )
                    ]
                    if (context := state.get("document_context")) is not None
                    else []
                ),
                HumanMessage(content=state["reference"]),
            ]
        )

        if classified.source == SearchSource.LBLOD and not classified.municipality:
            classified = classified.model_copy(
                update={
                    "source": None,
                    "reason": (
                        f"{classified.reason} LBLOD requires an explicit municipality."
                    ),
                }
            )

        source_queue: list[SearchSource] = []
        for source in [classified.source, *classified.fallback_sources]:
            if source is None or source in source_queue:
                continue
            if source == SearchSource.LBLOD and not classified.municipality:
                continue
            source_queue.append(source)

        logger.info(
            "Graph classification reference=%r source=%s fallbacks=%s duration_ms=%.0f",
            state["reference"],
            classified.source.value if classified.source else None,
            [source.value for source in source_queue[1:]],
            (perf_counter() - started_at) * 1000,
        )

        return {
            "classified_reference": classified,
            "resolution_status": ResolutionStatus.UNRESOLVED,
            "reason_code": ResolutionReasonCode.UNSUPPORTED_SOURCE,
            "results": [],
            "reason": classified.reason,
            "caveat": None,
            "source_queue": source_queue,
            "current_source": source_queue[0] if source_queue else None,
            "pivot_count": 0,
        }

    # ------------------------------------------------------------------
    # Conditional edge: AFTER CLASSIFICATION
    # ------------------------------------------------------------------
    @staticmethod
    def _route_after_classification(state: SearchGraphState) -> str:
        """Continue only when classification selected a supported source."""
        route = "search" if state.get("current_source") else "finish"
        logger.info(
            "Graph route after classification next=%s source=%s",
            route,
            state["current_source"].value if state.get("current_source") else None,
        )
        return route

    def _route_after_validation(self, state: SearchGraphState) -> str:
        """Pivot once only when validation remains unresolved."""
        if state["resolution_status"] != ResolutionStatus.UNRESOLVED:
            route = "finish"
        elif state["pivot_count"] >= self.max_pivots:
            route = "finish"
        else:
            current_source = state.get("current_source")
            if current_source not in state["source_queue"]:
                route = "finish"
            else:
                current_index = state["source_queue"].index(current_source)
                route = (
                    "pivot"
                    if current_index + 1 < len(state["source_queue"])
                    else "finish"
                )
        logger.info(
            "Graph route after validation status=%s next=%s",
            state["resolution_status"].value,
            route,
        )
        return route

    async def pivot_source_node(self, state: SearchGraphState) -> dict:
        """Advance to the next classified fallback source."""
        current_source = state.get("current_source")
        if current_source not in state["source_queue"]:
            return {}
        current_index = state["source_queue"].index(current_source)
        next_source = state["source_queue"][current_index + 1]
        logger.info(
            "Graph pivot source=%s next_source=%s pivot=%d/%d",
            current_source.value,
            next_source.value,
            state["pivot_count"] + 1,
            self.max_pivots,
        )
        return {
            "current_source": next_source,
            "pivot_count": state["pivot_count"] + 1,
            "guidelines": "",
            "guideline_error": "",
        }

    # ------------------------------------------------------------------
    # Node: FETCH GUIDELINES
    # ------------------------------------------------------------------
    async def fetch_guidelines_node(self, state: SearchGraphState) -> dict:
        """Load the selected source's complete guideline exactly once.

        A read error is retained for final validation and prevents searching
        without the required source instructions.
        """
        source = state.get("current_source")
        if source is None:
            return {}

        started_at = perf_counter()
        try:
            guidelines = await self.tools["fetch_guidelines"].ainvoke(
                {"source": source.value}
            )
            if not isinstance(guidelines, str):
                guidelines = str(guidelines)
            logger.info(
                "Graph guidelines loaded source=%s characters=%d duration_ms=%.0f",
                source.value,
                len(guidelines),
                (perf_counter() - started_at) * 1000,
            )
            return {"guidelines": guidelines, "guideline_error": ""}
        except Exception as error:
            logger.warning(
                "Failed to fetch %s guidelines: %s duration_ms=%.0f",
                source,
                error,
                (perf_counter() - started_at) * 1000,
            )
            return {
                "guidelines": "",
                "guideline_error": f"Failed to fetch source guidelines: {error}",
            }

    # ------------------------------------------------------------------
    # Node: SEARCH CANDIDATES
    # ------------------------------------------------------------------
    async def search_candidates_node(self, state: SearchGraphState) -> dict:
        """Run the bounded candidate-search operation for the selected source."""
        classified = state["classified_reference"]
        source = state.get("current_source")
        if classified is None or source is None:
            return {}
        if state["guideline_error"]:
            return {}

        tool_name = SEARCH_TOOL_BY_SOURCE[source]
        tool = self.tools[tool_name]
        started_at = perf_counter()
        search_model = self.llm.bind_tools([tool])
        prompt = self.prompts.search_candidates.format(
            tool_name=tool_name,
            max_search_attempts=self.max_search_attempts,
            classified_reference=_format_classified_reference(
                classified,
                include_locators=False,
            ),
            guidelines=state["guidelines"],
        )
        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=state["reference"]),
        ]
        if (context := state.get("document_context")) is not None:
            messages.insert(1, SystemMessage(content=_format_search_context_guidance(context)))
        result = await execute_candidate_search(
            search_model=search_model,
            tool=tool,
            tool_name=tool_name,
            source=source,
            messages=messages,
            max_search_attempts=self.max_search_attempts,
            classified_reference=classified,
            trace=state["trace"],
            candidates=state["candidates"],
        )
        logger.info(
            "Graph node=search source=%s tool=%s existing_candidates=%d duration_ms=%.0f",
            source.value,
            tool_name,
            len(state["candidates"]),
            (perf_counter() - started_at) * 1000,
        )
        return result

    # ------------------------------------------------------------------
    # Node: VALIDATE CANDIDATES
    # ------------------------------------------------------------------
    async def validate_candidates_node(self, state: SearchGraphState) -> dict:
        """Independently select confirmed candidates from the search registry.

        The validator has no tools and may select only supplied indices.  Python
        verifies index bounds and maps them back to unchanged source records.
        Invalid model selections are converted to an unresolved result.
        """
        classified = state["classified_reference"]
        if classified is None:
            return {
                "resolution_status": ResolutionStatus.UNRESOLVED,
                "reason_code": ResolutionReasonCode.UNSUPPORTED_SOURCE,
                "results": [],
                "reason": "The reference was not classified.",
                "caveat": None,
            }

        candidates = _dedupe_by_identifier(state["candidates"])[:MAX_VALIDATION_CANDIDATES]
        started_at = perf_counter()
        prompt = self.prompts.validate_candidates.format(
            classified_reference=_format_classified_reference(
                classified,
                include_locators=True,
            ),
            search_context=_format_search_context(
                state["trace"],
                state["guideline_error"],
            ),
            candidates=_format_candidates_for_prompt(candidates),
        )

        messages = [
            SystemMessage(content=prompt),
        ]
        if (context := state.get("document_context")) is not None:
            messages.append(SystemMessage(content=_format_validation_context_guidance(context)))
        messages.append(HumanMessage(content=state["reference"]))

        try:
            decision = await self._validator.ainvoke(
                messages
            )
        except Exception as error:
            logger.warning(
                "Candidate validation failed: %s candidates=%d unique_candidates=%d duration_ms=%.0f",
                error,
                len(state["candidates"]),
                len(candidates),
                (perf_counter() - started_at) * 1000,
            )
            return {
                "resolution_status": ResolutionStatus.UNRESOLVED,
                "reason_code": ResolutionReasonCode.VALIDATION_FAILURE,
                "results": [],
                "reason": f"Candidate validation failed: {error}",
                "caveat": None,
            }

        selected_indices = list(dict.fromkeys(decision.selected_indices))
        valid_indices = all(
            0 <= index < len(candidates) for index in selected_indices
        )
        expected_count = {
            ResolutionStatus.RESOLVED: len(selected_indices) == 1,
            ResolutionStatus.RESOLVED_WITH_CAVEAT: len(selected_indices) == 1,
            ResolutionStatus.AMBIGUOUS: len(selected_indices) >= 2,
            ResolutionStatus.UNRESOLVED: not selected_indices,
        }.get(decision.status, False)
        if not valid_indices or not expected_count:
            logger.info(
                "Graph validation status=unresolved selected=%d candidates=%d unique_candidates=%d duration_ms=%.0f",
                len(selected_indices),
                len(state["candidates"]),
                len(candidates),
                (perf_counter() - started_at) * 1000,
            )
            return {
                "resolution_status": ResolutionStatus.UNRESOLVED,
                "reason_code": ResolutionReasonCode.VALIDATION_FAILURE,
                "results": [],
                "reason": (
                    "The validator selected candidate indices that were not "
                    "returned by the source."
                ),
                "caveat": None,
            }

        effective_status = decision.status
        effective_reason_code = decision.reason_code
        effective_reason = decision.reason
        effective_caveat = decision.caveat
        if decision.status == ResolutionStatus.RESOLVED:
            candidate = candidates[selected_indices[0]]
            if _is_current_reglement_equivalent(classified, candidate):
                effective_status = ResolutionStatus.RESOLVED_WITH_CAVEAT
                effective_reason_code = ResolutionReasonCode.CURRENT_EQUIVALENT
                effective_reason = (
                    f"{decision.reason} The supplied historical version was not "
                    "located; this is the later current official equivalent."
                )
                effective_caveat = (
                    "The candidate is a later current Reglementen page than the "
                    "requested historical approval date."
                )

        if effective_status == ResolutionStatus.RESOLVED_WITH_CAVEAT:
            candidate = candidates[selected_indices[0]]
            attempts = [
                attempt
                for attempt in state["trace"]
                if attempt.source == SearchSource.REGLEMENT
            ]
            if candidate.source != SearchSource.REGLEMENT:
                return {
                    "resolution_status": ResolutionStatus.UNRESOLVED,
                    "reason_code": ResolutionReasonCode.VERSION_MISMATCH,
                    "results": [],
                    "reason": "A qualified outcome is only supported for reglement candidates.",
                    "caveat": None,
                }
            if not attempts or any(
                not attempt.complete or attempt.truncated or attempt.source_errors
                for attempt in attempts
            ):
                return {
                    "resolution_status": ResolutionStatus.UNRESOLVED,
                    "reason_code": ResolutionReasonCode.SOURCE_INCOMPLETE,
                    "results": [],
                    "reason": "The authoritative regulation search was incomplete.",
                    "caveat": None,
                }

        logger.info(
            "Graph validation status=%s selected=%d candidates=%d unique_candidates=%d duration_ms=%.0f",
            decision.status.value,
            len(selected_indices),
            len(state["candidates"]),
            len(candidates),
            (perf_counter() - started_at) * 1000,
        )
        return {
            "resolution_status": effective_status,
            "reason_code": effective_reason_code,
            "results": [candidates[index] for index in selected_indices],
            "reason": effective_reason,
            "caveat": effective_caveat,
            "proposed_guideline_lesson": decision.proposed_guideline_lesson,
        }

    # ------------------------------------------------------------------
    # Build and compile
    # ------------------------------------------------------------------
    def build(self):
        """Construct and return the compiled legal-reference search graph."""
        graph = StateGraph(SearchGraphState)  # type: ignore[bad-specialization]

        # Nodes
        graph.add_node("classify_reference", self.classify_reference_node)
        graph.add_node("fetch_guidelines", self.fetch_guidelines_node)
        graph.add_node("search_candidates", self.search_candidates_node)
        graph.add_node("validate_candidates", self.validate_candidates_node)
        graph.add_node("pivot_source", self.pivot_source_node)

        # Edges
        graph.add_edge(START, "classify_reference")
        graph.add_conditional_edges(
            "classify_reference",
            self._route_after_classification,
            {"search": "fetch_guidelines", "finish": END},
        )
        graph.add_edge("fetch_guidelines", "search_candidates")
        graph.add_edge("search_candidates", "validate_candidates")
        graph.add_conditional_edges(
            "validate_candidates",
            self._route_after_validation,
            {"pivot": "pivot_source", "finish": END},
        )
        graph.add_edge("pivot_source", "fetch_guidelines")
        return graph.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_search_graph(
    *,
    llm,
    tools: dict[str, Any],
    prompts: PromptSet,
    max_search_attempts: int = 3,
    max_pivots: int = 1,
):
    """Create a compiled legal-reference search graph ready for invocation.

    The graph accepts the dictionary returned by :func:`initial_search_state`
    and returns completed state containing the terminal resolution, unchanged
    selected results, compact per-call trace, unique candidates, and an optional
    guideline lesson proposal for the selected source guideline.
    """
    return SearchGraphBuilder(
        llm=llm,
        tools=tools,
        prompts=prompts,
        max_search_attempts=max_search_attempts,
        max_pivots=max_pivots,
    ).build()
