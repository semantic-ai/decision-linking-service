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

- 2026-09-28T00:00:00Z - Stad Gent exposes regulation categories as regulation_type checkbox IDs; do not send the approval-body filter when searching by category.
- 2026-09-28T00:00:00Z - The Reglementen listing is paged at twelve result articles per page and reports a total count in the view header.
- 2026-09-28T12:55:08Z - When an exact-title search returns similarly titled regulations, verify the approval date and official title before selecting a candidate.
- 2026-09-28T14:44:11Z - Verify document type and date before treating broad place-name matches as candidates.
- 2026-09-28T16:34:45Z - Wanneer een exacte-titelzoekopdracht alleen een latere versie oplevert, controleer dan ook historische goedkeuringsgegevens of gearchiveerde versies.
- 2026-09-28T16:35:11Z - Controleer bij historische verwijzingen altijd expliciet de goedkeuringsdatum en onderscheid een latere versie of wijziging van het oorspronkelijke instrument.
- 2026-09-28T16:36:37Z - Controleer bij exacte titelovereenkomsten altijd afzonderlijk de goedkeuringsdatum om een latere hergoedkeuring niet als het oorspronkelijke instrument te identificeren.
- 2026-09-28T16:37:22Z - Controleer bij een exacte titelmatch altijd de goedkeuringsdatum en behandel een latere versie met dezelfde titel niet automatisch als het gevraagde basisinstrument.
- 2026-09-28T16:37:45Z - Controleer bij titelovereenkomsten altijd afzonderlijk de goedkeuringsdatum om historische instrumenten van latere herzieningen of vervangende documenten te onderscheiden.
- 2026-09-28T16:39:33Z - When a reference includes a historical approval date, search and validate historical versions separately from later regulations with similar titles.
- 2026-09-28T16:41:39Z - Controleer bij titelovereenkomsten altijd expliciet de goedkeuringsdatum en behandel een afwijkende datum niet als een bevestiging.
- 2026-09-28T16:47:09Z - Neem bij historische lokale reglementen de goedkeuringsdatum of het jaartal expliciet mee in de zoekstrategie om latere versies of vervangende instrumenten niet als match te selecteren.
- 2026-09-28T16:49:55Z - Bij reglementen met historische versies moet de goedkeuringsdatum afzonderlijk worden gevalideerd naast de titel.
- 2026-09-28T16:53:27Z - Controleer bij gelijkende reglementen altijd de officiële goedkeuringsdatum en het goedkeuringsorgaan in het documentrecord; behandel lege datumgerichte zoekresultaten niet als gezaghebbende afwezigheid.
- 2026-09-28T16:58:29Z - When exact-title searches fail, retry with normalized wording and distinctive shorter title phrases while separately verifying the document date.
- 2026-09-28T17:01:10Z - Wanneer een exacte titelzoekopdracht geen resultaat oplevert, probeer onderscheidende titelgedeelten en spellingvarianten afzonderlijk te zoeken.
- 2026-09-28T17:05:58Z - Herhaal bij lokale reglementen zoekopdrachten met titelvarianten en zonder documenttype, omdat kleine woordverschillen resultaten kunnen uitsluiten.
- 2026-09-28T19:04:50Z - When exact-title searches return nothing, retry with shorter title fragments and verify any hit against the approval date and document version.
- 2026-09-28T19:06:55Z - When a title match has a different approval date, perform a separate source search using the exact date and historical-version terms before resolving.
- 2026-09-28T19:08:39Z - Probeer bij lokale reglementen zowel volledige titelfragmenten als onderscheidende fonds- of entiteitsnamen afzonderlijk te zoeken.
- 2026-09-28T19:30:54Z - When an instrument is absent from exact-title searches, check the source’s dedicated spatial-planning or zoning collection rather than relying only on general regulation filters.
- 2026-09-29T11:25:00Z - Stedenbouwkundige verordeningen (SVO, gewSVO, gemSVO) and bouwverordeningen / bouwreglementen (BVO, gewBVO, gemBVO, e.g. Algemeen Bouwreglement) are spatial planning regulations indexed on DSI; route them to DsiSearch instead of ReglementSearch.
