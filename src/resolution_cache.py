"""Append-only persistence for complete agent resolutions."""

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from src.agent_helpers.models import (
    AgentConfig,
    ClassifiedReference,
    DocumentContext,
    ResolutionResponse,
    ResolutionStatus,
)


logger = logging.getLogger(__name__)


def _normalize_reference(reference: str) -> str:
    return re.sub(r"\s+", " ", reference.strip()).casefold()


def compute_cache_key(doc_reference: str) -> str:
    return hashlib.sha256(
        _normalize_reference(doc_reference).encode("utf-8")
    ).hexdigest()


class ResolutionCacheRecord(BaseModel):
    cache_key: str
    doc_reference: str
    normalized_reference: str
    classification: ClassifiedReference
    response: ResolutionResponse
    model: str
    created_at: datetime


class ResolutionCacheWriter:
    def __init__(self, path: Path):
        self.path = path

    def append(self, record: ResolutionCacheRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="") as cache_file:
            cache_file.write(record.model_dump_json())
            cache_file.write("\n")


def is_cacheable(response: ResolutionResponse) -> bool:
    return (
        response.status == ResolutionStatus.RESOLVED
        and len(response.results) == 1
        and all(
            attempt.complete
            and not attempt.truncated
            and not attempt.source_errors
            for attempt in response.trace
        )
    )


class ResolutionCacheService:
    def __init__(self, agent, writer: ResolutionCacheWriter | None = None):
        self.agent = agent
        self.writer = writer

    async def resolve(
        self,
        reference: str,
        document_context: DocumentContext | None = None,
        *,
        doc_reference: str | None = None,
    ) -> ResolutionResponse:
        response = await self.agent.search(
            reference,
            document_context=document_context,
        )
        if self.writer is not None and is_cacheable(response):
            if response.classification is None:
                return response
            cache_doc_reference = (
                reference if doc_reference is None else doc_reference
            )
            record = ResolutionCacheRecord(
                cache_key=compute_cache_key(cache_doc_reference),
                doc_reference=cache_doc_reference,
                normalized_reference=_normalize_reference(response.reference),
                classification=response.classification,
                response=response,
                model=self.agent.config.model,
                created_at=datetime.now(timezone.utc),
            )
            try:
                self.writer.append(record)
            except Exception:
                logger.exception("Failed to persist resolution cache record")
        return response