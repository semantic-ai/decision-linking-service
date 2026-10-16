# Stad Gent Reglementen search guidelines

Use `ReglementSearch` for municipal regulations published on the Stad Gent
Reglementen page. Use `EBesluitvormingSearch` for agenda items and decisions
that approve, amend, or discuss a regulation.

Do NOT use `ReglementSearch` for stedenbouwkundige verordeningen (SVO) or
bouwverordeningen / bouwreglementen (BVO), such as the *Algemeen Bouwreglement*.
These spatial planning regulations are indexed in DSI; use `DsiSearch` instead.

## Supported regulation types

The `regulation_type` filter accepts either the visible label or its current
Stad Gent form value:

| Type | Form value |
|---|---:|
| Aanvullende reglementen op het wegverkeer | 6534 |
| Ander reglement | 6529 |
| Belastingreglement | 6526 |
| Burgemeestersbesluit | 6540 |
| Politiereglement | 6531 |
| Retributiereglement | 6527 |
| Subsidiereglement | 6532 |

The displayed category counts are a changing site snapshot and are not part of
the source contract. The approval-body filter is intentionally not exposed by
this adapter.

## Search sequence

1. Start with a short distinctive title or subject query.
2. Use the exact `regulation_type` when the reference identifies one of the
   supported categories.
3. Inspect the complete title, type, approval body, approval date, announcement
   date, and canonical result URL before selecting a candidate.
4. When the first page is broad or truncated, retry with a narrower query,
  category, or a later `page` value.
5. Keep the regulation itself separate from eBesluitvorming records that cite
   or approve it.

## Query and filter rules

- `query` is sent as the page's `search` parameter.
- `regulation_type` is sent as one checkbox parameter named
  `regulation_type[{id}]` with the corresponding ID as its value.
- The adapter never sends `body_of_approval`.
- Approval and announcement dates are returned as metadata only. They are not
  search filters because later amendments or republication can change which
  date is indexed for a regulation.
- `page` is zero-based. One HTTP request is made per tool call.
- Do not infer one displayed date from the other during validation.

## Candidate validation

- Require a canonical HTTPS URL below `/nl/reglementen/`.
- Verify the full official title, displayed category, and any supplied date or
  body-of-approval clue.
- A regulation page is the source for the regulation text; an agenda or decision
  page is not a substitute merely because it contains the same title.
- When a supplied approval date is historical and no candidate has that date,
  an exact current Stad Gent Reglementen page with the same title, category,
  municipality, and a later approval or announcement date is the current
  equivalent. Select it as `resolved_with_caveat` with `current_equivalent`,
  and state that the historical version was not located. Do not require the
  page to use the word `consolidated`.
- Keep the result unresolved with `version_mismatch` when the title, category,
  municipality, or scope differs materially, when the candidate is an
  amendment rather than the regulation itself, or when the reference explicitly
  requires the historical version.
- Preserve ambiguity between distinct regulations with similar titles.
- Treat the numeric `data-nid` as the source document ID and keep the public
  slug URL unchanged.

## Failure and completeness rules

- A successful empty listing is complete when the page contains the expected
  Reglementen view and no result articles.
- A page with a `rel="next"` link, or a result total larger than the parsed page,
  is marked `truncated=true`. This is coverage evidence, not a source failure.
- Timeouts, network failures, non-200 responses, malformed pages, and malformed
  rows are retained as structured errors and make `complete=false`.
- A result row may coexist with a malformed row and an incomplete outcome.
- Do not interpret a failed request as proof that no regulation exists.

## Practical lessons

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-09-28T00:00:00Z - Use the source regulation category IDs and do not send an approval-body filter when searching by category.
- 2026-09-28T00:00:00Z - The Reglementen listing is paged and reports a total count in the view header.
- 2026-09-28T12:55:08Z - Verify the approval date and official title before selecting a similarly titled regulation.
- 2026-09-28T14:44:11Z - Verify document type and date before treating broad place-name matches as candidates.
- 2026-09-28T19:30:54Z - When exact-title searches fail, retry with shorter title fragments and verify the document version.
- 2026-09-29T11:25:00Z - Route stedenbouwkundige and bouwverordeningen to DSI rather than ReglementSearch.
