"""Unified read-through cache for canonical document resolutions."""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from src.agent_helpers.models import (
    DocumentContext,
    ResolutionReasonCode,
    ResolutionResponse,
    ResolutionStatus,
)

logger = logging.getLogger(__name__)

CACHE_POLICY_VERSION = "2"
CAVEATED_TTL = timedelta(days=7)
SHORT_NEGATIVE_TTL = timedelta(hours=24)
LONG_NEGATIVE_TTL = timedelta(days=7)


class CacheStatus(StrEnum):
    HIT = "hit"
    MISS = "miss"
    INVALID = "invalid"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"


def normalize_reference(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def compute_cache_key(doc_reference: str) -> str:
    return hashlib.sha256(normalize_reference(doc_reference).encode("utf-8")).hexdigest()


def _has_clean_trace(response: ResolutionResponse) -> bool:
    return all(
        attempt.complete and not attempt.truncated and not attempt.source_errors
        for attempt in response.trace
    )


def _cache_entry(response: ResolutionResponse) -> tuple[str, timedelta | None] | None:
    if not _has_clean_trace(response):
        return None
    if response.status == ResolutionStatus.RESOLVED and (
        response.reason_code == ResolutionReasonCode.CONFIRMED
        and len(response.results) == 1
    ):
        return "resolved", None
    if response.status == ResolutionStatus.RESOLVED_WITH_CAVEAT and (
        response.reason_code == ResolutionReasonCode.CURRENT_EQUIVALENT
        and len(response.results) == 1
    ):
        return "caveated", CAVEATED_TTL
    if response.status == ResolutionStatus.AMBIGUOUS and (
        response.reason_code == ResolutionReasonCode.CANDIDATE_CONFLICT
    ):
        return "negative", SHORT_NEGATIVE_TTL
    if response.status == ResolutionStatus.UNRESOLVED:
        if response.reason_code == ResolutionReasonCode.SOURCE_NO_MATCH:
            return "negative", SHORT_NEGATIVE_TTL
        if response.reason_code in {
            ResolutionReasonCode.UNSUPPORTED_SOURCE,
            ResolutionReasonCode.INSUFFICIENT_REFERENCE,
        } and response.classification is not None and response.classification.source is None:
            return "negative", LONG_NEGATIVE_TTL
    return None


class ResolutionCacheRecord(BaseModel):
    cache_key: str
    doc_reference: str
    normalized_reference: str
    classification: object | None = None
    response: ResolutionResponse
    model: str = ""
    created_at: datetime
    cache_policy_version: str = CACHE_POLICY_VERSION
    entry_kind: str = "resolved"
    expires_at: datetime | None = None


class CacheLookup(BaseModel):
    status: CacheStatus
    response: ResolutionResponse | None = None
    lookup: str = "no_match"
    cache_entry_kind: str | None = None


class DocumentCache:
    def __init__(self, path: Path | None = None, *, policy_version: str = CACHE_POLICY_VERSION, model: str = ""):
        self.path = Path(path or "resolution-cache.jsonl")
        self.policy_version = policy_version
        self.model = model
        self._index: dict[str, dict] | None = None

    @staticmethod
    def _timestamp(record: dict) -> datetime:
        try:
            stamp = datetime.fromisoformat(str(record.get("created_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=timezone.utc)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    @staticmethod
    def _eligible(record: dict) -> bool:
        response = record.get("response") or {}
        if record.get("entry_kind"):
            return record.get("entry_kind") in {"resolved", "caveated", "negative"}
        return (
            response.get("status") == "resolved"
            and len(response.get("results") or []) == 1
            and all(
                attempt.get("complete", True)
                and not attempt.get("truncated", False)
                and not attempt.get("source_errors")
                for attempt in response.get("trace", [])
            )
        )

    @staticmethod
    def _expired(record: dict) -> bool:
        value = record.get("expires_at")
        if not value:
            return False
        try:
            expires_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    def _load(self) -> dict[str, dict]:
        if self._index is not None:
            return self._index
        self._index = {}
        if not self.path.exists():
            logger.debug("Resolution cache does not exist at %s", self.path)
            return self._index
        skipped_records = 0
        with self.path.open(encoding="utf-8") as cache_file:
            for line in cache_file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    skipped_records += 1
                    continue
                reference = record.get("doc_reference")
                if not reference or not self._eligible(record):
                    skipped_records += 1
                    continue
                key = normalize_reference(reference)
                if key not in self._index or self._timestamp(record) >= self._timestamp(self._index[key]):
                    self._index[key] = record
        logger.info(
            "Loaded %d eligible resolution cache records from %s (%d skipped)",
            len(self._index),
            self.path,
            skipped_records,
        )
        return self._index

    @staticmethod
    def _tokens(value: str) -> set[str]:
        stopwords = {"and", "bij", "de", "der", "een", "en", "het", "of", "on", "op", "te", "the", "tot", "van", "voor"}
        return {token for token in re.findall(r"\w+", normalize_reference(value)) if len(token) > 2 and token not in stopwords}

    def lookup(self, doc_reference: str) -> CacheLookup:
        index = self._load()
        exact = index.get(normalize_reference(doc_reference))
        if exact is not None:
            if self._expired(exact):
                return CacheLookup(
                    status=CacheStatus.STALE,
                    lookup="exact_match",
                    cache_entry_kind=exact.get("entry_kind", "resolved"),
                )
            try:
                logger.debug("Resolution cache hit using exact reference")
                return CacheLookup(
                    status=CacheStatus.HIT,
                    response=ResolutionResponse.model_validate(exact["response"]),
                    lookup="exact_match",
                    cache_entry_kind=exact.get("entry_kind", "resolved"),
                )
            except Exception:
                logger.warning("Resolution cache record failed validation for exact reference")
                return CacheLookup(status=CacheStatus.INVALID, lookup="exact_match")
        reference_tokens = self._tokens(doc_reference)
        if len(reference_tokens) < 2:
            logger.debug("Resolution cache miss: reference has insufficient match tokens")
            return CacheLookup(status=CacheStatus.MISS)
        matches: dict[tuple, dict] = {}
        for record in index.values():
            if self._expired(record):
                continue
            response = record.get("response") or {}
            result = (response.get("results") or [{}])[0]
            titles = ((response.get("classification") or {}).get("title"), result.get("title"))
            if any(self._tokens(title or "") >= reference_tokens for title in titles):
                identity = (result.get("source"), result.get("doc_id") or result.get("url"))
                matches[identity] = record
        if len(matches) == 1:
            record = next(iter(matches.values()))
            try:
                logger.debug("Resolution cache hit using title overlap")
                return CacheLookup(
                    status=CacheStatus.HIT,
                    response=ResolutionResponse.model_validate(record["response"]),
                    lookup="title_match",
                    cache_entry_kind=record.get("entry_kind", "resolved"),
                )
            except Exception:
                logger.warning("Resolution cache record failed validation for title match")
                return CacheLookup(status=CacheStatus.INVALID, lookup="title_match")
        if len(matches) > 1:
            logger.info("Resolution cache lookup is ambiguous across %d candidates", len(matches))
            return CacheLookup(status=CacheStatus.AMBIGUOUS, lookup="ambiguous_match")
        logger.debug("Resolution cache miss")
        return CacheLookup(status=CacheStatus.MISS)

    def append(self, doc_reference: str, response: ResolutionResponse) -> None:
        entry = _cache_entry(response)
        if entry is None:
            return
        entry_kind, ttl = entry
        created_at = datetime.now(timezone.utc)
        record = ResolutionCacheRecord(
            cache_key=compute_cache_key(doc_reference),
            doc_reference=doc_reference,
            normalized_reference=normalize_reference(doc_reference),
            classification=response.classification,
            response=response,
            model=self.model,
            created_at=created_at,
            cache_policy_version=self.policy_version,
            entry_kind=entry_kind,
            expires_at=created_at + ttl if ttl else None,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="") as cache_file:
            cache_file.write(record.model_dump_json() + "\n")
        if self._index is None:
            self._index = {}
        key = normalize_reference(doc_reference)
        current = self._index.get(key)
        record_data = record.model_dump(mode="json")
        if current is None or self._timestamp(record_data) >= self._timestamp(current):
            self._index[key] = record_data
        logger.debug("Appended eligible resolution to cache")

    async def resolve(self, agent, reference: str, *, document_context: DocumentContext | None = None, doc_reference: str | None = None) -> tuple[ResolutionResponse, CacheLookup]:
        canonical = doc_reference or reference
        lookup = self.lookup(canonical)
        if lookup.response is not None:
            return lookup.response, lookup
        logger.debug("Performing live resolution after cache status=%s", lookup.status.value)
        response = await agent.search(reference, document_context=document_context)
        try:
            self.append(canonical, response)
        except Exception:
            logger.exception("Failed to persist resolution cache record")
        return response, lookup
