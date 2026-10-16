# eBesluitvorming search guidelines

Use `EBesluitvormingSearch` for City of Ghent decisions and agenda items. Use an
authoritative legislation source when a Ghent page only cites legislation.

## Supported document types

This backend supports no `doc_type` values: always omit it or pass `None`.
Values such as `local_decision`, `regulation`, and the display type returned in
result metadata are not valid filters here. Use `title`, `type_id`, governing
body, and meeting date as described below when a narrower search is needed.

## Search sequence

1. When a decision number is known, put it in `title` and leave `query` empty.
2. Inspect every exact-number candidate because committee, executive, and final
   council records can share a human-readable number or subject.
3. If title search is empty, search the number in `query` as a full-text fallback.
4. Without a number, start with two to four distinctive subject or entity words
  in `query` and use `page_size=200`. When the reference supplies a street,
  project, address, or other location qualifier, combine it with the
  distinctive subject terms and inspect both agenda-item titles and
  descriptions.
5. Inspect the broad candidates before applying a governing-body or date filter.
6. Repeat with metadata observed on the intended candidate. Add a reliable title
   fragment when several versions share the subject.
7. If a filtered search fails, relax one constraint at a time: `type_id`, title,
   date, body.
8. Preserve ambiguity when several versions remain valid.

## Query and filter rules

- `title` is the strongest field for an exact decision number or trusted title
  fragment.
- `query` searches indexed full text and can return later decisions that cite the
  requested decision.
- Remove meeting boilerplate, approval verbs, dates, and governing bodies from
  the discovery query.
- Keep meaningful organization, person, street, project, address, and regulation
  names. A street or project qualifier can distinguish otherwise similar
  decisions and should not be discarded as incidental prose.
- Correct spelling and test deliberate variants; do not assume fuzzy matching.
- Use a configured governing-body name. Matching ignores capitalization and
  surrounding/repeated whitespace; an unknown non-empty `organ` is rejected
  before a broad unfiltered request can run.
- `doc_type` is unsupported and must remain unset. `type_id` must be a site publication-classification
  GUID; it is not the display type in result metadata.
- Apply dates and bodies after discovery. Dates quoted in prose can differ from
  the final meeting date, and combined historical bodies can have another label.

## Candidate validation

- Require the decision number in the returned title when one was supplied.
- Verify full title, subject/entity, meeting date, governing body, displayed
  result kind, meeting ID, and agenda-item ID.
- Distinguish committee preparation, college or vast-bureau approval, and final
  council approval.
- Treat a date and body as meeting clues, not as a unique decision identity.
- Do not select the first or newest row solely because its wording is similar.
- Resolve `dit reglement`, `voormelde beslissing`, and comparable anaphora only
  when the source title and immediate context identify one version.
- A source-page self-link is valid for an instrument being approved on that page
  only when both the mention and source title identify the same instrument.

## Failure and completeness rules

- Use `page_size=200` for discovery. The adapter paginates up to `max_pages`
  per governing body; `truncated=true` means that cap was reached, so narrow
  the query rather than assuming the result set is complete.
- The general endpoint also returns written questions and other non-agenda
  records. The adapter intentionally keeps only `MEETING_ITEM` rows because
  those have the supported public agenda-item URL. A complete but truncated
  outcome with no candidates can therefore warrant a narrower query.
- A friendly governing body can fan out to several current and historical IDs.
  Failure of one request can make the merged result incomplete.
- Non-200 responses are retained in `SearchOutcome.errors`; when one fan-out
  request fails, valid candidates can coexist with `complete=false`.
- A non-empty result set does not prove the intended record was returned.
- Leave version ambiguity or context-only references unresolved instead of
  guessing.

## Practical lessons

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-08-01T12:19:38Z - Put identifiers in `title` for precision and in `query` only as a fallback.
- 2026-08-01T12:19:38Z - Use short subject queries for discovery, then validate returned metadata.
- 2026-08-01T12:19:38Z - Build URLs from meeting and agenda IDs.
- 2026-09-22T13:59:48Z - Use only source-supported governing-body values and search the base act separately from amendments.
- 2026-09-28T13:40:42Z - Treat identifiers embedded in later meeting-item titles as citations until the official title and document kind confirm the base instrument.
- 2026-09-28T14:28:36Z - When identifier-only searches are truncated, combine the identifier with distinctive title terms and paginate or narrow the filters.
- 2026-09-28T15:23:07Z - Prefer the definitive adoption record over preliminary, committee, or downstream permit records.
