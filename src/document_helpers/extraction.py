"""Structured extraction and provenance validation for document references."""

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class Mention(BaseModel):
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class DocumentReference(BaseModel):
    doc_reference: str
    reference_class: str
    context: str
    mentions: list[Mention] = Field(min_length=1)


class _ExtractedReference(BaseModel):
    doc_reference: str
    reference_class: str
    context: str
    mentions: list[str] = Field(default_factory=list)


class DocumentReferences(BaseModel):
    references: list[DocumentReference] = Field(default_factory=list)


REFERENCE_EXTRACTION_PROMPT = """
Find references to specific legislative, regulatory, and administrative planning 
or permit documents in the input and organize them by the underlying document.

Return one group for each distinct underlying document, including repeated mentions with different articles or paragraphs. 
Do not merge different instruments merely because their names are similar.

For each group return doc_reference, reference_class, context, and mentions. 
doc_reference must be a concise canonical reference that can be searched once. 
reference_class is the document type, never a topic or legal effect.
context is a concise description of how the instrument is used in the input.
Include concrete nearby discriminators when present and relevant to the instrument, such as a street,
house number, project, object, municipality, governing body, or decision
number. Draw them from the nearest sentence, list item, or paragraph so the
context distinguishes similarly titled instruments without changing
doc_reference.
mentions must contain every exact occurrence belonging to that document.

Each mention must be a verbatim substring of the input. 
Preserve capitalization, accents, articles, whitespace, quotation marks, punctuation, and exact wording.
Keep article, paragraph, title, and section details in the mention.
Do not return surrounding sentences, rewrite text, invent a title, or omit repeated mentions. 
Do not return offsets; offsets are validated locally.

When a mention identifies a specific version with an approval, adoption, or
decision date, preserve that date in doc_reference. Do not reduce a dated
version to an undated title.

Extract identifiable laws, decrees, codes, regulations, municipal or police regulations, European regulations and directives, spatial plans,
building regulations, environmental permits, permit applications, permit decisions, OMV dossier numbers, and official decision numbers.
Omit generic legal wording without an identifiable instrument.
Never return a date on its own.
"""


_VERSION_DATE_PATTERN = re.compile(
    r"(?:approved|adopted|goedgekeurd|vastgesteld|beslist|besluit\s+van)"
    r"[^.;()\n]{0,100}?\b\d{1,2}\s+(?:januari|februari|maart|april|mei|juni|juli|"
    r"augustus|september|oktober|november|december|january|february|march|"
    r"april|may|june|july|august|september|october|november|december)\s+\d{4}\b",
    re.IGNORECASE,
)


def _mention_at(text: str, mention: str, start: int) -> Mention | None:
    if not mention or not mention.strip():
        return None
    position = text.find(mention, start)
    if position < 0:
        return None
    return Mention(text=mention, start=position, end=position + len(mention))


def validate_mentions(text: str, reference: _ExtractedReference) -> tuple[DocumentReference | None, str | None]:
    mentions: list[Mention] = []
    search_start = 0
    for mention_text in reference.mentions:
        mention = _mention_at(text, mention_text, search_start)
        if mention is None:
            continue
        mentions.append(mention)
        search_start = mention.end
    if not mentions:
        return None, f"No exact mention found for {reference.doc_reference!r}"
    date_clauses = []
    for mention in mentions:
        for match in _VERSION_DATE_PATTERN.finditer(mention.text):
            clause = re.sub(r"\s+", " ", match.group(0)).strip()
            if clause.casefold() not in reference.doc_reference.casefold():
                date_clauses.append(clause)
    doc_reference = reference.doc_reference
    for clause in dict.fromkeys(date_clauses):
        doc_reference = f"{doc_reference}, {clause}"
    return (
        DocumentReference(
            doc_reference=doc_reference,
            reference_class=reference.reference_class,
            context=reference.context,
            mentions=mentions,
        ),
        None,
    )


class ReferenceExtractor:
    def __init__(self, llm):
        self.llm = llm.with_structured_output(
            type("ExtractedDocumentReferences", (BaseModel,), {
                "__annotations__": {"references": list[_ExtractedReference]},
                "references": Field(default_factory=list),
            })
        )

    async def extract(self, normalized_text: str) -> tuple[DocumentReferences, list[str]]:
        result = await self.llm.ainvoke([
            SystemMessage(content=REFERENCE_EXTRACTION_PROMPT),
            HumanMessage(content=normalized_text),
        ])
        references: list[DocumentReference] = []
        errors: list[str] = []
        for raw_reference in result.references:
            reference, error = validate_mentions(normalized_text, raw_reference)
            if reference is not None:
                references.append(reference)
            if error:
                errors.append(error)

        seen_omv_ids: set[str] = set()
        for match in re.finditer(r"\bOMV_\d{10}[A-Za-z0-9_]*\b", normalized_text):
            omv_key = match.group(0).casefold()
            if omv_key in seen_omv_ids:
                continue
            seen_omv_ids.add(omv_key)
            if any(match.group(0).casefold() in mention.text.casefold() for reference in references for mention in reference.mentions):
                continue
            references.append(DocumentReference(
                doc_reference=f"Omgevingsvergunning {match.group(0)}",
                reference_class="omgevingsvergunning",
                context=f"Omgevingsvergunning dossier {match.group(0)}",
                mentions=[Mention(text=match.group(0), start=match.start(), end=match.end())],
            ))
        return DocumentReferences(references=references), errors
