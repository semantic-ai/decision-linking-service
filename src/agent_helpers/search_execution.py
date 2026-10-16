"""Bounded candidate-search execution for the legal-reference workflow."""

import json
import logging
from time import perf_counter
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from pydantic import TypeAdapter

from src.agent_helpers.models import AttemptTrace, ClassifiedReference, SearchSource
from src.models import SearchOutcome, SearchResult


logger = logging.getLogger(__name__)

_SEARCH_OUTCOME_ADAPTER = TypeAdapter(SearchOutcome)
_SEARCH_RESULT_ADAPTER = TypeAdapter(SearchResult)


def _serialize_json(value: Any) -> str:
    """Serialize tool context as readable, Unicode-preserving JSON."""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _argument_signature(arguments: dict[str, Any]) -> str:
    """Return a stable signature used to detect repeated search arguments."""
    return json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def candidate_for_model(candidate: SearchResult) -> dict[str, Any]:
    """Return only candidate identity evidence useful to an LLM node."""
    value = _SEARCH_RESULT_ADAPTER.dump_python(candidate, mode="json")
    value.pop("url", None)
    value.pop("retrieved_at", None)
    return value


def _parse_search_outcome(value: Any) -> SearchOutcome:
    """Validate supported structured MCP result shapes as a search outcome."""
    if value is None:
        raise ValueError("Search tool returned no SearchOutcome")
    if isinstance(value, str):
        value = json.loads(value)
    while isinstance(value, dict) and set(value) == {"result"}:
        value = value["result"]
    if isinstance(value, SearchOutcome):
        return value
    if not isinstance(value, dict):
        raise ValueError("Search tool must return a SearchOutcome object")
    return _SEARCH_OUTCOME_ADAPTER.validate_python(value)


def _tool_message_content(
    outcome: SearchOutcome,
    invocation_error: str | None,
) -> str:
    """Build the structured search outcome shown to the next model turn."""
    value = _SEARCH_OUTCOME_ADAPTER.dump_python(outcome, mode="json")
    value["candidates"] = [
        candidate_for_model(candidate) for candidate in outcome.candidates
    ]
    value["invocation_error"] = invocation_error
    return _serialize_json(value)


def _allows_identical_retry(outcome: SearchOutcome) -> bool:
    """Return whether one identical retry may follow this source outcome."""
    return bool(outcome.errors) and all(error.retryable for error in outcome.errors)


def _add_unique_candidates(
    registry: list[SearchResult],
    candidates: list[SearchResult],
) -> None:
    """Append candidates not already present by source and document identity."""
    known = {
        (candidate.source, candidate.doc_id or candidate.url) for candidate in registry
    }
    for candidate in candidates:
        identity = (candidate.source, candidate.doc_id or candidate.url)
        if identity not in known:
            registry.append(candidate)
            known.add(identity)


def _is_exact_identifier_match(
    classified: ClassifiedReference | None,
    source: SearchSource,
    arguments: dict[str, Any],
    outcome: SearchOutcome,
) -> bool:
    identifier = (classified.identifier if classified else None) or ""
    if len(identifier.strip()) < 5 or not outcome.complete or outcome.truncated or outcome.errors:
        return False
    identifier_key = "".join(identifier.casefold().split())
    argument_text = "".join(str(arguments).casefold().split())
    if identifier_key not in argument_text:
        return False
    matches = []
    for candidate in outcome.candidates:
        candidate_text = "".join(
            f"{candidate.title} {candidate.doc_id} {candidate.metadata}".casefold().split()
        )
        if identifier_key in candidate_text:
            matches.append(candidate)
    return len(matches) == 1 and (source == SearchSource.EBESLUITVORMING or identifier_key in argument_text)


