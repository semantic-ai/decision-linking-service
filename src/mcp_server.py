"""FastMCP server exposing legal-source searches and read-only guidelines."""

import logging
from dataclasses import asdict
from typing import Literal

from fastmcp import FastMCP

from src.models import ReferenceType, SearchOutcome
from src.tools.codex import CodexSearch
from src.tools.dsi import DsiSearch
from src.tools.ebesluitvorming import EBesluitvormingSearch
from src.tools.lblod import LblodSearch
from src.tools.memory import fetch_memory
from src.tools.reglement import ReglementSearch
from src.tools.web_search import WebSearch


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public tool types and server
# ---------------------------------------------------------------------------


Source = Literal["codex", "dsi", "ebesluitvorming", "lblod", "reglement", "web_search"]

mcp = FastMCP(
    name="IPI Legislation Search",
    instructions=(
        "Search official Flemish, Belgian federal, European, and local-decision sources, "
        "using source-specific search guidelines."
    ),
)


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------


def _serialize_outcome(outcome: SearchOutcome) -> dict:
    """Convert a complete adapter outcome into an MCP-safe dictionary.

    Candidate and error values remain otherwise unchanged; only timezone-aware
    retrieval timestamps are converted to their ISO 8601 representation.
    """
    serialized = asdict(outcome)
    for candidate, value in zip(outcome.candidates, serialized["candidates"]):
        value["retrieved_at"] = candidate.retrieved_at.isoformat()
    return serialized


# ---------------------------------------------------------------------------
# Authoritative source search tools
# ---------------------------------------------------------------------------


def _log_tool_call(
    tool_name: str,
    query: str | None = None,
    **fields: object,
) -> None:
    values = []
    if query is not None:
        values.append(f"query={query!r}")
    values.extend(
        f"{name}={value!r}"
        for name, value in fields.items()
        if value is not None
    )
    logger.info("[%s] %s", tool_name, " ".join(values))


def search_codex(
    query: str,
    doc_type: ReferenceType | None = None,
) -> dict:
    """Search Vlaamse Codex for Flemish or indexed Belgian legislation.

    Args:
        query: Short distinctive title, citeeropschrift, or identifier.
        doc_type: Optional supported Codex document category.  Omit it when the
            category is uncertain.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call("search_codex", query, category=doc_type)
    with CodexSearch() as search:
        return _serialize_outcome(search.search(query, doc_type=doc_type))


def search_ebesluitvorming(
    query: str,
    organ: str | None = None,
    meeting_date_start: str | None = None,
    meeting_date_end: str | None = None,
    title: str | None = None,
    type_id: str | None = None,
    page_size: int = 100,
) -> dict:
    """Search City of Ghent decisions and agenda items.

    Args:
        query: Full-text discovery query; may be empty when ``title`` is used.
        organ: Optional configured governing-body display name.
        meeting_date_start: Optional lower meeting-date boundary accepted by
            the Ghent search endpoint.
        meeting_date_end: Optional upper meeting-date boundary accepted by the
            Ghent search endpoint.
        title: Optional title or exact decision-number filter.
        type_id: Optional source publication-classification identifier.
        page_size: Number of rows requested from page zero.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call(
        "search_ebesluitvorming",
        query,
        organ=organ,
        meeting_date_start=meeting_date_start,
        meeting_date_end=meeting_date_end,
        title=title,
        type_id=type_id,
        page_size=page_size,
    )
    with EBesluitvormingSearch() as search:
        outcome = search.search(
            query,
            organ=organ,
            meeting_date_start=meeting_date_start,
            meeting_date_end=meeting_date_end,
            title=title,
            type_id=type_id,
            page_size=page_size,
        )
    return _serialize_outcome(outcome)


def search_reglement(
    query: str,
    regulation_type: str | None = None,
    page: int = 0,
) -> dict:
    """Search Stad Gent municipal regulations.

    Args:
        query: Full-text regulation title or subject query.
        regulation_type: Optional regulation type label or source ID.
        page: Zero-based result page.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call("search_reglement", query, category=regulation_type, page=page)
    with ReglementSearch() as search:
        outcome = search.search(
            query,
            regulation_type=regulation_type,
            page=page,
        )
    return _serialize_outcome(outcome)


def search_dsi(
    query: str,
    municipality: str | None = None,
    niscode: str | None = None,
    procedure_code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Search DSI Plannen en Verordeningen for spatial planning instruments.

    Args:
        query: Plan name or identifier (matches against naam and algplanid).
        municipality: Optional municipality display name to filter by location.
        niscode: Optional 5-digit NIS code to filter by location.
        procedure_code: Optional plan type code or alias (GWP, gewRUP, gemRUP, BPA, APA, etc.).
        status: Optional status filter (e.g. 'DEFINITIEF').
        page: One-based result page.
        page_size: Results per page.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call(
        "search_dsi",
        query,
        municipality=municipality,
        niscode=niscode,
        procedure_code=procedure_code,
        status=status,
        page=page,
    )
    with DsiSearch() as search:
        outcome = search.search(
            query,
            municipality=municipality,
            niscode=niscode,
            procedure_code=procedure_code,
            status=status,
            page=page,
            page_size=page_size,
        )
    return _serialize_outcome(outcome)


def search_lblod(
    query: str,
    municipality: str,
    governing_body: str | None = None,
    session_date: str | None = None,
) -> dict:
    """Search local decisions published through Lokaal Beslist/LBLOD.

    Args:
        query: Exact decision number or short distinctive title/subject.
        municipality: Required municipality display name.
        governing_body: Optional governing-body name.
        session_date: Optional session date in ``YYYY-MM-DD`` format.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call(
        "search_lblod",
        query,
        municipality=municipality,
        governing_body=governing_body,
        session_date=session_date,
    )
    with LblodSearch() as search:
        outcome = search.search(
            query,
            municipality=municipality,
            governing_body=governing_body,
            session_date=session_date,
        )
    return _serialize_outcome(outcome)


def search_web(
    query: str,
    doc_type: ReferenceType | None = None,
) -> dict:
    """Search official Belgian federal and European legislation.

    Args:
        query: Short distinctive title, identifier, or legal subject.
        doc_type: Optional document category, currently retained for a common
            MCP signature but not used by this source.

    Returns:
        Candidates and structured completeness/failure evidence.
    """
    _log_tool_call("search_web", query, category=doc_type)
    with WebSearch() as search:
        return _serialize_outcome(search.search(query, doc_type=doc_type))


# ---------------------------------------------------------------------------
# Source guideline tools
# ---------------------------------------------------------------------------


def fetch_guidelines(source: Source) -> str:
    """Return the complete search guideline for one supported source.

    Args:
        source: Source whose search guide must be loaded.

    Returns:
        Complete Markdown guide, including previously learned lessons.
    """
    _log_tool_call("fetch_guidelines", source=source)
    return fetch_memory(source)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


mcp.tool(search_codex)
mcp.tool(search_ebesluitvorming)
mcp.tool(search_reglement)
mcp.tool(search_dsi)
mcp.tool(search_lblod)
mcp.tool(search_web)
mcp.tool(fetch_guidelines)


# ---------------------------------------------------------------------------
# Command-line entry point
# ---------------------------------------------------------------------------


def cli() -> None:
    """Run the standalone server over Streamable HTTP at ``/mcp``."""
    mcp.run(transport="http", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    cli()
