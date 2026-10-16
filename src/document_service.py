"""Document-level orchestration for extraction, resolution, caching, and aggregation."""

import logging
from time import perf_counter

from src.agent import Agent
from src.agent_helpers.models import AgentConfig, DocumentContext
from src.config import load_agent_config
from src.document_helpers.aggregation import (
    DocumentResult,
    ReferenceOutcome,
    build_document_result,
)
from src.document_helpers.cache import DocumentCache
from src.document_helpers.extraction import ReferenceExtractor

logger = logging.getLogger(__name__)


class DocumentService:
    """Process one normalized document through the reference-resolution pipeline."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        agent: Agent | None = None,
        cache: DocumentCache | None = None,
        extractor: ReferenceExtractor | None = None,
    ):
        self.config = config or (agent.config if agent is not None else load_agent_config())
        self.agent = agent or Agent(self.config)
        self.cache = cache or DocumentCache(self.config.cache_path, model=self.config.model)
        self.extractor = extractor or ReferenceExtractor(self.agent.llm)

    async def process(
        self,
        normalized_text: str,
        *,
        document_context: DocumentContext | None = None,
    ) -> DocumentResult:
        """Validate, extract, resolve, and aggregate one document.

        The stages are deliberately kept in this order: extraction establishes
        the reference evidence, cache lookup avoids unnecessary live searches,
        and aggregation preserves both successful results and per-reference
        failures in one document-level response.
        """
        document_started_at = perf_counter()
        if not isinstance(normalized_text, str) or not normalized_text.strip():
            logger.warning("Document rejected because normalized text is empty or invalid")
            return build_document_result(
                normalized_text if isinstance(normalized_text, str) else "",
                [],
                ["normalized_text must be a non-empty string"],
                failed=True,
            )

        logger.info("Starting document processing (%d characters)", len(normalized_text))

        # Extract first so every later result can retain its source mention.
        extraction_started_at = perf_counter()
        try:
            references, extraction_errors = await self.extractor.extract(normalized_text)
        except Exception as error:
            logger.exception("Document reference extraction failed")
            return build_document_result(
                normalized_text,
                [],
                [f"reference extraction failed: {error}"],
                failed=True,
            )
        logger.info(
            "Extracted %d document references (%d extraction errors) duration_ms=%.0f",
            len(references.references),
            len(extraction_errors),
            (perf_counter() - extraction_started_at) * 1000,
        )

        outcomes: list[ReferenceOutcome] = []
        resolved_by_key = {}
        for reference in references.references:
            reference_started_at = perf_counter()
            context_fingerprint = " ".join((reference.context or "").split()).casefold()
            key = (reference.doc_reference.strip().casefold(), context_fingerprint)
            if key in resolved_by_key:
                response, lookup = resolved_by_key[key]
                logger.info(
                    "Reference document=%r cache_hit=%s dedupe=true status=%s resolved_url=%s duration_ms=%.0f",
                    reference.doc_reference,
                    lookup.status.value == "hit",
                    response.status.value,
                    response.results[0].url if response.status.value in {"resolved", "resolved_with_caveat"} and response.results else None,
                    (perf_counter() - reference_started_at) * 1000,
                )
                outcomes.append(ReferenceOutcome(
                    extracted=reference,
                    cache_status=lookup.status,
                    cache_lookup=lookup.lookup,
                    cache_entry_kind=lookup.cache_entry_kind,
                    resolution=response,
                ))
                continue
            description = "\n".join(
                part
                for part in (
                    document_context.description if document_context else None,
                    reference.context,
                )
                if part
            ) or None
            context = DocumentContext.model_validate(
                {
                    **(document_context.model_dump() if document_context else {}),
                    "description": description,
                }
            )
            try:
                # Cache resolution is isolated per reference so siblings continue.
                response, lookup = await self.cache.resolve(
                    self.agent,
                    reference.doc_reference,
                    document_context=context,
                    doc_reference=reference.doc_reference,
                )
                resolved_by_key[key] = (response, lookup)
                logger.info(
                    "Reference document=%r cache_hit=%s status=%s resolved_url=%s duration_ms=%.0f",
                    reference.doc_reference,
                    lookup.status.value == "hit",
                    response.status.value,
                    response.results[0].url if response.status.value in {"resolved", "resolved_with_caveat"} and response.results else None,
                    (perf_counter() - reference_started_at) * 1000,
                )
                outcomes.append(ReferenceOutcome(
                    extracted=reference,
                    cache_status=lookup.status,
                    cache_lookup=lookup.lookup,
                    cache_entry_kind=lookup.cache_entry_kind,
                    resolution=response,
                ))
            except Exception as error:
                logger.exception(
                    "Reference resolution failed for %r duration_ms=%.0f",
                    reference.doc_reference,
                    (perf_counter() - reference_started_at) * 1000,
                )
                outcomes.append(ReferenceOutcome(
                    extracted=reference,
                    error=f"resolution failed: {error}",
                ))

        result = build_document_result(
            normalized_text,
            outcomes,
            extraction_errors,
        )
        logger.info(
            "Document processing finished with status=%s and %d reference outcomes duration_ms=%.0f",
            result.status.value,
            len(result.references),
            (perf_counter() - document_started_at) * 1000,
        )
        return result
