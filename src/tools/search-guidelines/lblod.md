# LBLOD search guidelines

Use `LblodSearch` for local decisions and agenda items published through
Lokaal Beslist. A municipality is required for every search. Use Codex for
legislation that a local decision merely cites.

## Supported document types

This backend supports no `doc_type` values: always omit it or pass `None`.
In particular, `local_decision` describes the content conceptually but is not
implemented as an LBLOD filter. Narrow results with `municipality`,
`governing_body`, and `session_date` instead.

## Query and filter rules

- Use the exact decision number when one is present; otherwise keep only the
  distinctive title or subject words.
- `municipality` is mandatory and should use the municipality's display name.
- `session_date` uses `YYYY-MM-DD`.
- Apply date and governing-body filters only when the reference states them
  reliably. The adapter retries without those two filters after an empty result.
- Do not put approval boilerplate, articles, or a full surrounding paragraph in
  the query unless shorter searches fail.
- Generated JSON:API title-query variants are deduplicated before requests are
  sent, so deliberately choose distinct fallback terms rather than repetitions.

## Candidate validation

- Inspect all candidates and verify decision number, title, municipality,
  governing body, and session date where available.
- Distinguish the decision itself from an agenda item that only cites it.
- Prefer exact identity evidence over result order or wording similarity.
- Return a link only after the candidate is confirmed; preserve ambiguity when
  multiple meetings or versions remain plausible.

## Failure and completeness rules

- The composite adapter tries SPARQL first and JSON:API second. Their coverage
  and metadata can differ, so an empty or sparse result is not proof of absence.
- Inspect both `SearchOutcome.complete` and `errors`: failures from SPARQL remain
  visible even when the JSON:API fallback returns candidates, and vice versa.
- Shorten an over-specific query and retry before declaring no match.
- Never replace an unresolved local decision with a related Codex instrument.

## Practical lessons

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-08-01T12:19:38Z - Use local metadata as filters, not as substitutes for
  candidate validation.
- 2026-08-01T12:19:38Z - `local_decision` is not an implemented LBLOD filter.