async def execute_candidate_search(
    *,
    search_model,
    tool,
    tool_name: str,
    source: SearchSource,
    messages: list[BaseMessage],
    max_search_attempts: int,
    classified_reference: ClassifiedReference | None = None,
    trace: list[AttemptTrace],
    candidates: list[SearchResult],
) -> dict[str, Any]:
    """Run the bounded model/tool conversation and return graph state updates."""
    trace = list(trace)
    candidates = list(candidates)
    attempts_before = len(trace)
    argument_use_counts: dict[str, int] = {}
    retryable_repeat_signatures: set[str] = set()
    for attempt in trace:
        if not attempt.arguments or (
            attempt.error and "repeat an earlier call" in attempt.error
        ):
            continue
        signature = _argument_signature(attempt.arguments)
        argument_use_counts[signature] = argument_use_counts.get(signature, 0) + 1
        if (
            argument_use_counts[signature] == 1
            and attempt.error is None
            and attempt.source_errors
            and all(error.retryable for error in attempt.source_errors)
        ):
            retryable_repeat_signatures.add(signature)
        else:
            retryable_repeat_signatures.discard(signature)

    while len(trace) - attempts_before < max_search_attempts:
        llm_started_at = perf_counter()
        try:
            response = await search_model.ainvoke(messages)
            llm_ms = (perf_counter() - llm_started_at) * 1000
        except Exception as error:
            llm_ms = (perf_counter() - llm_started_at) * 1000
            logger.warning(
                "Candidate-search model failed: %s duration_ms=%.0f",
                error,
                llm_ms,
            )
            trace.append(
                AttemptTrace(
                    attempt=len(trace) + 1,
                    source=source,
                    tool=tool_name,
                    complete=False,
                    error=f"Candidate-search model failed: {error}",
                )
            )
            break

        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break

        remaining = max_search_attempts - (len(trace) - attempts_before)
        stop_after_tool = False
        for call in tool_calls[:remaining]:
            attempt_number = len(trace) + 1
            call_name = call.get("name") or ""
            arguments: dict[str, Any] = {}
            outcome = SearchOutcome()
            error_text: str | None = None
            tool_started_at = perf_counter()

            try:
                arguments = dict(call.get("args") or {})
                if call_name != tool_name:
                    raise ValueError(
                        f"Model called {call_name!r}, expected {tool_name!r}"
                    )

                argument_signature = _argument_signature(arguments)
                use_count = argument_use_counts.get(argument_signature, 0)
                retry_allowed = (
                    use_count == 1
                    and argument_signature in retryable_repeat_signatures
                )
                if use_count and not retry_allowed:
                    raise ValueError("Search arguments repeat an earlier call")
                retryable_repeat_signatures.discard(argument_signature)
                argument_use_counts[argument_signature] = use_count + 1

                outcome = _parse_search_outcome(await tool.ainvoke(arguments))
                if argument_use_counts[
                    argument_signature
                ] == 1 and _allows_identical_retry(outcome):
                    retryable_repeat_signatures.add(argument_signature)
                _add_unique_candidates(candidates, outcome.candidates)
            except Exception as error:
                outcome = SearchOutcome(complete=False)
                error_text = str(error)
                logger.warning(
                    "Search attempt with %s failed: %s tool_ms=%.0f llm_ms=%.0f",
                    tool_name,
                    error,
                    (perf_counter() - tool_started_at) * 1000,
                    llm_ms,
                )

            logger.info(
                "Graph search result tool=%s candidates=%d complete=%s truncated=%s attempt=%d/%d tool_ms=%.0f llm_ms=%.0f",
                tool_name,
                len(outcome.candidates),
                outcome.complete,
                outcome.truncated,
                attempt_number,
                max_search_attempts,
                (perf_counter() - tool_started_at) * 1000,
                llm_ms,
            )

            trace.append(
                AttemptTrace(
                    attempt=attempt_number,
                    source=source,
                    tool=tool_name,
                    arguments=arguments,
                    candidate_ids=[
                        candidate.doc_id for candidate in outcome.candidates
                    ],
                    complete=outcome.complete,
                    truncated=outcome.truncated,
                    total_available=outcome.total_available,
                    backend_request_count=outcome.backend_request_count,
                    source_errors=outcome.errors,
                    error=error_text,
                )
            )
            messages.append(
                ToolMessage(
                    content=_tool_message_content(outcome, error_text),
                    tool_call_id=call.get("id") or f"call-{attempt_number}",
                    name=call_name or tool_name,
                )
            )
            if _is_exact_identifier_match(
                classified_reference,
                source,
                arguments,
                outcome,
            ):
                stop_after_tool = True
                break
        if stop_after_tool:
            break

    return {
        "attempt_count": len(trace),
        "trace": trace,
        "candidates": candidates,
    }
