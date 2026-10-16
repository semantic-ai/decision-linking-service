"""Default node prompts and validated JSON overrides."""

from dataclasses import dataclass, fields
from string import Formatter


# ---------------------------------------------------------------------------
# Prompt schema and defaults
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptSet:
    """Prompts consumed by the three model-driven graph operations.

    Prompt field names are also the only keys accepted in the optional
    ``config.json`` prompt override object.
    """

    classify_reference: str
    search_candidates: str
    validate_candidates: str


DEFAULT_PROMPTS = PromptSet(
    classify_reference="""Normalize and classify exactly one legal reference supplied
in the user message.

Extract only facts stated by the reference or directly established by its
wording. Keep the identifying title concise and exclude citation prose,
articles, dates, and approval wording from that title. Preserve abbreviations
as aliases and normalize one identifying document or meeting date to ISO form.
Do not treat validity periods or dates inside the subject matter as the
document date. Leave missing facts null; never invent local context.

Classify document_type using the supported ReferenceType values.

Classify jurisdiction as the governmental level of the instrument, using its
type and name conventions:
- local: municipal or provincial acts such as a gemeenteraad decision,
  politiereglement, gemeentelijk reglement, or a named municipal codex.
- regional: Flemish or other regional and community acts, typically a decreet,
  besluit van de Vlaamse Regering, or a Vlaamse Codex.
- federal: Belgian federal acts such as a wet, Grondwet, (Nieuwe) gemeentewet,
  gecoördineerde wetten, or koninklijk besluit.
- european: EU acts such as a verordening, richtlijn, the AVG, or an EU standard.
- unknown: leave this value when no reliable cue fixes the level, for example a
  bare "omzendbrief" or "wet" with no other identifying context.
Jurisdiction is descriptive; set it even when no supported source applies.

Select source as:
- codex: Flemish and regional legislation indexed by Vlaamse Codex (ONLY covers Flemish legislation).
- web_search: official Belgian federal and European legislation (ONLY covers federal and European legislation).
- ebesluitvorming: City of Ghent decisions or agenda items (ONLY covers Ghent local decisions and agenda records).
- reglement: Stad Gent municipal regulations such as subsidiereglementen, retributiereglementen, belastingreglementen, politiereglementen, burgemeestersbesluiten, and traffic regulations. Do NOT use reglement for stedenbouwkundige verordeningen (SVO) or bouwverordeningen/bouwreglementen (BVO) - use dsi instead.
- dsi: spatial planning instruments and planning regulations across all Flemish municipalities and the Flemish region. Covers gewestplan, ruimtelijk uitvoeringsplan (RUP/GRUP), bijzonder plan van aanleg (BPA), algemeen plan van aanleg (APA), stedenbouwkundige verordeningen (SVO, gewSVO, gemSVO, proSVO such as hemelwaterverordening, toegankelijkheidsverordening, publiciteitsverordening), and bouwverordeningen (BVO, gewBVO, gemBVO such as Algemeen Bouwreglement, voetgangersverkeer). For ANY stedenbouwkundige verordening (SVO) or bouwverordening / bouwreglement (BVO), ALWAYS select dsi.

Always choose one of `codex`, `web_search`, `ebesluitvorming`, `reglement`, or `dsi` when
the reference or the supplied document context identifies a supported source.
Use document context as fallback only: facts stated by the reference take
precedence, and context must not override an explicit contrary municipality,
jurisdiction, or source. In particular, a Ghent general regulation reference (subsidie,
belasting, retributie, politie) uses `reglement`, while a Ghent decision or agenda-item
reference uses `ebesluitvorming`. Any spatial planning instrument or planning regulation
(RUP, BPA, APA, gewestplan, and specifically all SVO and BVO verordeningen such as
hemelwaterverordening, Algemeen Bouwreglement, toegankelijkheidsverordening) uses `dsi`,
regardless of municipality or government level. An identifier starting with 'OMV_'
(such as 'OMV_2026070977', 'OMV_2020011285'), or references to environmental permits /
permit applications ('omgevingsvergunning', 'aanvraag omgevingsvergunning', 'vergunningsbeslissing'),
represents an environmental permit dossier or local decision. When supplied with Ghent
document context or concerning Ghent, classify document_type as 'local_decision', jurisdiction
as 'local', identifier as the OMV number, and source as 'ebesluitvorming'.

The jurisdiction and source must agree. Federal or European references must
use `web_search`, regional references use `codex` (except regional spatial plans and regional
verordeningen like gewestplan, gewestelijk RUP, gewSVO, or gewBVO which use `dsi`), all spatial
planning instruments and planning regulations (RUP, BPA, APA, gewestplan, SVO, BVO) use `dsi`,
Ghent general regulations use `reglement`, and Ghent local decisions use `ebesluitvorming`;
never assign a federal or European reference to `codex`, and never leave source null merely
because a title is generic when the fallback context resolves its governmental
level. In particular, never assign a federal or European reference to `codex`.
Choose `null` only when neither the reference nor the fallback context identifies
a supported source safely, or when the reference explicitly identifies an
unsupported municipality or source.

Choose the source of the referenced instrument, not a local page that merely
quotes it. Under the single-reference scope, normalize only the primary
explicitly identifiable instrument; do not resolve anaphoric phrases such as
"its implementing order" as another document.

When the primary source is genuinely uncertain at one of these boundaries,
optionally put one conservative alternative in fallback_sources: reglement and
ebesluitvorming for a Ghent general regulation versus decision, dsi and
ebesluitvorming for a planning instrument versus local decision or permit, or
codex and web_search for regional versus federal or European wording. Leave
fallback_sources empty unless the boundary is genuinely ambiguous; never
duplicate the primary source or name an unsupported source.""",
    search_candidates="""Search one classified legal reference using {tool_name}.

You may call the selected tool repeatedly and inspect each result before
deciding whether another search is useful. You have at most
{max_search_attempts} total tool calls. Calls may use different short titles,
aliases, identifiers, or reliable source filters. Never repeat unchanged
arguments unless the preceding outcome for those arguments contains only
retryable source errors; in that case, you may retry them once. Never call
another source.

Follow the complete source guideline. Do not invent municipality, date,
governing-body, type, or identifier values. Treat article, paragraph,
subsection, and point primarily as validation evidence rather than discovery
terms. Stop calling tools when one or more candidates are suitably focused, or
when no materially different search remains. Do not invent candidate data in
your final reply; the separate validator will inspect only source results.
Each tool result reports whether the source lookup was complete, truncated, or
failed. A source error is not evidence that no matching document exists. Retry
with materially different arguments only when that may produce useful evidence.

Classified reference:
{classified_reference}

Source guideline:
{guidelines}""",
    validate_candidates="""Independently validate the final candidate pool for the
legal reference supplied in the user message.

Select only candidate indices shown below. Confirm identity from official
title, document kind, date, identifier, municipality, and governing body when
those facts are applicable. Do not accept rank one automatically, do not invent
a URL, and distinguish a base instrument from amendments or documents that
merely cite it.

Choose status and reason_code together:
- resolved / confirmed: exactly one candidate is an exact match;
- resolved_with_caveat / current_equivalent: exactly one authoritative
    `reglement` candidate matches the regulation identity/type/subject and
    municipality, the requested dated version is unavailable, and the candidate
    is the later current official page for that same regulation. For Stad Gent
    Reglementen, an exact current title/type/municipality match with a later
    approval or announcement date is sufficient evidence of a current
    equivalent; the page does not need to say ``consolidated`` explicitly.
    Explain the qualification in a non-empty caveat. Do not infer this from
    title similarity alone, and do not use it for an amendment or a candidate
    with a materially different scope. A date conflict with an exact current
    equivalent is a caveat, not automatically a version mismatch. Use
    version_mismatch when no current equivalent is established or an explicit
    historical version is required.
- ambiguous / candidate_conflict: at least two candidates remain genuinely
    plausible;
- unresolved: use source_no_match, source_incomplete, unsupported_source,
    insufficient_reference, or version_mismatch as appropriate.

The reason_code is authoritative for reporting; keep reason as a concise human
narrative. A qualified result is never an ordinary resolved result.

Source errors, incomplete fan-out, and truncated results are operational
evidence, not proof that no matching document exists. Reflect material source
limitations in the status and reason; never interpret a failed lookup as an
authoritative empty result.

Optionally propose one source-specific search lesson when the search attempts
demonstrate a clear, general behavior that may help future lookups. The lesson
must be one concise line. Never include this reference's facts, candidate facts,
identifiers, URLs, dates, or outcome. Leave proposed_guideline_lesson null unless
the evidence is specific and reusable. A proposal is appended to that source's
guideline after the result is returned, with duplicate lessons ignored.

Classified reference:
{classified_reference}

Search context:
{search_context}

Candidates, indexed from zero:
{candidates}""",
)


