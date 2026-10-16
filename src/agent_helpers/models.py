"""Configuration, workflow, and response models for the legal-reference agent."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any
from typing_extensions import TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models import ReferenceType, SearchError, SearchResult


# ---------------------------------------------------------------------------
# Shared source and status values
# ---------------------------------------------------------------------------


class SearchSource(StrEnum):
    """Authoritative sources supported by the search agent."""

    CODEX = "codex"
    WEB_SEARCH = "web_search"
    EBESLUITVORMING = "ebesluitvorming"
    LBLOD = "lblod"
    REGLEMENT = "reglement"
    DSI = "dsi"


class Jurisdiction(StrEnum):
    """Governmental level of the referenced instrument.

    Descriptive only.  It records what the instrument is, independent of whether
    a supported source can currently search it, and stays ``unknown`` when the
    reference gives no reliable cue.
    """

    LOCAL = "local"
    REGIONAL = "regional"
    FEDERAL = "federal"
    EUROPEAN = "european"
    UNKNOWN = "unknown"


class ResolutionStatus(StrEnum):
    """Terminal outcomes exposed by :class:`ResolutionResponse`."""

    RESOLVED = "resolved"
    RESOLVED_WITH_CAVEAT = "resolved_with_caveat"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ResolutionReasonCode(StrEnum):
    """Machine-readable reason for a terminal resolution outcome."""

    CONFIRMED = "confirmed"
    CURRENT_EQUIVALENT = "current_equivalent"
    VERSION_MISMATCH = "version_mismatch"
    SOURCE_NO_MATCH = "source_no_match"
    SOURCE_INCOMPLETE = "source_incomplete"
    UNSUPPORTED_SOURCE = "unsupported_source"
    INSUFFICIENT_REFERENCE = "insufficient_reference"
    CANDIDATE_CONFLICT = "candidate_conflict"
    VALIDATION_FAILURE = "validation_failure"


# ---------------------------------------------------------------------------
# Document context
# ---------------------------------------------------------------------------


class DocumentContext(BaseModel):
    """Optional origin context used only as a classification fallback."""

    municipality: str | None = Field(default=None)
    jurisdiction: Jurisdiction | None = Field(default=None)
    governing_body: str | None = Field(default=None)
    description: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# Trace model
# ---------------------------------------------------------------------------


class AttemptTrace(BaseModel):
    """Compact auditable details for one requested source-tool call.

    Complete candidates live in one lookup-level registry.  Attempts reference
    them by document ID instead of duplicating full source records.
    """

    attempt: int
    source: SearchSource
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    candidate_ids: list[str] = Field(default_factory=list)
    complete: bool = True
    truncated: bool = False
    total_available: int | None = None
    backend_request_count: int = 0
    source_errors: list[SearchError] = Field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Workflow models
# ---------------------------------------------------------------------------


class ClassifiedReference(BaseModel):
    """Flat, normalized representation of one supplied legal reference."""

    title: str | None = Field(
        default=None,
        description="Concise identifying title without citation details",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Explicit short titles or abbreviations such as DABM or VCRO",
    )
    document_type: ReferenceType | None = Field(
        default=None,
        description="Supported document category, or null when it is unclear",
    )
    jurisdiction: Jurisdiction = Field(
        default=Jurisdiction.UNKNOWN,
        description="Governmental level of the instrument, or unknown when unclear",
    )
    document_date: date | None = Field(
        default=None,
        description="Identifying document, approval, or meeting date",
    )
    identifier: str | None = Field(
        default=None,
        description="Explicit decision, circular, or other document identifier",
    )
    article: str | None = Field(default=None, description="Referenced article")
    paragraph: str | None = Field(default=None, description="Referenced § paragraph")
    subsection: str | None = Field(
        default=None,
        description="Referenced textual subsection or lid",
    )
    point: str | None = Field(
        default=None,
        description="Referenced numbered or lettered point such as 10° or c)",
    )
    municipality: str | None = Field(
        default=None,
        description="Explicit municipality for a local decision",
    )
    governing_body: str | None = Field(
        default=None,
        description="Explicit local governing body",
    )
    source: SearchSource | None = Field(
        default=None,
        description="Authoritative supported source, or null when none applies",
    )
    fallback_sources: list[SearchSource] = Field(
        default_factory=list,
        description=(
            "Ordered alternative sources to try only if the primary is "
            "unresolved; at most one is used"
        ),
    )
    reason: str = Field(description="Concise explanation of classification and source")


class ValidationDecision(BaseModel):
    """Terminal validation decision for the accumulated candidate pool."""

    status: ResolutionStatus
    reason_code: ResolutionReasonCode
    selected_indices: list[int] = Field(default_factory=list)
    reason: str
    caveat: str | None = Field(default=None)
    proposed_guideline_lesson: str | None = Field(
        default=None,
        description=(
            "Optional one-line source-specific search lesson; null unless this "
            "lookup demonstrates a reusable behavior"
        ),
    )

    @field_validator("proposed_guideline_lesson", mode="before")
    @classmethod
    def normalize_lesson(cls, value):
        """Normalize an empty proposal to null and enforce a compact one-line value."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("proposed guideline lesson must be a string or null")
        value = value.strip()
        if not value:
            return None
        if any(character in value for character in "\r\n"):
            raise ValueError("proposed guideline lesson must be a single line")
        if len(value) > 500:
            raise ValueError("proposed guideline lesson must not exceed 500 characters")
        return value

    @model_validator(mode="after")
    def validate_selection(self):
        """Keep the selected candidate count consistent with terminal status."""
        if self.status == ResolutionStatus.RESOLVED and len(self.selected_indices) != 1:
            raise ValueError("resolved requires exactly one selected index")
        if self.status == ResolutionStatus.RESOLVED and self.reason_code != ResolutionReasonCode.CONFIRMED:
            raise ValueError("resolved requires reason_code confirmed")
        if self.status == ResolutionStatus.RESOLVED and self.caveat is not None:
            raise ValueError("resolved cannot carry a caveat")
        if self.status == ResolutionStatus.RESOLVED_WITH_CAVEAT:
            if len(self.selected_indices) != 1:
                raise ValueError("resolved_with_caveat requires exactly one selected index")
            if self.reason_code != ResolutionReasonCode.CURRENT_EQUIVALENT:
                raise ValueError("resolved_with_caveat requires reason_code current_equivalent")
            if not self.caveat or not self.caveat.strip():
                raise ValueError("resolved_with_caveat requires a non-empty caveat")
        if self.status == ResolutionStatus.AMBIGUOUS and len(self.selected_indices) < 2:
            raise ValueError("ambiguous requires at least two selected indices")
        if self.status in {ResolutionStatus.AMBIGUOUS, ResolutionStatus.UNRESOLVED} and self.reason_code in {
            ResolutionReasonCode.CONFIRMED,
            ResolutionReasonCode.CURRENT_EQUIVALENT,
        }:
            raise ValueError("non-success status requires a non-success reason code")
        if self.status == ResolutionStatus.UNRESOLVED:
            self.selected_indices = []
        return self


