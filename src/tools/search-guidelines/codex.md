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
- 2026-08-01T12:19:38Z - Type filtering improves focus but does not prove
  document type.
- 2026-08-01T12:19:38Z - High recall requires short queries; high precision
  comes from candidate validation, not from making the query longer.
- 2026-08-01T12:19:38Z - A documented unresolved result is preferable to an
  unverified link.
- 2026-09-22T13:57:55Z - Behandel nulresultaten bij exacte titelzoekopdrachten niet als definitief en controleer bredere resultaten expliciet op basisinstrument versus wijzigingswet.
- 2026-09-22T13:58:24Z - When multiple title-variant searches return zero records, treat the result as a possible indexing limitation and broaden the lookup using verified metadata fields rather than concluding that the document is absent.
- 2026-09-22T14:09:32Z - Bij een exacte titel zonder resultaat: zoek ook genormaliseerde titelvarianten en onderscheid wijzigingswetten van de geconsolideerde basistekst.
- 2026-09-22T14:11:18Z - Controleer bij Codex-resultaten die een gecodificeerd wetboek vermelden altijd of het resultaat het basisinstrument is en niet slechts een wijzigings- of verwijzingsakte.
- 2026-09-22T14:12:58Z - Wanneer een exacte titelzoekopdracht alleen wijzigings- of invoeringswetten oplevert, zoek dan aanvullend naar het afzonderlijke geconsolideerde wetboekrecord.
- 2026-09-22T14:26:34Z - Verify the instrument date independently when an exact-title search returns a similarly titled historical document.
- 2026-09-23T10:51:02Z - A trace-backed behavior worth reviewing offline.
- 2026-09-23T11:00:48Z - When a title search returns a similarly named instrument with a conflicting date, verify the date and document type explicitly and perform a date-focused search before selecting it.
- 2026-09-24T07:03:02Z - Geef bij Codex-zoekopdrachten voor basisinstrumenten voorrang aan een exacte titel- en datumcombinatie boven brede trefwoorden, die vooral wijzigingsdocumenten kunnen opleveren.
- 2026-09-24T11:24:35Z - Als een exacte titelzoekopdracht geen resultaten oplevert, zoek dan op het onderliggende decreet en filter vervolgens op het documenttype om het basisinstrument van wijzigingsbesluiten te onderscheiden.
- 2026-09-24T12:12:12Z - When an exact-title search returns no results, retry with distinctive title fragments and broader jurisdictional terms before treating the source as exhaustive.
- 2026-09-28T13:39:27Z - When a title search returns both a named base instrument and later amendments or implementing instruments, prefer the instrument whose official title directly matches the cited short title.
- 2026-09-28T13:49:40Z - When title searches return only documents citing an instrument, search separately for the instrument’s formal adoption metadata and document type.
- 2026-09-28T13:49:58Z - If an exact-identifier lookup returns no result, preserve candidates already confirmed by a complete title-based search rather than treating the lookup as authoritative emptiness.
- 2026-09-28T13:53:10Z - When an exact-title query returns no results, retry with distinctive title fragments and without document-type filters before concluding that the instrument is absent.
- 2026-09-28T13:58:38Z - When an exact phrase appears inside a longer official title, verify whether it names the instrument itself or only a plan or context cited by that instrument.
- 2026-09-28T14:00:55Z - When an exact-title search returns no result, search the title stem and distinguish the base instrument from amendments, implementing acts, and circulars by their official titles.
- 2026-09-28T14:02:35Z - When an exact-title search returns no result, retry with distinctive title fragments and the document type before validating related instruments.
- 2026-09-28T14:02:53Z - When broad title searches return related instruments but no exact match, verify the official title and date against the source before selecting a candidate.
- 2026-09-28T14:12:25Z - For historical instruments, broaden exact-title searches with a distinctive geographic phrase and the relevant document type.
- 2026-09-28T14:13:10Z - Zoek voor technische achtergronddocumenten ook naar afzonderlijke publicaties of bijlagen, omdat de brondatabase vooral het onderliggende regelgevende besluit kan teruggeven.
- 2026-09-28T14:19:08Z - Zoek bij Codex-verwijzingen naar begeleidende technische documenten afzonderlijk van het juridische basisinstrument, omdat zulke documenten niet altijd onder dezelfde titel worden geïndexeerd.
- 2026-09-28T14:20:41Z - When an exact-title search returns no records, combine distinctive title terms with the document date and governing-body filter before relying on broad partial-title matches.
- 2026-09-28T14:20:55Z - Wanneer een informele titel geen resultaten oplevert, zoek opnieuw met de formele onderwerpsterm en filter vervolgens op documenttype.
- 2026-09-28T14:24:02Z - When an exact-title search returns no results, retry with distinctive title fragments and a document-type filter.
- 2026-09-28T14:24:17Z - When an exact-title search returns no result, search distinctive title fragments together with the governing body and date, then verify the full official title and instrument type.
- 2026-09-28T14:29:46Z - When an exact Codex title search returns no result, search a distinctive noun phrase and distinguish the base instrument from provider-specific approvals, amendments, and related documents.
- 2026-09-28T14:30:07Z - When an exact multi-term title search returns no hits, retry using its distinctive noun phrase and vary document-type filters.
- 2026-09-28T14:31:18Z - When an exact-title search returns no results, search distinctive title fragments with the document type and governing body, then verify the complete official title and date.
- 2026-09-28T14:32:11Z - When a colloquial title returns no hits, retry with the official subject wording and document type.
- 2026-09-28T14:33:19Z - When an exact-title search returns no results, retry with distinctive title fragments and historical instrument terminology before validating dates and document type.
- 2026-09-28T14:35:23Z - When an exact-title search returns no results, broaden the query to the governing decree or subject while retaining the document-type filter.
- 2026-09-28T14:38:08Z - When an exact-title search returns no records, retry with core title variants and enactment terms, then verify neighboring results against the official title and date rather than treating related hits as matches.
- 2026-09-28T14:40:09Z - When an exact-title query returns no hits, search using the enabling instrument and filter by document type.
- 2026-09-28T14:41:16Z - Wanneer een exacte titelzoekopdracht geen resultaat oplevert, zoek dan ook naar het onderliggende rechtsinstrument en controleer gekoppelde of begeleidende documenten in plaats van de lege zoekuitkomst als definitief te beschouwen.
- 2026-09-28T14:42:20Z - Zoek naast de citeertitel ook op de formele titel en filter waar mogelijk op documenttype.
- 2026-09-28T14:42:36Z - When an exact-title search returns no result, broadened searches may surface related planning instruments, so candidate identity must be checked against the requested instrument type and date.
- 2026-09-28T14:42:52Z - When an exact Codex title search returns no result, broaden by document type and jurisdictional place name, then verify the full official title and decision date rather than selecting a related instrument.
- 2026-09-28T14:43:35Z - When exact-title searches return no records, include common instrument-type synonyms and punctuation or wording variants in follow-up Codex searches.
- 2026-09-28T14:43:50Z - When an exact-title search returns no results, retry with document-type variants and approval-date terms before treating related-result listings as exhaustive.
- 2026-09-28T14:46:42Z - Bij een nulresultaat op een exacte titelzoekopdracht: herhaal de zoekactie met titelvarianten, datum en vermoedelijk documenttype en controleer afzonderlijk basisinstrumenten en wijzigingen.
- 2026-09-28T14:46:58Z - Wanneer een exacte titelzoekopdracht geen resultaat oplevert, zoek dan ook op onderscheidende titelonderdelen en controleer vervolgens de officiële titel, datum en documentsoort.
- 2026-09-28T14:47:47Z - Wanneer een exacte titelzoekopdracht geen resultaat oplevert, probeer onderscheidende titelonderdelen gecombineerd met datum en documenttype om anders getitelde basisinstrumenten of wijzigingen te vinden.
- 2026-09-28T14:49:03Z - When an exact-title alias search returns no hits, search using the instrument’s enabling-law formulation and filter by document type to surface the base instrument.
- 2026-09-28T14:49:37Z - Bij nulresultaten voor titelzoekopdrachten ook zoeken op genormaliseerde titelvarianten en afzonderlijk filteren op documenttype, datum en bevoegd bestuursorgaan.
- 2026-09-28T14:49:58Z - When a combined legal title returns no exact match, search its constituent terms separately and distinguish base instruments from supplier-specific approvals.
- 2026-09-28T14:51:08Z - Wanneer een exacte titelzoekopdracht niets oplevert, probeer genormaliseerde titelvarianten gecombineerd met documenttype en historische datumfilters.
- 2026-09-28T14:51:25Z - When an exact-title search returns no result, broaden by document type and distinctive geographic terms, then verify the official instrument title and decision date before selecting a related plan.
- 2026-09-28T14:56:10Z - When exact-title searches fail, broaden the query with distinctive title terms and document-type variants, then verify the official title, instrument type, and date before selecting a result.
- 2026-09-28T14:58:25Z - Bij een nuluitslag voor een exacte Codex-titel, zoek opnieuw met onderscheidende titelonderdelen en controleer daarna expliciet het formele plantype en de vaststellingsdatum.
- 2026-09-28T14:58:40Z - Gebruik bij regelgeving ook officiële documenttypesynoniemen en titelvarianten wanneer een exacte titelzoekopdracht geen resultaten oplevert.
- 2026-09-28T15:00:01Z - When an exact-title search returns no result, broaden the query with distinctive title phrases and inspect related planning instruments across document types.
- 2026-09-28T15:04:35Z - Wanneer een exacte titelzoekopdracht geen resultaten geeft, probeer ook een verkorte geografische benaming en historische termen voor het instrumenttype.
- 2026-09-28T15:06:35Z - When an exact-title search returns no results, retry with normalized title terms and inspect related instruments for a distinct base document rather than treating the result as authoritative absence.
- 2026-09-28T15:06:51Z - Bij brede Codex-zoekopdrachten op gedeeltelijke plaats- of gebiedsnamen moet de volledige officiële titel en datum worden gecontroleerd om semantisch verwante maar onjuiste besluiten uit te sluiten.
- 2026-09-28T15:08:05Z - Bij samengestelde reglementtitels in Codex werkt zoeken op de kernterm met het documenttype vaak beter dan zoeken op de volledige titel.
- 2026-09-28T15:09:58Z - When an exact-title search returns no records, retry with distinctive title fragments and without restrictive document-type filters.
- 2026-09-28T15:13:20Z - For Flemish spatial-planning instruments, search both the plan title and the formal decision title, then verify the decision date and whether the result is the base plan rather than a later implementation decision.
- 2026-09-28T15:15:01Z - For Codex lookups, retry with normalized title terms and document type separately when an exact-title query returns no candidates.
- 2026-09-28T15:15:45Z - Wanneer titel- en procedurele synoniemzoekopdrachten geen resultaten opleveren, probeer ook de canonieke documenttypeclassificatie van de bron en termen uit de artikeltekst.
- 2026-09-28T15:16:15Z - Bij juridische zoekopdrachten met een volledige plannaam: zoek ook op de genormaliseerde kernnaam en controleer daarna expliciet documentsoort en officiële titel.
- 2026-09-28T15:18:27Z - Wanneer een exacte titelzoekopdracht niets oplevert, zoek dan afzonderlijke kenmerkende titelonderdelen en controleer daarna expliciet basisinstrumenten, goedkeuringsbesluiten en wijzigingen.
- 2026-09-28T15:19:17Z - Zoek naast de benaming van een plan ook op de officiële titel van het besluit dat het plan vaststelt of goedkeurt.
- 2026-09-28T15:19:31Z - Bij een nulresultaat op een exacte titel in Codex ook zoeken met onderscheidende titelfragmenten en het documenttype.
- 2026-09-28T15:20:47Z - When an exact-title search fails, broaden by document function and approval wording, then verify the date before selecting a related instrument.
- 2026-09-28T15:22:35Z - When an exact-title search returns no result, broaden with distinctive title terms and date while separately verifying that returned records concern the same instrument rather than a related plan or amendment.
- 2026-09-28T15:23:23Z - When an exact-title search returns no result, search the distinctive noun phrase separately and distinguish base regulations from approval decisions, amendments, and related implementing measures.
- 2026-09-28T15:24:52Z - When an exact-title search returns no hits, retry without imposing a potentially mismatched document-type filter before concluding that no document is available.
- 2026-09-28T15:25:22Z - Probeer bij samengestelde officiële titels naast de volledige titel ook genormaliseerde zoekvarianten met weggelaten lidwoorden, voegwoorden en leestekens.
- 2026-09-28T15:27:57Z - Bij een nulresultaat op de exacte titel moeten genormaliseerde titelvarianten en de documentdatum worden gebruikt voordat semantisch verwante plannen als match worden overwogen.
- 2026-09-28T15:31:12Z - Valideer bij brede titelzoekopdrachten steeds de volledige officiële titel en het documenttype, omdat lexicale deelmatches inhoudelijk andere ruimtelijke plannen kunnen opleveren.
- 2026-09-28T15:32:21Z - When broad title searches return related instruments, verify the complete official title and document kind before treating a result as a match.
- 2026-09-28T15:34:21Z - Zoek bij een gangbare citeernaam ook op de onderliggende officiële titel en het uitvoeringsdecreet, omdat een exacte titelzoekopdracht geen resultaten kan opleveren.
- 2026-09-28T15:34:48Z - When exact-title and document-type searches return no records, try distinctive title fragments together with the formal instrument wording used by the issuing authority.
- 2026-09-28T15:36:21Z - When exact-title and document-type searches return no records, retry using the source’s formal instrument terminology and publication metadata.
- 2026-09-28T15:37:06Z - When an exact compound title returns no results, retry with its distinctive core terms and then distinguish base instruments from provider-specific approvals.
- 2026-09-28T15:38:39Z - Wanneer zoekopdrachten op een exacte identifier of titel niets opleveren, verbreed de zoekopdracht en pagineer volledige resultaten voordat een document als afwezig wordt beschouwd.
- 2026-09-28T15:39:05Z - When exact-title searches return no results, retry with distinctive title fragments and document-type variants before treating the candidate pool as exhaustive.
- 2026-09-28T15:43:59Z - Voer bij een lege exacte titelzoekopdracht een tweede zoekronde uit met onderscheidende titelonderdelen en de formele vaststellingsformule.
- 2026-09-28T15:45:30Z - Wanneer een exacte Codex-titelzoekopdracht niets oplevert, combineer bredere titeltermen met documenttype en datum, maar verifieer steeds de volledige officiële titel en het instrumenttype.
- 2026-09-28T15:48:51Z - When an exact-title query returns no result, search separately for base instruments and related implementing approvals before resolving.
- 2026-09-28T15:50:06Z - When exact-title searches return no hits, broaden the query with distinctive title fragments and inspect related instruments, while verifying the official title and date before selecting a result.
- 2026-09-28T15:50:38Z - Zoek bij begeleidende of technische documenten naast de regelingstitel ook op documenttype- en titelvarianten, omdat zulke documenten afzonderlijk kunnen zijn geïndexeerd.
- 2026-09-28T15:51:31Z - Wanneer een exacte titelzoekopdracht geen resultaten geeft, zoek de onderscheidende titelonderdelen afzonderlijk en varieer de documentsoort.
- 2026-09-28T15:55:02Z - Controleer bij zoekresultaten voor een basisinstrument expliciet of het resultaat het oorspronkelijke besluit is en niet een later wijzigingsbesluit dat er alleen naar verwijst.
- 2026-09-28T15:56:09Z - In Codex, retry compound legal-title searches with separated terms and the formal “houdende” wording when the exact title returns no result.
- 2026-09-28T15:58:11Z - For Flemish spatial plans, search with GRUP or “ruimtelijk uitvoeringsplan” terminology and avoid restricting the document type to executive orders.
- 2026-09-28T15:59:48Z - When an exact Codex title search is empty, retry with normalized title terms and related planning terminology before concluding that no match exists.
- 2026-09-28T16:03:05Z - Zoek bij plannen van aanleg ook op officiële vaststellings- of goedkeuringsbesluiten, omdat een titelzoekopdracht vooral verwante aanwijzings- en wijzigingsbesluiten kan opleveren.
- 2026-09-28T16:07:25Z - Bij nulresultaten op een exacte titel: zoek opnieuw op onderscheidende kerntermen en documenttype, en controleer daarna strikt titel, datum en instrumenttype.
- 2026-09-28T16:09:40Z - Controleer bij titelzoekopdrachten of een resultaat een basisinstrument is of slechts een later wijzigingsbesluit dat het gezochte instrument citeert.
- 2026-09-28T16:12:48Z - On Codex, broaden failed exact-title searches with document-type or approval terms, then distinguish the requested base instrument from related enabling, amending, or implementing acts.
- 2026-09-28T16:13:04Z - On Codex, retry exact-title searches with documented title variants and relevant instrument-type filters when the initial query returns no results.
- 2026-09-28T16:16:52Z - When exact-title and name-only searches return no records, broaden the search with date fields and spelling or punctuation variants before concluding that the document is absent.
- 2026-09-28T16:17:47Z - When an exact-title search returns no hits, search formal document-type terminology together with distinctive title fragments and verify the resulting document date and title before selecting a candidate.
- 2026-09-28T16:20:27Z - When an acronym search returns many amendments, search the source for the instrument’s full official title and filter by the original document kind.
- 2026-09-28T16:21:45Z - Combineer bij normatieve documenten een exacte titelzoekopdracht met een zoekopdracht op een onderscheidende plaatsnaam en documenttype om verwante instrumenten te vinden.
- 2026-09-28T16:22:00Z - Wanneer exacte titel-, datum- en typezoekopdrachten geen resultaat opleveren, verbreed de zoekterm met documentgenerieke planterminologie en verifieer titel en datum vervolgens handmatig.
- 2026-09-28T16:22:26Z - Gebruik bij decreten naast de gangbare benaming ook genormaliseerde kerntermen en het documenttype, omdat een exacte titelzoekopdracht geen resultaat kan opleveren.
- 2026-09-28T16:23:09Z - When an exact-title search returns no result, broaden searches with historical instrument terms such as the plan’s approval or designation wording, then distinguish the base plan from later amendments.
- 2026-09-28T16:23:20Z - When broadening Codex searches, verify the complete plan title because results may be related instruments rather than the requested base document.
- 2026-09-28T16:26:41Z - Bij nulresultaten voor een exacte titel ook zoeken op de officiële vaststellingshandeling en de relevante documentcategorie.
- 2026-09-28T16:27:10Z - Bij een lege exacte zoekopdracht: zoek met kenmerkende titelgedeelten en documenttype, maar verifieer titel en datum expliciet om verwante wijzigingen of voorbereidende besluiten niet als basisakte te selecteren.
- 2026-09-28T16:29:43Z - Bij een mislukte exacte titelzoekopdracht opnieuw zoeken met datum, documenttype en varianten van de titel of spelling.
- 2026-09-28T16:29:58Z - Wanneer een exacte Codex-zoekopdracht geen resultaat geeft, probeer onderscheidende titelonderdelen gecombineerd met de standaardbenaming van het document en de bevoegde instantie.
- 2026-09-28T16:32:07Z - When an exact-title search returns no result, search normalized title variants and inspect related instruments while separately verifying whether each result is the base instrument or an amendment.
- 2026-09-28T19:09:36Z - For historical planning instruments, combine exact-title searches with searches for the underlying designation or approval instrument, since source indexes may return related amendments instead of the base instrument.
- 2026-09-28T19:14:45Z - Zoek in Codex eerst op de volledige titel zonder documenttypefilter en controleer daarna steeds de volledige officiële titel en datum, omdat verwante ruimtelijke plannen kunnen worden teruggegeven.
- 2026-09-28T19:16:24Z - When an exact-title lookup returns no results, retry with distinctive title terms combined with the document type and date, then verify whether broader results are related instruments or the requested base document.
- 2026-09-28T19:17:00Z - When a search targets an annex or technical section, also inspect the parent instrument because the index may expose only the instrument title.
- 2026-09-28T19:18:11Z - Bij historische Codex-documenten die niet op de exacte titel vindbaar zijn, zoek ook op de goedkeuringsdatum en op alternatieve termen zoals ‘gewest’ of ‘plan van aanleg’.
- 2026-09-28T19:18:25Z - When an exact-title search yields no result, search distinctive title fragments separately and verify the instrument type and date against the full official title.
- 2026-09-28T19:18:56Z - Bij een nulresultaat voor een exacte titelzoekopdracht: zoek ook op afzonderlijke titeltermen en onderscheid daarna basisinstrumenten van goedkeuringsbesluiten, aanvullingen en wijzigingen.
- 2026-09-28T19:20:34Z - When exact-title and document-type searches return no hits, try shorter title stems but verify every result against the complete official instrument title and document type.
- 2026-09-28T19:21:16Z - Wanneer een exacte titelzoekopdracht niets oplevert, probeer onderscheidende plaatsnaamvarianten en bredere planningszoektermen zonder het documenttype te strikt te beperken.
- 2026-09-28T19:21:27Z - Bij brede Codex-zoekopdrachten met thematische nabijtreffers moeten de volledige officiële titel en documentdatum afzonderlijk worden geverifieerd.
- 2026-09-28T19:22:48Z - Gebruik bij Codex-zoekopdrachten naar ruimtelijke plannen onderscheidende titelonderdelen samen met planterminologie en verifieer steeds de officiële titel en datum voordat een verwant resultaat wordt geselecteerd.
- 2026-09-28T19:23:36Z - Neem bij Vlaamse Codex-verwijzingen ook de officiële lange titel en de onderliggende decreetverwijzing op wanneer een gangbare citeertitel geen directe zoekresultaten geeft.
- 2026-09-28T19:23:48Z - When broad title searches return only related instruments, also search by document type, approval date, and base-instrument terms such as “vaststelling” or “goedkeuring”.
- 2026-09-28T19:25:07Z - Voer bij nulresultaten naast titel- en datumzoekopdrachten ook een afzonderlijke zoekopdracht uit op de unieke identificator.
- 2026-09-28T19:25:21Z - Bij een nulresultaat op de volledige titel kunnen kortere titelvarianten en afzonderlijke datumzoekopdrachten verwante besluiten opleveren, maar die moeten afzonderlijk op documentsoort en datum worden gevalideerd.
- 2026-09-28T19:25:34Z - Vermijd een strikte documenttypefilter wanneer de bronclassificatie mogelijk afwijkt van de classificatie in de referentie.
- 2026-09-28T19:26:24Z - Bij een exacte zoekopdracht zonder resultaat: zoek ook op bredere documenttype-termen en controleer gerelateerde aanwijzings- of wijzigingsakten, maar behandel die niet automatisch als het gevraagde basisinstrument.
- 2026-09-28T19:26:38Z - When an exact-title search is empty, broaden the query with the official document type and adoption date, then verify the title and date manually.
- 2026-09-28T19:27:03Z - When an exact title search returns no results, search each substantive title component separately and classify base instruments apart from amendments and implementing approvals.
- 2026-09-28T19:28:14Z - For absent exact-title hits, combine shorter distinctive phrase searches with document-type terms and inspect nearby results rather than treating zero hits as authoritative.
- 2026-09-28T19:28:34Z - Wanneer een exacte titelzoekopdracht niets oplevert, zoek dan opnieuw op een onderscheidende geografische titelcomponent in combinatie met het documenttype om verwante Codex-records te vinden.
- 2026-09-28T19:28:51Z - When exact-title and document-type searches return no results, broaden the query with related planning terminology and verify returned documents against the full official title and date.
- 2026-09-28T19:30:21Z - Wanneer een exacte titelzoekopdracht geen resultaat geeft, zoek ook met titelankers en documenttype en controleer verwante basisinstrumenten, wijzigingen en uitvoeringsbesluiten.
- 2026-09-28T19:30:37Z - When an exact-title Codex search returns no result, retry with distinctive title fragments and the instrument type or official establishing formula before treating the candidate set as exhaustive.
- 2026-09-28T19:31:38Z - When exact-title and document-type searches return no results, retry broader title variants without the type filter because historical instruments may be indexed under different document kinds.
- 2026-09-28T19:31:54Z - When exact-title searches return no result, broaden distinctive title terms separately and inspect returned official titles before concluding that no match exists.
- 2026-09-28T19:33:12Z - When an exact-title search returns no results, retry with distinctive title fragments and related planning terminology without imposing a possibly incorrect document-type filter.
- 2026-09-28T19:33:59Z - On Codex, combine distinctive title fragments with the document type and the governing body's standard decision wording when an exact-title search returns no result.
- 2026-09-28T19:36:44Z - When exact-title searches return no records, retry with the source’s formal instrument type and normalized title variants.
- 2026-09-28T19:37:40Z - When exact-title searches return no hits, broaden the query but verify the complete official title, document kind, date, and governing body instead of accepting merely related planning instruments.
- 2026-09-28T19:38:42Z - When an exact-title search returns no hits, retry with shorter distinctive title fragments and historical terminology.
- 2026-09-28T19:38:57Z - When an exact Codex title search yields no result, retry with distinctive title fragments and broader plan-type terminology.
- 2026-09-28T19:40:10Z - When an exact-title search returns no results, broaden the geographic query and inspect related instruments while distinguishing base plans from amendments and revision decrees.
- 2026-09-28T19:41:04Z - When an exact-title search returns no result, search normalized title terms together with the likely instrument type and governing body.
- 2026-09-28T19:41:17Z - Gebruik bij officiële regelgeving naast onderwerptermen ook titelvarianten en identificerende metadata, en behandel inhoudelijk verwante treffers niet als titelmatches.
- 2026-09-28T19:44:31Z - Bij een lege exacte zoekopdracht moet de bronzoekactie worden verbreed met formele instrumenttermen en vervolgens worden gecontroleerd op officiële titel en besluitdatum voordat een verwant document wordt geselecteerd.
- 2026-09-28T19:46:02Z - Bij een lege zoekopdracht op een samengestelde titel, probeer ook de onderscheidende stam met documenttype, omdat titelindexering samengestelde benamingen kan missen.
- 2026-09-28T19:46:33Z - Wanneer zoekopdrachten op exacte titel en documenttype geen treffers opleveren, probeer aanvullend te zoeken op datum en uitgevende instantie voordat verwante documenten worden beoordeeld.
- 2026-09-28T19:49:04Z - For historical spatial plans, search by approval date and plan designation separately when exact-title retrieval returns no result.
- 2026-09-28T19:50:42Z - When an exact-title Codex search returns no result, retry with the distinctive title terms and likely document type/date filters before treating the candidate pool as exhaustive.
- 2026-09-28T19:51:37Z - When an abbreviated instrument title returns no hits, search Codex with the formal enactment phrase and document type.
- 2026-09-28T19:51:49Z - When exact-title searches return no hits, retry normalized title variants and document-type filters before concluding unresolved.
- 2026-09-28T19:52:59Z - Map colloquial instrument names to the source’s full official title before filtering candidates by article.
- 2026-09-28T19:53:22Z - When exact-title searches return no hits, search the source by document type, date, and distinctive title fragments before accepting related documents.
- 2026-09-28T19:54:35Z - When exact-title searches return no result, inspect related thematic records but require an exact match on the instrument’s official title and date before selecting a candidate.
- 2026-09-28T19:57:43Z - When exact-title searches fail, broaden the plan-title query but verify the returned instrument’s complete official title, document kind, and decision date before selecting related measures.
- 2026-09-28T19:58:59Z - When an exact plan title returns no result, retry using the source’s broader terminology for plans of development or land-use plans.
- 2026-09-28T19:59:12Z - If an exact-title search returns no result, broaden the query with distinctive title terms and related instrument terminology before concluding that no match exists.
- 2026-09-28T20:01:12Z - Voer bij gewestplannen ook een zoekopdracht uit op titelvarianten zonder lidwoorden en met afzonderlijke plaats- of kanaalzone-termen.
- 2026-09-29T07:18:34Z - Bij een mislukte exacte Codex-titelzoekopdracht kan een zoekopdracht op de onderscheidende kernterm met een losser of weggelaten documenttype titelvarianten opleveren.
- 2026-09-29T07:20:24Z - When an exact-title Codex search returns no hits, retry with broader title fragments combined with the document type and governing body.
- 2026-09-29T07:22:02Z - Wanneer een exacte titelzoekopdracht geen resultaat geeft, zoek ook op onderscheidende onderwerpstermen in combinatie met het documenttype om de formele titel te vinden.
- 2026-09-29T07:24:50Z - When an exact title query yields no result, retry with distinctive subsection terms and broader title phrases.
- 2026-09-29T07:25:35Z - When an exact legal shorthand title yields no results, retry with the instrument’s subject matter and document-type filter to surface the official long title.
- 2026-09-29T07:25:47Z - Bij een lege exacte titelzoekopdracht in Codex: zoek daarna met genormaliseerde titeltermen en documenttype, en controleer of de treffers basisakten, wijzigingen of uitvoeringsbesluiten zijn.
- 2026-09-29T07:28:10Z - When an exact-title search returns no hits, retry with distinctive title fragments and the document type, then verify the official title and date against the returned records.
- 2026-09-29T07:31:02Z - Zoek in Codex eerst op genormaliseerde plaatsnaamfragmenten en verifieer daarna titel, documenttype en datum van het instrument.
- 2026-09-29T07:31:16Z - When an exact-title Codex search returns no hits, retry with distinctive title terms plus the document type and inspect related regional spatial-plan results without treating the initial empty result as authoritative.
- 2026-09-29T07:33:52Z - When an exact-title Codex search returns no result, broaden the plan terminology and verify each related hit against the full official title and document date rather than treating zero hits as authoritative.
- 2026-09-29T07:39:13Z - When an exact-title query returns no hits, retry with a shorter title stem combined with the likely document-type term to surface indexed variants.
- 2026-09-29T07:41:28Z - Wanneer een exacte titelzoekopdracht geen resultaat geeft, zoek ook op afzonderlijke kerntermen en controleer verwante instrumenten afzonderlijk op documentsoort en datum.
- 2026-09-29T07:43:38Z - Broad thematic searches can return related instruments with overlapping geographic terms; validate the exact official title and decision date before selecting a candidate.
- 2026-09-29T07:49:15Z - Wanneer een exacte titelzoekopdracht niets oplevert, zoek dan aanvullend op onderscheidende plaatsnaamtermen met het juiste documenttype en controleer daarna titel en datum tegen het officiële document.
- 2026-09-29T07:57:38Z - When an exact-title search returns no hits, retry with broader thematic terms and alternate document-type filters before concluding that no matching instrument exists.
- 2026-09-29T07:58:58Z - When exact-title searches return no result, combine the document type with distinctive jurisdictional terms and verify the resulting instrument's official title and date before selecting it.
- 2026-09-29T08:00:26Z - On Codex, supplement exact-title searches with alternate document-type labels and date or governing-body filters when a known instrument is not returned.
- 2026-09-29T08:02:01Z - Bij lege Codex-resultaten voor een gewestplan moet ook worden gezocht op de formele titel van het goedkeuringsbesluit en op varianten van het documenttype.
- 2026-09-29T08:02:16Z - Treat broader Codex results for related planning instruments as leads only; verify the exact official title and decision date before selecting.
- 2026-09-29T08:02:30Z - When a generic regulation title matches multiple historical instruments, add a year or other identifying qualifier to distinguish the applicable version.
- 2026-09-29T08:06:02Z - Combineer bij regelgeving een exacte titelzoekopdracht met een zoekopdracht op goedkeuringsdatum en documenttype wanneer de titelvariant geen resultaat oplevert.
- 2026-09-29T08:07:52Z - Bij een lege exacte titelzoekopdracht in Codex: zoek ook op naamvarianten, maar controleer vervolgens afzonderlijk de datum en het documenttype om basisinstrumenten van wijzigingen of voorbereidende besluiten te onderscheiden.
- 2026-09-29T08:09:14Z - Als een exacte titelzoekopdracht niets oplevert, zoek daarna op onderscheidende titeltermen zonder documenttypefilter en controleer de volledige metadata van de gevonden verwante documenten.
- 2026-09-29T08:11:29Z - When an exact-title query returns no hits, retry with distinctive geographic terms and inspect related instruments because catalog titles may use variant terminology.
- 2026-09-29T08:11:45Z - For Codex, treat broad thematic matches as leads only and verify the complete official title and decision date before selecting a document.
- 2026-09-29T08:12:01Z - When an informal legal title has no exact hit, search both its distinctive subject phrase and common formal-title variants, then require date or identifier data before selecting among similarly titled instruments.
- 2026-09-29T08:13:47Z - When an exact-title search returns no result, normalize the query and distinguish related planning-program decisions from the underlying base plan.
- 2026-09-29T08:14:01Z - For spatial plans, search Codex using the full formal adoption-title pattern and the decision date, rather than relying only on the abbreviated plan title.
- 2026-09-29T08:17:22Z - Zoek bij Codex-ruimtelijke-planningsakten ook op onderscheidende titelgedeelten afzonderlijk en verifieer daarna de volledige officiële titel in het documentrecord.
- 2026-09-29T08:19:22Z - When an exact-title search returns no result, broaden the query while filtering out similarly named plans and later implementing or amending instruments.
- 2026-09-29T08:21:34Z - When exact-title searches are empty, broaden by document type and governing body, then verify the official title and date before selecting a related record.
- 2026-09-29T08:22:16Z - Searches for implementing instruments should also include the official title or date of the underlying decree, because database results may primarily return later amendments.
- 2026-09-29T08:23:59Z - When an exact-title lookup is empty, retry with normalized word order and broader place-name terms before concluding that no matching document exists.
- 2026-09-29T08:25:38Z - Controleer bij zoekresultaten met een verwijzing naar een instrument afzonderlijk of het resultaat het basisinstrument dan wel slechts een wijzigingsbesluit is.
- 2026-09-29T11:25:00Z - Stedenbouwkundige verordeningen (SVO, gewSVO, gemSVO) and bouwverordeningen (BVO, gewBVO, gemBVO, e.g. hemelwater, toegankelijkheid, bouwreglement) as well as spatial plans (RUP, BPA, gewestplan) should be resolved through DsiSearch rather than CodexSearch.
- 2026-09-29T14:46:42Z - Gebruik na een brede titelzoekopdracht documenttype en datum om het basisinstrument van latere wijzigingsakten te onderscheiden.