_PROMPT_NAMES = {field.name for field in fields(PromptSet)}
_ALLOWED_PLACEHOLDERS = {
    "classify_reference": set(),
    "search_candidates": {
        "tool_name",
        "max_search_attempts",
        "classified_reference",
        "guidelines",
    },
    "validate_candidates": {
        "classified_reference",
        "search_context",
        "candidates",
    },
}


# ---------------------------------------------------------------------------
# Validation and loading
# ---------------------------------------------------------------------------


def validate_prompt_overrides(overrides: dict[str, str]) -> dict[str, str]:
    """Validate and normalize prompt overrides loaded from JSON.

    Unknown names are rejected to surface configuration typos.  Values must be
    non-empty strings; leading and trailing whitespace is removed before the
    overrides are stored in :class:`AgentConfig`.
    """
    unknown = set(overrides) - _PROMPT_NAMES
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown prompt override(s): {names}")
    for name, value in overrides.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Prompt override {name!r} must be a non-empty string")
        try:
            placeholders = {
                field_name
                for _, field_name, _, _ in Formatter().parse(value)
                if field_name
            }
        except ValueError as error:
            raise ValueError(f"Prompt override {name!r} has invalid braces") from error
        unsupported = placeholders - _ALLOWED_PLACEHOLDERS[name]
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(
                f"Prompt override {name!r} uses unsupported placeholder(s): {names}"
            )
    return {name: value.strip() for name, value in overrides.items()}


def load_prompts(overrides: dict[str, str] | None = None) -> PromptSet:
    """Return the default prompt set with validated overrides applied.

    Parameters
    ----------
    overrides
        Optional mapping containing any subset of the three ``PromptSet`` keys.
    """
    values = {
        field.name: getattr(DEFAULT_PROMPTS, field.name) for field in fields(PromptSet)
    }
    values.update(validate_prompt_overrides(overrides or {}))
    return PromptSet(**values)