class SearchGraphState(TypedDict):
    """State passed between nodes in the legal-reference search graph."""

    reference: str
    document_context: DocumentContext | None
    classified_reference: ClassifiedReference | None
    guidelines: str
    guideline_error: str
    attempt_count: int
    trace: list[AttemptTrace]
    candidates: list[SearchResult]
    resolution_status: ResolutionStatus
    reason_code: ResolutionReasonCode
    results: list[SearchResult]
    reason: str
    caveat: str | None
    proposed_guideline_lesson: str | None
    source_queue: list[SearchSource]
    current_source: SearchSource | None
    pivot_count: int


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    """Configuration needed to construct and run an Agent."""

    model: str
    mcp_server_url: str = "http://127.0.0.1:8000/mcp"
    max_search_attempts: int = Field(default=3, ge=1, le=5)
    max_pivots: int = Field(default=1, ge=0, le=2)
    temperature: float = 0.0
    reasoning_effort: str = "none"
    llm_deployment: str | None = None
    prompt_overrides: dict[str, str] = Field(default_factory=dict)
    cache_path: Path | None = None


class ResolutionResponse(BaseModel):
    """Final structured result returned for one legal reference."""

    reference: str
    classification: ClassifiedReference | None = None
    status: ResolutionStatus
    reason_code: ResolutionReasonCode = ResolutionReasonCode.CONFIRMED
    results: list[SearchResult] = Field(default_factory=list)
    reason: str
    caveat: str | None = None
    attempt_count: int
    trace: list[AttemptTrace] = Field(default_factory=list)
    proposed_guideline_lesson: str | None = None
