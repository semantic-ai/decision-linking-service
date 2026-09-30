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
   in `query` and use `page_size=200`.
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
- Keep meaningful organization, person, street, project, and regulation names.
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

- Use `page_size=200` for discovery. The adapter requests page zero only, so a
  very broad result set may still be incomplete.
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

- 2026-08-01T12:19:38Z - Put identifiers in `title` for precision and in `query`
  only as a fallback.
- 2026-08-01T12:19:38Z - Use short subject queries for discovery, then validate
  with returned metadata.
- 2026-08-01T12:19:38Z - Derive filters from the candidate record rather than
  trusting citation prose.
- 2026-08-01T12:19:38Z - Build URLs from meeting and agenda IDs.
- 2026-08-01T12:19:38Z - Correct unresolved outcomes are part of reliable
  retrieval.
- 2026-09-22T13:59:48Z - Gebruik voor Gent alleen de door de bron ondersteunde bestuursorgaanwaarden en zoek afzonderlijk naar de basisakte naast wijzigings- en goedkeuringsdossiers.
- 2026-09-23T12:36:12Z - Wanneer een bron bij exacte datumfilters een parseerfout geeft, voer ook een afzonderlijke titelzoekactie uit en behandel de resultaten als mogelijk onvolledig.
- 2026-09-23T12:36:54Z - Controleer bij datumgevoelige zoekopdrachten ook de volledige vergaderhistoriek wanneer de bronpagina niet parseerbaar is.
- 2026-09-23T12:37:50Z - For codified local regulations, distinguish agenda or decision records that amend constituent provisions from the separately published consolidated text.
- 2026-09-23T12:38:09Z - Bij historische besluiten moet de zoekstrategie naast de exacte titel en datum ook expliciet zoeken naar oudere basisbesluiten buiten de standaardresultaatpagina.
- 2026-09-23T14:33:20Z - Behandel titelovereenkomsten op deze bron pas als het oorspronkelijke instrument is bevestigd nadat datum, bestuursorgaan en documentsoort afzonderlijk overeenstemmen.
- 2026-09-24T06:27:15Z - When an exact historical-date search returns no result, search title variants and amendment records because a source may index later references without exposing the original base instrument.
- 2026-09-24T06:29:39Z - When an exact-title/date search returns no records, broaden the title search and distinguish later amendments from the requested base instrument.
- 2026-09-24T11:10:13Z - When municipal full-text searches time out, retry with narrower title-term combinations before concluding that no match exists.
- 2026-09-28T13:40:42Z - Verify that a searched identifier is the document's own identifier rather than merely a reference embedded in a meeting item's title.
- 2026-09-28T13:41:23Z - Treat identifier matches embedded in later meeting-item titles as citations until the item's official title and document kind confirm that it is the base instrument.
- 2026-09-28T13:53:46Z - Wanneer een bronzoekopdracht met datumfilter geen resultaten geeft maar een bredere titelzoekopdracht wel, behandel de datumfilter als mogelijk onbetrouwbaar en controleer alternatieve zoekcombinaties.
- 2026-09-28T13:58:08Z - When an identifier-filtered search is empty, retry the identifier as a full-text query and verify the returned official title instead of relying on ranking.
- 2026-09-28T14:14:32Z - Treat broad free-text identifier hits as provisional and confirm the identifier in the official title or document metadata before selecting a candidate.
- 2026-09-28T14:16:12Z - Require a property address or unique application number when a date/title search returns multiple local decisions.
- 2026-09-28T14:24:36Z - When exact-title filtering returns no hits, retry with free-text abbreviations and inspect linked documents rather than treating the empty result as authoritative.
- 2026-09-28T14:26:01Z - When a source distinguishes base instruments from addenda, validate the action date and document subtype separately rather than treating a near-title result as the requested decision.
- 2026-09-28T14:28:04Z - When exact-identifier filtering returns no hits, retry with the identifier as a full-text query but verify the official identifier and document metadata before selecting a result.
- 2026-09-28T14:28:36Z - When identifier-only searches are truncated, combine the identifier with distinctive title terms and paginate or apply narrower date or document-type filters.
- 2026-09-28T14:29:24Z - When an identifier-only search returns a truncated fan-out, paginate or add jurisdictional and governing-body filters before validating candidates.
- 2026-09-28T14:31:54Z - When exact-title and date-filtered searches return no records, broaden terminology and consult historical planning archives because a meeting index may omit older instruments.
- 2026-09-28T14:36:10Z - When an exact-identifier search returns broad token matches, validate the canonical identifier and document metadata instead of treating title-token matches as exact matches.
- 2026-09-28T14:37:22Z - When a source rejects an abbreviated governing-body name, retry with the source’s canonical full organ label.
- 2026-09-28T14:38:26Z - Combineer bij brede of afgekapt teruggegeven identifierresultaten onderscheidende titeltermen met datum en plaats, en verifieer daarna de volledige bronfiche.
- 2026-09-28T14:38:43Z - Behandel afgekaptet identifierzoekresultaten niet als volledige negatieve zoekresultaten; verfijn met de officiële titel en het documenttype.
- 2026-09-28T14:44:31Z - Behandel brede identificatorresultaten als relevantiesuggesties en verifieer elk resultaat afzonderlijk op officiële datum, titel, documentsoort en bestuursorgaan.
- 2026-09-28T14:45:09Z - Wanneer een exacte identifierszoekopdracht uitsluitend recente, inhoudelijk afwijkende resultaten oplevert, combineer die zoekopdracht met expliciete historische datum- en documenttypefilters.
- 2026-09-28T14:54:30Z - Splits bij historische lokale besluiten zoekopdrachten op in afzonderlijke identifier-, datum- en titeltermen en controleer daarna het brondocument.
- 2026-09-28T14:55:12Z - Wanneer een exacte zoekopdracht in een besluitvormingsbron alleen moderne, niet-overeenkomende items oplevert, controleer dan ook historische of archiefspecifieke indexen in plaats van de uitkomst als volledig te beschouwen.
- 2026-09-28T15:05:57Z - Behandel treffers op een identificatienummer als voorlopig totdat titel, documenttype, datum en bestuursorgaan onafhankelijk overeenstemmen.
- 2026-09-28T15:23:07Z - Prefer the definitive adoption record for a planning instrument over preliminary-adoption, committee, or downstream permit records.
- 2026-09-28T15:25:49Z - Wanneer een identificatiezoekactie een afgekapt resultatenpakket oplevert, combineer dan exacte titel-, datum- en gemeentefilters en controleer de detailrecords voordat de resultaten als volledig worden beschouwd.
- 2026-09-28T15:26:08Z - Combineer bij oudere lokale besluiten een exacte identifierzoekopdracht met titel- en inhoudszoekopdrachten en controleer steeds of brede resultaten volledig zijn.
- 2026-09-28T15:26:26Z - Combineer bij identifierzoekacties die brede of afgeknotte resultaten opleveren de identifier met titeltermen en datumfilters, en behandel malformed bronrijen als een reden voor herhaling.
- 2026-09-28T15:26:41Z - Exacte identifierzoekopdrachten op deze bron kunnen brede, inhoudelijk niet-passende resultaten opleveren; controleer altijd titel, datum, documenttype en bestuursorgaan afzonderlijk.
- 2026-09-28T15:29:01Z - Controleer bij identificatorzoekopdrachten altijd ook de officiële titel, datum en het documenttype, omdat een bron een niet-gerelateerde treffer kan retourneren.
- 2026-09-28T15:29:31Z - Voor historische lokale beslissingen: combineer identifier-varianten met een expliciet datumfilter voordat brede meeting-itemresultaten worden beoordeeld.
- 2026-09-28T15:29:49Z - Combineer bij oudere lokale beslissingen een exacte identifierzoekopdracht met datum- en gemeentefilters, omdat titelzoekopdrachten vaak latere semantisch gelijkende dossiers teruggeven.
- 2026-09-28T15:30:08Z - Behandel een afgekapt identifierzoekresultaat of een nulresultaat na combinatie van titel- en datumfilters niet als een volledige bronraadpleging.
- 2026-09-28T15:30:22Z - Combineer identifier- en titelzoekopdrachten met een expliciete historische datum- of periodefilter wanneer de bron bij exacte zoekopdrachten vooral recente resultaten teruggeeft.
- 2026-09-28T15:42:48Z - Wanneer een datumgefilterde zoekopdracht niets oplevert, controleer datumvarianten en pagineer of verfijn de resultaten voordat je concludeert dat er geen overeenkomstig document bestaat.
- 2026-09-28T15:47:31Z - Exact title/date filters may omit older records; pair them with broader title-only or keyword searches.
- 2026-09-28T15:52:22Z - Gebruik voor historische lokale beslissingen naast identificatienummers ook genormaliseerde titeltermen, plaatsnaam en datumfilters.
- 2026-09-28T15:52:37Z - Gebruik voor historische lokale beslissingen naast titel- en identifierzoekopdrachten ook archiefspecifieke zoekingangen, omdat algemene besluitregisters oudere stukken mogelijk niet indexeren.
- 2026-09-28T15:53:08Z - Wanneer een identifier-veldzoekopdracht geen treffers geeft, combineer dan een vrije-tekstzoekopdracht met titel- en datumfilters en controleer ook afgekapt vervolgresultaten.
- 2026-09-28T15:53:25Z - Combineer bij historische lokale besluiten exacte identificatoren met documenttype- en gemeentefilters en pagineer afgekorte resultaten.
- 2026-09-28T15:53:42Z - Wanneer een exacte identifierzoekopdracht brede, afgekapt resultaten oplevert, combineer de identifier met datum- en titeltermen en gebruik paginering voordat de zoekactie als leeg wordt beschouwd.
- 2026-09-28T15:53:59Z - Wanneer een identifierzoekopdracht brede, ongerelateerde vergaderitems oplevert, combineer de identifier met documenttype- en datumfilters en controleer of de resultaten volledig zijn.
- 2026-09-28T15:54:14Z - Combineer bij identifierzoekacties altijd afzonderlijke zoekfilters voor officiële titel, documentdatum en bestuursorgaan om afgekapt of ruisrijk resultaat te ondervangen.
- 2026-09-28T15:55:28Z - Pagineer brede titelzoekacties en behandel een lege datumfilter als operationele onzekerheid, niet als een definitief nulresultaat.
- 2026-09-28T15:57:02Z - Bij een generieke titel gecombineerd met alleen een vergaderdatum levert een agenda-zoekactie meerdere plausibele besluiten op; vraag of zoek naar een onderwerp, dossiernummer of officieel identifier.
- 2026-09-28T16:08:37Z - Combineer bij oudere lokale beslissingen een exacte identificatie met datum- en titeltermen en behandel afgekapt zoekresultaat als onvolledig.
- 2026-09-28T16:08:53Z - Combineer identifierzoekopdrachten met datum-, plaats- en documenttypefilters en controleer altijd of de resultaten volledig zijn.
- 2026-09-28T16:09:09Z - Wanneer een zoekopdracht op een exacte identifier een brede, afgekapt lijst met vergaderstukken oplevert, combineer dan afzonderlijke zoekgangen op documenttype, datum en titel voordat kandidaten worden gevalideerd.
- 2026-09-28T16:10:03Z - Bij generieke documenttitels moet naast datum en bestuursorgaan een onderscheidend onderwerp of identifier worden gezocht, omdat bronrecords onder hun concrete agendatitel kunnen zijn geïndexeerd.
- 2026-09-28T16:15:53Z - For local-decision identifiers, verify the year and full official decision identifier rather than accepting substring matches in titles or tax-assessment article numbers.
- 2026-09-28T16:30:16Z - Vul zoekopdrachten naar historische lokale planningsinstrumenten aan met het gemeentelijke archief of een afzonderlijk ruimtelijk-planningsregister.
- 2026-09-28T16:30:51Z - Controleer bij oudere lokale besluiten altijd de volledige paginering van identifierzoekresultaten en combineer die met titel- en datumfilters, omdat exacte zoekopdrachten geen volledige historische dekking kunnen bieden.
- 2026-09-28T16:31:10Z - Combineer bij brede of afgekapt geretourneerde identificatorzoekresultaten genormaliseerde titeltermen met datum- en jurisdictiefilters en controleer alle resultaatpagina’s.
- 2026-09-28T16:31:26Z - Herhaal identifierzoekopdrachten met paginering of smallere filters wanneer de bronresultaten zijn afgekapt.
- 2026-09-28T19:11:56Z - Wanneer een exacte titel- en datumzoekopdracht geen treffers oplevert, zoek dan op onderscheidende titeltermen over een ruimer datumbereik en controleer vervolgens documenttype en bestuursorgaan.
- 2026-09-28T19:12:16Z - When an exact identifier hit conflicts with the requested decision date, verify the item's meeting metadata and publication record before treating it as a match.
- 2026-09-28T19:12:32Z - Wanneer een exacte-identifierzoekopdracht alleen brede, moderne resultaten oplevert, controleer eerst of de bron historische archiefbesluiten indexeert voordat de resultaten als volledig worden beschouwd.
- 2026-09-28T19:15:33Z - When identifier-only searches return broad relevance-ranked results, apply structured filters and inspect all result pages before validating.
- 2026-09-28T19:30:08Z - Voer voor historische lokale besluiten naast identifierzoekopdrachten ook afzonderlijke zoekopdrachten uit op titelvarianten en vergaderdatum, en behandel afgekapt resultaat niet als een volledige negatieve match.
- 2026-09-28T19:34:16Z - When exact title/date filters return no hits, broaden with title-only and normalized-wording searches before treating the source as empty.
- 2026-09-28T19:37:05Z - For older local decisions, combine title-fragment searches with broader date ranges because exact-title and date filters may omit records from the searchable index.
- 2026-09-28T19:54:20Z - When a source rejects an abbreviated governing-body label, retry the search using the source’s supported full organ name.
- 2026-09-28T19:55:14Z - Combineer bij identifierzoekacties die veel heterogene en afgekapt gerangschikte resultaten opleveren de exacte identificator met onderscheidende titeltermen en een datumfilter.
- 2026-09-28T19:56:04Z - Gebruik voor historische lokale beslissingen zowel een exacte identificatorzoekactie als afzonderlijke datum- en titelzoekacties, en behandel afgekapt brede zoekresultaten als onvolledig.
- 2026-09-29T07:16:38Z - Combineer bij historische lokale besluiten titelvarianten, afkortingen en documenttype-termen wanneer exacte titel- en datumfilters geen resultaten geven.
- 2026-09-29T07:28:29Z - When identifier-only searches return broad, truncated results, combine the identifier with distinctive title terms and paginate the source results.
- 2026-09-29T07:32:18Z - Wanneer zoeken op een identifier in een specifiek titelveld niets oplevert, herhaal de zoekactie met de identifier als algemene tekstquery en combineer die zo nodig met titel- en datumfilters.
- 2026-09-29T07:32:35Z - Combineer exacte identifiers met documenttype- en datumfilters en behandel afgekapt resultaat niet als een volledige zoekuitkomst.
- 2026-09-29T07:35:40Z - Controleer bij exacte zoekopdrachten altijd de metadata van het resultaat, omdat de bron een nieuwer of inhoudelijk slechts gelijkend document kan teruggeven.
- 2026-09-29T07:38:07Z - When identifier-only searches return broad relevance-ranked results, combine the identifier with document-type terms and verify the exact identifier in the title or record metadata.
- 2026-09-29T07:40:16Z - Prefer exact application or permit identifiers over broad internal-number searches, which may return many unrelated meeting items.
- 2026-09-29T07:41:58Z - Wanneer een exacte datumzoekactie voor historische lokale besluiten niets oplevert, herhaal de zoekactie met titelvarianten en zonder datumfilter voordat afwezigheid wordt geconcludeerd.
- 2026-09-29T07:42:34Z - Bij een identifier die meerdere gerelateerde vergaderitems oplevert, moeten datum en beslissingstype afzonderlijk worden geverifieerd voordat een kandidaat wordt bevestigd.
- 2026-09-29T07:43:52Z - Numeric identifier searches can return unrelated records sharing the same number; verify the full official title and date before selecting.
- 2026-09-29T07:44:15Z - Treat thematically related results with a mismatched identifier as non-matches, even when an exact-identifier search returns no better candidate.
- 2026-09-29T07:44:31Z - Een exacte identificatiezoekopdracht kan een gerelateerd adviesstuk opleveren in plaats van het uiteindelijke vergunningsbesluit; controleer daarom altijd documentsoort en beslissingsdatum.
- 2026-09-29T07:44:46Z - Controleer bij lokale besluitendatabanken naast het dossiernummer altijd het officiële besluitstype en de beslissingsdatum, omdat zoekresultaten ook adviezen en latere dossierbesluiten kunnen bevatten.
- 2026-09-29T07:45:01Z - Controleer bij identifierzoekopdrachten altijd de officiële titel, datum en documentsoort, omdat de bron ook inhoudelijk niet-overeenkomende resultaten kan teruggeven.
- 2026-09-29T07:46:11Z - Combineer bij brede of afgekaptte identifierzoekresultaten de identifier met meerdere onderscheidende titeltermen en controleer daarna expliciet documentdatum, documenttype en bestuursorgaan.
- 2026-09-29T07:46:29Z - Combineer identificatorzoekopdrachten met exacte titel- en datumverificatie, omdat vrije tekstresultaten breed kunnen zijn en afgekapt kunnen worden.
- 2026-09-29T07:46:47Z - Combineer bij deze bron een identifier met korte titeltermen en een datumfilter, omdat identifier-only zoekopdrachten brede, afgeknotte resultaten kunnen geven.
- 2026-09-29T07:47:38Z - Controleer bij lokale besluiten naast het dossiernummer altijd de officiële beslissingdatum en het volledige besluitopschrift, omdat zoekresultaten ook voorbereidende of gerelateerde vergaderitems kunnen bevatten.
- 2026-09-29T07:49:48Z - Combineer bij historische lokale besluiten titel- en datumzoekopdrachten met documenttype- en bestuursorgaanfilters, omdat brede trefwoordzoekopdrachten veel latere verwijzingen opleveren.
- 2026-09-29T07:50:45Z - Combineer bij lokale besluiten een exacte identificatorzoekopdracht met onderscheidende titeltermen en controleer daarna expliciet documentdatum, documenttype en bestuursorgaan.
- 2026-09-29T07:51:02Z - Bij identifierzoekacties die afgekapt en inhoudelijk heterogeen zijn, moeten aanvullende zoekfilters of bronfan-out worden gebruikt voordat afwezigheid kan worden geconcludeerd.
- 2026-09-29T07:51:19Z - Combineer bij brede of afgekapt gerangschikte identifierresultaten exacte titeltermen met datum- en gemeentefilters.
- 2026-09-29T07:51:35Z - Combineer bij lokale besluiten een exacte identifierzoekopdracht met afzonderlijke filters voor datum, documenttitel en bestuursorgaan, omdat brede identifierresultaten kunnen worden afgekapt.
- 2026-09-29T07:52:37Z - Combineer bij historische lokale besluiten identifier-, titel- en datumzoekingen, maar behandel een lege gefilterde resultaatset niet als bewijs dat het document ontbreekt.
- 2026-09-29T07:53:06Z - Behandel zoekresultaten op een identifier als voorlopige treffers en verifieer altijd titel, documenttype, datum en bestuursorgaan tegen het brondocument.
- 2026-09-29T07:53:22Z - Wanneer een exacte identifierzoekopdracht geen resultaten geeft, probeer dan onderscheidende titeltermen gecombineerd met datum- en documenttypefilters, omdat identifiervelden mogelijk niet volledig doorzoekbaar zijn.
- 2026-09-29T07:54:37Z - Exacte nummerzoekopdrachten kunnen brede, irrelevante lexicale treffers opleveren; combineer nummer, titeltermen, gemeente en beslisdatum en controleer daarna de documentinhoud.
- 2026-09-29T07:55:34Z - Bij historische lokale besluiten kunnen identifier- en datumfilters geen resultaat geven; doorzoek daarom ook historische archieven of registers buiten de moderne besluitenindex.
- 2026-09-29T07:59:16Z - When an exact-date title search returns no results, retry with normalized title terms and a broader date range before concluding that the record is unavailable.
- 2026-09-29T08:04:40Z - When an exact-title query returns no hits, retry with normalized spacing and relevant title-language variants before relying on a broad, truncated result set.
- 2026-09-29T08:06:19Z - Legacy decisions may require searching archival identifier fields separately from modern meeting-item full-text search.
- 2026-09-29T08:06:40Z - Combineer bij historische lokale beslissingen een exacte identifierzoekopdracht met filters voor gemeente, documentdatum en bestuursorgaan om ruis uit moderne resultaten te beperken.
- 2026-09-29T08:11:15Z - Treat place-name matches in later permits or related planning records as leads only; confirm the original instrument by its official title, approval date, document type, and deciding body.
- 2026-09-29T08:12:18Z - Combineer bij lokale besluiten een exacte identifierzoekopdracht met afzonderlijke titel-, datum- en documenttypefilters wanneer de eerste zoekactie geen treffer oplevert.
- 2026-09-29T08:12:35Z - Combineer bij historische lokale besluiten een exacte identifierzoekopdracht met titeltermen en een historische datumfilter, omdat identifierzoekopdrachten anders brede, recente en niet-relevante resultaten kunnen opleveren.
- 2026-09-29T08:17:41Z - Combineer bij ruimtelijke plannen exacte titel- en datumfilters met paginering en een gespecialiseerde bron voor ruimtelijke plannen wanneer algemene besluitzoekresultaten zijn afgekapt.
- 2026-09-29T08:18:26Z - Combineer bij brede, afgekapt terugkerende identifierzoekresultaten de identifier met titeltermen en een datumfilter.
- 2026-09-29T08:20:00Z - When legacy identifiers yield broad noisy results, combine them with distinctive title terms and paginate or fan out the search before validation.
