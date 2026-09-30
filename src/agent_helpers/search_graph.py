"""Structured LangGraph workflow for resolving one legal reference.

Graph: Classify reference -> Fetch guidelines -> Search candidates
       -> Validate candidates -> END

The graph is deliberately linear.  Classification selects one authoritative
source, its complete guideline is fetched once, and the candidate-search node
may call only that source tool until it has enough evidence or reaches the
Python-enforced call limit.  A separate structured validation call makes the
terminal resolution decision from unchanged source results and may attach one
optional reusable lesson for the selected source guideline.
"""

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agent_helpers.models import (
    AttemptTrace,
    ClassifiedReference,
    DocumentContext,
    ResolutionStatus,
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
        "results": [],
        "reason": "",
        "proposed_guideline_lesson": None,
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
    ):
        missing = REQUIRED_TOOLS - set(tools)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"MCP server is missing required tools: {names}")

        self.llm = llm
        self.tools = tools
        self.prompts = prompts
        self.max_search_attempts = max_search_attempts
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

        return {
            "classified_reference": classified,
            "resolution_status": ResolutionStatus.UNRESOLVED,
            "results": [],
            "reason": classified.reason,
        }

    # ------------------------------------------------------------------
    # Conditional edge: AFTER CLASSIFICATION
    # ------------------------------------------------------------------
    @staticmethod
    def _route_after_classification(state: SearchGraphState) -> str:
        """Continue only when classification selected a supported source."""
        classified = state.get("classified_reference")
        return "search" if classified and classified.source else "finish"

    # ------------------------------------------------------------------
    # Node: FETCH GUIDELINES
    # ------------------------------------------------------------------
    async def fetch_guidelines_node(self, state: SearchGraphState) -> dict:
        """Load the selected source's complete guideline exactly once.

        A read error is retained for final validation and prevents searching
        without the required source instructions.
        """
        classified = state["classified_reference"]
        if classified is None or classified.source is None:
            return {}

        try:
            guidelines = await self.tools["fetch_guidelines"].ainvoke(
                {"source": classified.source.value}
            )
            if not isinstance(guidelines, str):
                guidelines = str(guidelines)
            return {"guidelines": guidelines, "guideline_error": ""}
        except Exception as error:
            logger.warning(
                "Failed to fetch %s guidelines: %s", classified.source, error
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
        if classified is None or classified.source is None:
            return {}
        if state["guideline_error"]:
            return {}

        source = classified.source
        tool_name = SEARCH_TOOL_BY_SOURCE[source]
        tool = self.tools[tool_name]
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
        return await execute_candidate_search(
            search_model=search_model,
            tool=tool,
            tool_name=tool_name,
            source=source,
            messages=messages,
            max_search_attempts=self.max_search_attempts,
            trace=state["trace"],
            candidates=state["candidates"],
        )

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
                "results": [],
                "reason": "The reference was not classified.",
            }

        candidates = _dedupe_by_identifier(state["candidates"])
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

        try:
            decision = await self._validator.ainvoke(
                [
                    SystemMessage(content=prompt),
                    HumanMessage(content=state["reference"]),
                ]
            )
        except Exception as error:
            logger.warning("Candidate validation failed: %s", error)
            return {
                "resolution_status": ResolutionStatus.UNRESOLVED,
                "results": [],
                "reason": f"Candidate validation failed: {error}",
            }

        selected_indices = list(dict.fromkeys(decision.selected_indices))
        valid_indices = all(
            0 <= index < len(candidates) for index in selected_indices
        )
        expected_count = {
            ResolutionStatus.RESOLVED: len(selected_indices) == 1,
            ResolutionStatus.AMBIGUOUS: len(selected_indices) >= 2,
            ResolutionStatus.UNRESOLVED: not selected_indices,
        }[decision.status]
        if not valid_indices or not expected_count:
            return {
                "resolution_status": ResolutionStatus.UNRESOLVED,
                "results": [],
                "reason": (
                    "The validator selected candidate indices that were not "
                    "returned by the source."
                ),
            }

        return {
            "resolution_status": decision.status,
            "results": [candidates[index] for index in selected_indices],
            "reason": decision.reason,
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

        # Edges
        graph.add_edge(START, "classify_reference")
        graph.add_conditional_edges(
            "classify_reference",
            self._route_after_classification,
            {"search": "fetch_guidelines", "finish": END},
        )
        graph.add_edge("fetch_guidelines", "search_candidates")
        graph.add_edge("search_candidates", "validate_candidates")
        graph.add_edge("validate_candidates", END)
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
    ).build()
