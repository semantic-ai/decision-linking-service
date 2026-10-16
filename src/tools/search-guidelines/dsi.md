# DSI (Digitale Stedenbouwkundige Informatie) search guidelines

Use `DsiSearch` for all spatial planning instruments (*ruimtelijke verordenende plannen*) and urban/building regulations across all Flemish municipalities and the Flemish Region.

This includes:
- **Gewestplannen** (`GWP`)
- **Ruimtelijke uitvoeringsplannen** (`RUP`, `gewRUP`, `gemRUP`, `proRUP`)
- **Bijzondere en algemene plannen van aanleg** (`BPA`, `APA`)
- **Stedenbouwkundige verordeningen (SVO)**: both regional (`gewSVO` — e.g. hemelwaterverordening, toegankelijkheidsverordening, publiciteitsverordening) and municipal (`gemSVO`)
- **Bouwverordeningen en bouwreglementen (BVO)**: both regional (`gewBVO` — e.g. wegen voor voetgangersverkeer) and municipal (`gemBVO` — e.g. Algemeen Bouwreglement van de Stad Gent)

Use `ReglementSearch` only for general municipal regulations (belasting, subsidie, politie, retributie, verkeer). Do NOT use `ReglementSearch` or `CodexSearch` for SVO or BVO instruments — always use `DsiSearch`.

## Supported instruments and procedure codes

The `procedure_code` filter accepts canonical codes or common aliases:

| Procedure code | Instrument type | Authority level |
|---|---|---|
| `GWP` | Gewestplan | Regional / Flemish |
| `gewRUP` | Gewestelijk RUP | Regional / Flemish |
| `proRUP` | Provinciaal RUP | Provincial |
| `gemRUP` | Gemeentelijk RUP | Municipal |
| `RUP` | Any RUP (broad match) | Any |
| `BPA` | Bijzonder Plan van Aanleg | Municipal |
| `APA` | Algemeen Plan van Aanleg | Municipal |
| `gemSVO` / `gewSVO` / `proSVO` | Stedenbouwkundige verordening | Municipal / Regional / Provincial |
| `SVO` | Any stedenbouwkundige verordening (hemelwater, toegankelijkheid, etc.) | Any |
| `gemBVO` / `gewBVO` | Bouwverordening / Bouwreglement | Municipal / Regional |
| `BVO` | Any bouwverordening (Algemeen Bouwreglement, voetgangersverkeer, etc.) | Any |
| `gemROO` / `gewROO` / `proROO` | Rooilijnplan | Municipal / Regional / Provincial |

## Search sequence

1. Start with the distinctive plan name or subject query.
2. When the reference mentions a specific municipality, provide `municipality` (e.g. `"Gent"`) or `niscode` (`"44021"`).
3. If the plan category is clearly stated (e.g. gewestplan, gemeentelijk RUP), provide `procedure_code` (e.g. `"GWP"`, `"gemRUP"`).
4. Inspect candidate titles, `algplanid`, approval dates (`datumBesluitTotGoedkeuring`), and `plannende_overheid` before confirming a match.
5. If the first search returns too many results, narrow by adding `municipality` or `procedure_code`.

## Query and filter rules

- `query` matches against both the plan title (`naam`) and identifier (`algplanid`).
- Common plan prefixes such as "Gewestplan", "Ruimtelijk uitvoeringsplan", "RUP", "BPA" are stripped automatically by the adapter, but providing the concise distinctive name directly is recommended.
- Bounding quotes (`‘...’`, `"..."`, `'...'`) in the reference should be omitted from the search query.
- `municipality` resolves automatically against the official Flemish municipality keuzelijst to its 5-digit NIS code (e.g. "Gent" -> "44021").
- `status` defaults to open; use `"DEFINITIEF"` when only definitively approved plans are relevant.
- `page` is 1-based.

## Candidate validation

- Require a canonical URL pointing to `https://dsi.omgeving.vlaanderen.be/fiche-detail/{id}`.
- Verify the approval date (`approval_date` / `datumBesluitTotGoedkeuring`) against the date cited in the legal reference.
- Verify that the plan identifier (`algplanid`) matches expected format:
  - `GWP_...`: Gewestplan
  - `RUP_...`: Ruimtelijk uitvoeringsplan
  - `BPA_...`: Bijzonder Plan van Aanleg
  - `SVO_...`: Stedenbouwkundige verordening (gewSVO, gemSVO, proSVO)
  - `BVO_...`: Bouwverordening / Bouwreglement (gewBVO, gemBVO)
- The 5-digit number in the second segment of `algplanid` reflects the NIS code of the planning authority (e.g. `RUP_44021_...` belongs to Gent; `02000` denotes the Flemish Region).
- Distinguish between original base plans and subsequent partial revisions or deelprojecten.

## Failure and completeness rules

- A query that returns zero results is complete when the GraphQL query succeeded without error.
- A result set with `total_available > len(candidates)` is marked `truncated=true`.
- Timeouts, network failures, non-200 responses, and GraphQL syntax or backend errors are reported in `errors` and set `complete=false`.
- Never treat an adapter failure or network error as authoritative proof that no plan exists.

## Practical lessons

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-09-29T11:00:00Z - Spatial planning instruments (RUP, BPA, gewestplan) across Flanders are indexed on DSI (dsi.omgeving.vlaanderen.be); search by distinctive plan name with municipality filter.
- 2026-09-29T11:22:00Z - Stedenbouwkundige verordeningen (SVO, e.g. hemelwater, toegankelijkheid, publiciteit) and bouwverordeningen (BVO, e.g. Algemeen Bouwreglement, voetgangersverkeer) are indexed on DSI; route all SVO and BVO instruments to dsi.
- 2026-10-05T08:29:30Z - For DSI plan lookups, search title variants separately from procedure and status filters before concluding that no match is available.
- 2026-10-05T08:29:54Z - When exact-title searches return no results, retry with distinctive title fragments and the document type while retaining the municipality filter.
- 2026-10-05T08:40:36Z - When exact-title or filtered searches return no hits, broaden the query and verify whether returned records are later phases or related instruments rather than treating them as the requested document.
- 2026-10-05T08:42:06Z - When an exact-title search returns no results, retry with meaningful title components and jurisdiction filters before concluding that no document is available.
- 2026-10-05T08:57:51Z - For technical background documents, search linked attachments or associated documents separately from the governing legal instrument.
