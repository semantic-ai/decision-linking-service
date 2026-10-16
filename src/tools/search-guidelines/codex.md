# Codex search guidelines

Use `CodexSearch` for Flemish legislation and Belgian legislation indexed by
the Vlaamse Codex. Use the authoritative local or EU source for municipal
decisions and EU instruments.

For spatial planning instruments (gewestplan, RUP/GRUP, BPA, APA) and spatial
regulations including stedenbouwkundige verordeningen (gewSVO, gemSVO, proSVO
such as hemelwaterverordening, toegankelijkheid, publiciteit) and
bouwverordeningen (gewBVO, gemBVO such as Algemeen Bouwreglement, voetgangersverkeer),
use `DsiSearch` instead of `CodexSearch`.

## Supported document types

`doc_type` is optional and accepts only the following values for Codex:

| `doc_type` | Included Codex document kinds |
| --- | --- |
| `decree` | Decreet, Bijzonder Decreet, Gecodificeerd Decreet |
| `law` | Wet, Bijzondere Wet, Gecoördineerde Wet, Wetboek, Grondwet |
| `executive_order` | Besluit van de Vlaamse Regering, Ministerieel besluit, Koninklijk Besluit |
| `regulation` | Verordening, Gedelegeerde Verordening |
| `circular` | Omzendbrief |
| `agreement` | Samenwerkingsakkoord, Protocol, Verdrag |

Use the enum value, never a Dutch display label such as `wet` or `decreet`.
Do not use `local_decision`, `directive`, or `eu_decision` with Codex. When the
kind is uncertain, omit `doc_type`; an incorrect filter can hide the target and
the returned title still needs independent validation.

## Query preparation

- Split a paragraph that names several acts and search each act separately.
- Normalize Unicode to NFKC, collapse whitespace, and remove bullets or markup.
- Remove article and paragraph numbers, enactment dates, approval wording, and
  surrounding citation prose from the discovery query.
- Keep two to six distinctive words from the official title. Retain a year only
  when it is part of the official citeeropschrift.
- Try a citeeropschrift or acronym as its own query. Do not append it to a long
  title query.
- Preserve meaningful accents. Normalization must not transliterate words.
- Replace slash-heavy identifiers with space-separated tokens when necessary.

## Search sequence

1. Search the shortest distinctive title without `doc_type` to maximize recall.
2. Inspect the complete returned list; do not accept rank one automatically.
3. Repeat the same query with the expected `doc_type` to reduce inspection work.
4. Try an official short title or acronym as a separate query.
5. If no target appears, shorten the title one concept at a time.
6. Add a date or article only during validation, unless the year belongs to the
   official title.

```python
with CodexSearch() as search:
    broad = search.search("lokaal bestuur")
    typed = search.search("lokaal bestuur", doc_type="decree")
```

Treat a supported `doc_type` as a discovery filter, not proof of type. The
adapter retries without the filter when all typed requests return no rows, so a
typed call can still return documents of another kind. Validate the returned
title and kind before selecting a link.

## Candidate validation

- Match the official title or citeeropschrift, document kind, and enactment date.
- Distinguish the base act from amendments, implementing orders, and documents
  that merely cite it.
- Prefer an exact base-title candidate over titles containing `wijziging`, but
  retain the original result order in execution evidence.
- Use article numbers only after resolving the act; they are strong confirmation
  evidence and weak discovery terms.
- For compound references, store every independently confirmed document.
- Persist the Codex DID, official title, canonical URL, match method, and
  confidence.
- Add a link only after identity is confirmed. Leave anaphora such as
  `voormelde wet` unresolved unless its antecedent is unambiguous in the same
  source context.

## Failure and completeness rules

- Inspect `SearchOutcome.complete` and `errors`. An empty candidate list with
  `complete=false` is a source failure, not evidence that no match exists.
- Broad searches can reach the adapter's result cap, and pagination is not
  exposed. Narrow the title while preserving its distinctive concepts.
- A miss for an acronym does not prove that the act is absent; retry the official
  title.
- Do not force a similar result when the source does not cover the cited federal,
  EU, future, or unpublished instrument.
- Never substitute a local decision that merely quotes legislation for the
  authoritative legislation record.

## Practical lessons

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-08-01T12:19:38Z - Search title concepts, not citation grammar.
- 2026-08-01T12:19:38Z - Dates and articles belong primarily in validation.
- 2026-08-01T12:19:38Z - A documented unresolved result is preferable to an unverified link.
- 2026-09-22T14:11:18Z - Distinguish a codified base instrument from amendments and referring acts.
- 2026-09-24T12:12:12Z - When an exact title fails, retry with distinctive title fragments before treating the source as exhaustive.
- 2026-09-28T13:39:27Z - Prefer the official title and date of the named base instrument over related implementing documents.
