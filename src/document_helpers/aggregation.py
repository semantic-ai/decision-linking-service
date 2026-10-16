"""Document-level result contracts and aggregation."""

import hashlib
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field

from src.agent_helpers.models import ResolutionResponse
from src.document_helpers.cache import CacheStatus
from src.document_helpers.extraction import DocumentReference


class DocumentStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class DocumentMetadata(BaseModel):
    content_hash: str
    processed_at: datetime


class ReferenceOutcome(BaseModel):
    extracted: DocumentReference
    cache_status: CacheStatus | None = None
    cache_lookup: str | None = None
    cache_entry_kind: str | None = None
    resolution: ResolutionResponse | None = None
    error: str | None = None


class DocumentResult(BaseModel):
    document: DocumentMetadata
    references: list[ReferenceOutcome] = Field(default_factory=list)
    status: DocumentStatus
    errors: list[str] = Field(default_factory=list)


def document_metadata(text: str) -> DocumentMetadata:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentMetadata(
        content_hash=f"sha256:{digest}",
        processed_at=datetime.now(timezone.utc),
    )


def build_document_result(text: str, outcomes: list[ReferenceOutcome], errors: list[str] | None = None, *, failed: bool = False) -> DocumentResult:
    all_errors = list(errors or [])
    all_errors.extend(outcome.error for outcome in outcomes if outcome.error)
    if failed:
        status = DocumentStatus.FAILED
    elif all_errors:
        status = DocumentStatus.PARTIAL
    else:
        status = DocumentStatus.COMPLETE
    return DocumentResult(
        document=document_metadata(text),
        references=outcomes,
        status=status,
        errors=all_errors,
    )
