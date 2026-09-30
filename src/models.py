"""Shared source-adapter types for official legal-reference searches."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


# ---------------------------------------------------------------------------
# Search result values
# ---------------------------------------------------------------------------


class ReferenceType(StrEnum):
    """Legal reference categories."""

    DECREE = "decree"
    LAW = "law"
    EXECUTIVE_ORDER = "executive_order"
    REGULATION = "regulation"
    CIRCULAR = "circular"
    AGREEMENT = "agreement"
    LOCAL_DECISION = "local_decision"


@dataclass
class SearchResult:
    """One unchanged official candidate returned by a search adapter."""

    title: str
    url: str
    source: str
    doc_id: str
    retrieved_at: datetime
    metadata: dict = field(default_factory=dict)


class SearchErrorKind(StrEnum):
    """Portable categories for failures returned by a source adapter."""

    TIMEOUT = "timeout"
    HTTP = "http"
    NETWORK = "network"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class SearchError:
    """One non-fatal source failure retained with a search outcome."""

    backend: str
    kind: SearchErrorKind
    message: str
    retryable: bool
    status_code: int | None = None


@dataclass
class SearchOutcome:
    """Candidates plus completeness and failure evidence for one search call.

    ``complete`` describes whether every backend request needed by the adapter's
    strategy completed successfully. ``truncated`` separately records that a
    source result limit may have omitted additional candidates.
    """

    candidates: list[SearchResult] = field(default_factory=list)
    complete: bool = True
    truncated: bool = False
    total_available: int | None = None
    backend_request_count: int = 0
    errors: list[SearchError] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.errors:
            self.complete = False
        if self.backend_request_count < 0:
            raise ValueError("backend_request_count must not be negative")
        if self.total_available is not None and self.total_available < 0:
            raise ValueError("total_available must not be negative")


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------


class LegislationSearch(ABC):
    """Context-managed interface implemented by every source adapter."""

    @abstractmethod
    def search(
        self,
        query: str,
        doc_type: str | None = None,
        **kwargs,
    ) -> SearchOutcome:
        """Return candidates and structured source-completeness evidence."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release resources owned by the adapter."""
        ...

    def __enter__(self):
        """Return the open adapter for use as a context manager."""
        return self

    def __exit__(self, *exc):
        """Close adapter resources when leaving a context manager."""
        self.close()
