# Official federal and European web search

Use this source for Belgian federal instruments and European Union instruments
when the Vlaamse Codex does not cover the referenced legal level. Search only
official publisher pages returned from these exact HTTPS hosts:

- `ejustice.just.fgov.be` for Belgian federal legislation;
- `eur-lex.europa.eu` for European Union legislation;
- `www.remi.legal` for legal-reference results from Remi.

The adapter uses DDGS only for discovery. It sends one request per allowed host
with a query of the form `query site:host`; do not add `site:` expressions to
the tool argument.

DDGS title and body snippet are the only evidence available in this version.
The adapter does not fetch result pages. Treat snippets as discovery evidence,
not proof of identity: confirm the instrument's title, kind, identifier, date,
and jurisdiction where the snippet makes those facts available. Remain
unresolved or ambiguous when the evidence cannot uniquely identify the cited
instrument. Never accept a result from another host, an HTTP URL, a subdomain,
or a page that merely cites the instrument.

The optional document type is retained for the shared search contract but is
not a DDGS filter in this version. Refine the title or identifier when useful,
and treat an empty successful lookup separately from a faile## Query construction rules

Build a short discovery query from the normalized instrument identity. Search
for the base document, not the specific citation or provision where it occurs.

### 1. Strip leading articles and citation preambles
- Remove leading Dutch definite/indefinite articles (`De`, `Het`, `Een`) and
  citation lead-ins (`de bepalingen van`, `krachtens`, `zie`, `artikel ... van`).
- Publishers index instruments by their core title (e.g. `Nieuwe Gemeentewet`,
  not `De Nieuwe Gemeentewet`). Searching with `"De Nieuwe Gemeentewet"` fails or
  returns amending acts, whereas `"Nieuwe Gemeentewet"` immediately matches the
  base act.

### 2. Never include article, paragraph, or point locators in discovery
- **Omit all locators** (`artikel 119`, `art. 42`, `§ 1`, `1°d`, `tweede lid`) from
  initial search queries.
- **Why locators cause zero hits or wrong hits:**
  1. *Zero hits:* Database page titles and metadata index the instrument name,
     not every provision inside it. Requiring an article number in an exact or
     tight query commonly excludes the base instrument page.
  2. *Wrong hits (amending acts):* When an article number does appear in search
     snippets or titles, it almost always belongs to a later **amending act**
     (e.g., *"Wet tot wijziging van artikel 119 van de nieuwe gemeentewet"*),
     causing the validator to reject the candidate pool.
  3. *Special character tokenization:* Symbols like `§` and `°` cause tokenization
     failures in web search engines.
- **Where locators belong:** Locators belong exclusively in the **validation phase**.
  Discover the base instrument first; verify the cited article against candidate
  metadata or body text during validation.
- Only add an article number as a late, unquoted fallback on Attempt 3 if multiple
  competing base instruments share the same title and date. Never include paragraph
  markers (`§`, `lid`, `1°`).

### 3. Use quotes selectively—never quote the full reference
- **Never quote the complete reference:** Quoting an entire extracted string
  (e.g. `"de Wet van 02 oktober 2017 tot regeling van de private en bijzondere veiligheid"`
  or `"De Nieuwe Gemeentewet, artikel 119"`) returns **zero hits** because web
  search engines require an exact character-by-character match including commas,
  prepositions, and padding.
- **Never quote generic terms with dates:** Queries like `"wet 28 december 1983"`
  return zero hits.
- **Never overquote multiple distinct phrases together:** Quoting separate parts
  simultaneously (e.g. `"Wet inzake overheidsopdrachten" "17 juni 2016"`) over-constrains
  the search. Keep one phrase quoted and other terms unquoted.
- **Do quote a clean, multi-word canonical title phrase:**
  - `"Nieuwe Gemeentewet"` → Base law NUMAC 1988062450 at Rank 0.
  - `"Algemene Verordening Gegevensbescherming"` → CELEX 32016R0679 at Rank 0.
  - `"Wet betreffende de gemeentelijke administratieve sancties"` → NUMAC 2013000441 at Rank 0.
  - `"Richtlijn 2006/123/EG"` → CELEX 32006L0123 at Rank 0/1.

### 4. Inclusion of dates and proper date formatting
- **When to include dates:**
  - *Generic titles:* For generic acts (`wet`, `koninklijk besluit`), the enactment
    date is the primary distinguishing fact and must be included.
  - *Titled acts:* Include the date when it disambiguates the base enactment from
    later amendments (e.g. `Wet inzake overheidsopdrachten 17 juni 2016`).
  - *Do not add dates to named codes:* Avoid adding dates to instruments known
    universally by title (e.g. `Nieuwe Gemeentewet`, `Grondwet`, `AVG`).
- **Date format rules (Belgian and EU publishers):**
  - **Use natural Dutch text dates:** `28 december 1983`, `17 juni 2016`, `2 oktober 2017`.
  - **Remove leading zeros on days:** Use `2 oktober 2017`, NOT `02 oktober 2017`.
  - **NEVER use ISO format (`YYYY-MM-DD`):** Belgian publishers and DDGS do not
    index dates as `1983-12-28` or `2017-10-02`; ISO dates produce zero hits.
  - If a natural Dutch date fails, try the hyphenated day-month-year form
    `02-10-2017` (e.g. `Wet 02-10-2017 private en bijzondere veiligheid`).

### 5. Simplifying long formal titles to substantive phrases
- Long legislative titles often contain date prepositions that vary between
  publishers (`Wet van 02 oktober 2017 tot regeling van...`).
- Simplify by separating the substantive title from the date:
  - Substantive title: `Wet tot regeling van de private en bijzondere veiligheid`.
  - Distinctive keywords + date: `2 oktober 2017 private veiligheid` or
    `Wet 02-10-2017 private en bijzondere veiligheid`.

## Staged retry strategy

Execute searches in three structured attempts, progressing from canonical title
to date/subject refinement to official identifiers:

| Attempt | Strategy | Purpose | Example |
|---|---|---|---|
| **Attempt 1** | **Clean canonical title** | Find the base instrument without citation noise or locators. Strip `De`/`Het`, omit articles/paragraphs. Quote stable multi-word titles. | `"Nieuwe Gemeentewet"`<br>`"Algemene Verordening Gegevensbescherming"`<br>`Wet tot regeling van de private en bijzondere veiligheid`<br>`Wet inzake overheidsopdrachten 17 juni 2016` |
| **Attempt 2** | **Disambiguating date or distinctive subject** | If Attempt 1 yields no hits or multiple amendments, refine with natural date or substantive domain terms. | `"28 december 1983" "sterke drank"`<br>`2 oktober 2017 private veiligheid`<br>`Verordening (EU) 2016/679`<br>`Richtlijn 2006/123/EG` |
| **Attempt 3** | **Official identifier or unquoted locator** | Use official CELEX or NUMAC identifier if extracted, or add an unquoted article locator if competing base acts exist. | `32016R0679`<br>`2016021053`<br>`"Nieuwe Gemeentewet" artikel 119` |

Do not repeat an unchanged query. A no-result response is evidence about that
query form only; retry with a shorter title, an unquoted variant, a natural
date form, an alias, or an identifier.

## Reference-specific examples

### Belgian federal legislation

1. **`De Nieuwe Gemeentewet, artikel 119`** (or `artikel 135, § 2`):
   - *Attempt 1:* `"Nieuwe Gemeentewet"` → Matches base act NUMAC 1988062450 at Rank 0.
   - *Do not do:* `"De Nieuwe Gemeentewet, artikel 119"` (0 hits) or
     `"De Nieuwe Gemeentewet" artikel 119` (0 hits).
   - Validate article 119 against the retrieved candidate text.

2. **`de Wet van 02 oktober 2017 tot regeling van de private en bijzondere veiligheid`**:
   - *Attempt 1:* `Wet tot regeling van de private en bijzondere veiligheid` → Matches NUMAC 2017031388 at Rank 0.
   - *Attempt 2:* `2 oktober 2017 private veiligheid` or `Wet 02-10-2017 private en bijzondere veiligheid`.
   - *Do not do:* Quoting the full title `"de Wet van 02 oktober 2017..."` (0 hits) or using ISO date `2017-10-02` (0 hits).

3. **`wet 28 december 1983`** (Liquor licensing / sterke drank):
   - *Attempt 1:* `"28 december 1983" "sterke drank"` (when domain/context mentions liquor) → Matches NUMAC 1983004493 at Rank 0.
   - *Attempt 2:* `wet 28 december 1983` (unquoted).
   - *Do not do:* `"wet 28 december 1983"` (0 hits).

4. **`De Wet van 24 juni 2013 betreffende de gemeentelijke administratieve sancties, artikel 2, § 1`**:
   - *Attempt 1:* `"Wet betreffende de gemeentelijke administratieve sancties"` → Matches NUMAC 2013000441 at Rank 0.
   - *Attempt 2:* `"Wet betreffende de gemeentelijke administratieve sancties" "24 juni 2013"`.
   - *Do not do:* Including `artikel 2, § 1` in the first query.

5. **`De wet inzake overheidsopdrachten van 17 juni 2016, artikel 42, §1, 1°d`**:
   - *Attempt 1:* `Wet inzake overheidsopdrachten 17 juni 2016` → Matches NUMAC 2016021053 at Rank 0.
   - *Do not do:* Quoting both phrases `"Wet inzake overheidsopdrachten" "17 juni 2016"` (0 hits) or including `artikel 42, §1, 1°d`.

6. **`artikel 19, tweede lid van de gecoördineerde wetten op de Raad van State`**:
   - *Attempt 1:* `gecoördineerde wetten op de Raad van State` or `"gecoördineerde wetten op de Raad van State"` → Matches NUMAC 1973011250.
   - *Do not do:* Quoting with `artikel 19, tweede lid` (0 hits).

7. **`De gecoördineerde Grondwet, artikel 26`**:
   - *Attempt 1:* `gecoördineerde Grondwet` or `Belgische Grondwet 17 februari 1994`.
   - *Do not do:* Including `artikel 26` in the discovery query.

### European Union legislation

1. **`De Algemene Verordening Gegevensbescherming`** (GDPR / AVG):
   - *Attempt 1:* `"Algemene Verordening Gegevensbescherming"` → Matches CELEX 32016R0679 at Rank 0.
   - *Attempt 2:* `Verordening (EU) 2016/679`.
   - *Attempt 3:* `32016R0679`.
   - *Do not do:* Unquoted `De Algemene Verordening Gegevensbescherming` (0 hits) or separated `EU 2016 679`.

2. **`Richtlijn 2006/123/EG betreffende diensten op de interne markt, artikel 15`**:
   - *Attempt 1:* `Richtlijn 2006/123/EG` or `"Richtlijn 2006/123/EG"` → Matches CELEX 32006L0123.
   - *Do not do:* Attaching `artikel 15` or long subject phrases to the directive query (0 hits).

## Evidence and validation

DDGS title and body snippet are the only evidence available in this version.
The validator must compare the candidate with the complete reference,
including article and paragraph locators, after discovery. Confirm the title,
instrument type, date or formal number, jurisdiction, and whether the result is
the base instrument rather than an amendment or a page that merely cites it.
Do not treat the first result as authoritative. A result from Remi is useful
fallback evidence, but an exact official Belgian or EUR-Lex result is preferred.

## IMPORTANT

- Prioritize authoritative official sources for the relevant legal level:
  - `ejustice.just.fgov.be` for Belgian federal legislation;
  - `eur-lex.europa.eu` for European Union legislation.
- `www.remi.legal` and other non-official sources may be used only as fallback
  or supplementary evidence when an official source is unavailable or
  insufficient.
- Use the URL of the accepted search result as the reference URL.
- When a `doc_id` can be reliably extracted:
  - For EU legislation, use the CELEX identifier from the `celex:` URI.
    Example:
    `https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=celex:32016R0679`
    → `32016R0679`.
  - For Belgian legislation, use the NUMAC code when available.
    Example:
    `https://www.remi.legal/nl/wetgeving/2017031388`
    → `2017031388`.
- If the `doc_id` cannot be reliably extracted, leave the field empty.

## Practical lessons

- `"Nieuwe Gemeentewet"` returned base law NUMAC `1988062450` at rank 0 on Remi;
  `"De Nieuwe Gemeentewet, artikel 119"` returned 0 hits, and
  `"De Nieuwe Gemeentewet"` returned only amending acts. Strip leading `De`
  and exclude article locators from the initial query.
- `Wet tot regeling van de private en bijzondere veiligheid` and
  `Wet 02-10-2017 private en bijzondere veiligheid` both returned the base act
  NUMAC `2017031388` at rank 0. Quoting the full reference or using ISO date
  `2017-10-02` returned 0 hits.
- `"28 december 1983" "sterke drank"` returned base liquor act NUMAC
  `1983004493` at rank 0; `"wet 28 december 1983"` returned 0 hits, and
  `"28 december 1983" wet` returned an unrelated budget act. For generic dated
  laws, include distinctive subject terms when known.
- `"Algemene Verordening Gegevensbescherming"` and `Verordening (EU) 2016/679`
  both returned CELEX `32016R0679` at rank 0.
- `Richtlijn 2006/123/EG` returned CELEX `32006L0123`; adding `artikel 15`
  returned 0 hits. Search the base directive first and validate the article
  from candidate text.
- `Wet inzake overheidsopdrachten 17 juni 2016` returned NUMAC `2016021053` at
  rank 0; overquoting both phrases `"Wet inzake overheidsopdrachten" "17 juni 2016"`
  returned 0 hits, and adding `artikel 42, §1, 1°d` returned only transposition
  n- 2026-09-24T11:00:20Z - For generic legal titles, combine jurisdiction and document type with multiple date formats and distinctive subject terms.- 2026-09-24T11:08:53Z - Bij een generieke instrumenttitel die veel verwijzende documenten oplevert, voeg in web_search de officiële juridische identifier of de volledige officiële titel toe.
- 2026-09-24T11:10:41Z - If an exact-title search returns no candidates, retry with the unquoted title and then search any identifier surfaced by the source.

otices rather than the base act.
- `gecoördineerde wetten op de Raad van State` returned NUMAC `1973011250` at
  rank 0; quoting the reference with `artikel 19, tweede lid` returned 0 hits.
ng 2016/679 artikel 32` and `32016R0679 artikel 32` returned no
  results in testing. Search the base EU act first and validate article 32
  afterward.
- 2026-09-28T08:38:09Z - Een generieke titelzoekopdracht kan vooral wijzigingsakten en verwijzingen opleveren; zoek daarnaast expliciet naar het officiële basisinstrument of de geconsolideerde tekst.
- 2026-09-28T10:22:45Z - Geef bij constitutionele zoekopdrachten voorrang aan de officiële geconsolideerde basistekst en filter afzonderlijke wijzigingsakten en loutere verwijzingen weg.
- 2026-09-28T12:49:22Z - Geef bij zoekopdrachten naar een geconsolideerde grondwet voorrang aan officiële corpusrecords waarvan de titel de grondwet zelf benoemt, en niet aan afzonderlijke wijzigingsakten die door artikelverwijzingen worden gevonden.
- 2026-09-28T12:54:51Z - For national legal texts, include the official publication date and prioritize the national consolidated-legislation database over generic web-result pages.
- 2026-09-28T14:22:04Z - Filter zoekresultaten die een rechtsinstrument slechts citeren expliciet uit wanneer de gevraagde bronakte zelf moet worden geïdentificeerd.
- 2026-09-28T14:22:36Z - Zoek Belgische koninklijke besluiten bij voorkeur in een officiële Belgische wetgevingsbron op de volledige titel en datum, en verifieer daarna afzonderlijk het identificatienummer en de aangehaalde artikeltekst.
- 2026-09-28T14:25:12Z - Geef voor Belgische binnenlandse regelgeving voorrang aan de officiële nationale wetgevingsdatabank boven algemene EU-rechtzoekmachines en verifieer steeds de volledige titel, het instrumenttype en de publicatiegegevens.
- 2026-09-28T14:52:46Z - For standards searches, query the designation together with “standard” and the issuing standards body rather than restricting results to legal regulations.
- 2026-09-28T15:02:43Z - When acronym-and-number searches produce legal-article false positives, add standards-specific terms and the relevant standards body's name.
- 2026-09-28T15:03:18Z - For references with national standard prefixes, search the relevant standards-body catalogue separately from general legal databases.
- 2026-09-28T15:09:04Z - For standards references, search national standards catalogues alongside general legal databases.
- 2026-09-28T15:10:20Z - When a standards query returns legal-gazette pages, verify whether each result is the standard record or merely an instrument adopting or citing the standard.
- 2026-09-28T15:20:03Z - Wanneer een titelzoekopdracht vooral wijzigingsinstrumenten oplevert, voeg een zoekterm toe die expliciet om de oorspronkelijke of geconsolideerde basistekst vraagt en verifieer het documenttype.
- 2026-09-28T15:24:01Z - For standards references, distinguish the standard publication from EU notices, guidance, or legal instruments that merely cite harmonised standards.
- 2026-09-28T15:33:34Z - For standards identifiers, search the relevant national or regional standards body's catalogue directly, since general web results may return legal notices that cite the standard rather than the standard record.
- 2026-09-28T15:37:49Z - For technical-standard queries, distinguish an official standards-catalog record for the standard itself from legal or regulatory documents that merely cite it.
- 2026-09-28T15:42:21Z - For standards references, prioritize results from the relevant standards body or standards catalogue and reject legal acts that only share a numeric identifier.
- 2026-09-28T16:02:23Z - For standards identified by an alphanumeric designation, prioritize standards-body catalogs and exact-identifier searches over general legal databases.
- 2026-09-28T16:06:10Z - For standards queries, search the national standards body's catalogue separately from legal databases to distinguish the base standard from EU notices that cite it.
- 2026-09-28T16:08:20Z - For standards references, distinguish the standard’s own official catalogue record from legal notices or harmonised-standard publications that merely list or cite it.
- 2026-09-28T16:11:42Z - When a query names a legal code, distinguish the original instrument from later amending acts that merely cite or modify it.
- 2026-09-28T16:12:08Z - Distinguish notices that reference harmonized standards from the national standards publication or adopted standard itself.
- 2026-09-28T16:14:26Z - When a standards query returns legal notices, search the relevant standards catalogue directly and treat EU harmonisation notices as citations rather than the standard itself.
- 2026-09-28T16:17:34Z - Bij onvolledige resultaten voor een exacte titel: herhaal de zoekopdracht met de datum, enkele onderscheidende titeltermen en het documenttype.
- 2026-09-28T16:19:14Z - Behandel jurisprudentieresultaten die een regeling citeren afzonderlijk van het officiële basisinstrument en zoek daarna expliciet op de documentsoort en datum.
- 2026-09-28T16:20:09Z - Prefer official title-field matches over full-text hits when a query term is a common legal shorthand.
- 2026-09-28T16:24:33Z - When searching for a standard, distinguish catalog records for the standard from legal notices that merely publish or cite harmonized standards.
- 2026-09-28T16:39:18Z - When legal-title searches return aggregator or unrelated results, prioritize records exposing the official title, enactment date, and consolidated-text metadata.
- 2026-09-28T16:40:07Z - Zoek bij een informele juridische titel ook op de formele titel en controleer expliciet of een resultaat het basisinstrument, een geconsolideerde tekst of slechts een wijzigingsdocument is.
- 2026-09-28T16:42:02Z - When searching legislation by date and subject, distinguish the base law from later amendment laws by verifying the enactment date and whether the title expressly states that it amends an earlier instrument.
- 2026-09-28T16:43:35Z - Zoek bij Nederlandstalige regelgeving naast de exacte titel ook naar gangbare varianten van de instrumentnaam, omdat webindexen het basisbesluit soms niet onder de aangeleverde titel tonen.
- 2026-09-28T16:44:40Z - Combineer bij Belgische KB-zoekopdrachten de volledige officiële titel met een verwijzing naar het Staatsblad en verifieer daarna de officiële identificatiepagina in plaats van alleen zoekresultaatsnippets te gebruiken.
- 2026-09-28T16:45:30Z - When title-and-date searches return legislative records, distinguish the base instrument from later amendments and documents that merely cite it.
- 2026-09-28T16:47:28Z - When a query names a statute by date, distinguish the statute itself from later amending acts and judicial documents that merely cite it.
- 2026-09-28T16:49:05Z - Wanneer zoekresultaten vooral wijzigingsakten opleveren, zoek de oorspronkelijke akte afzonderlijk op officieel documenttype en vaststellingsdatum.
- 2026-09-28T16:49:28Z - When date-based results mix base instruments with amendments, verify the official title and persistent identifier before selecting.
- 2026-09-28T16:50:18Z - When date-and-topic searches return amendment records, verify each record's own enactment date before selecting it.
- 2026-09-28T16:54:39Z - When the target may be a technical standard, search beyond regulation filters and verify results against the relevant standards publisher’s official catalogue.
- 2026-09-28T16:56:32Z - For standards identifiers, prioritize official standards-body catalogs and filter out legal databases and unrelated EUR-Lex results.
- 2026-09-28T16:57:20Z - Richt zoekopdrachten naar Belgische nationale regelgeving expliciet op de officiële Staatsblad- of overheidsdatabank wanneer algemene webzoekresultaten vooral EU-bronnen opleveren.
- 2026-09-28T16:57:39Z - Zoek voor Belgische omzendbrieven naast de afkorting ook op de vermoedelijke uitgevende overheidsdienst en controleer het documenttype afzonderlijk van de aangehaalde basiswet.
- 2026-09-28T16:59:06Z - When an identifier denotes a technical standard, search the issuing standards body's catalogue rather than relying on legal databases that only cite standards.
- 2026-09-28T16:59:35Z - Gebruik bij Belgische rechtsbronnen naast onderwerpstermen ook de exacte officiële titel en zoek specifiek in het Staatsblad op publicatiedatum of NUMAC-nummer.
- 2026-09-28T16:59:58Z - Gebruik bij brede webzoekopdrachten naast datum- en trefwoordzoekingen ook een exacte-titelzoeking, omdat algemene resultaten vaak ongerelateerde instrumenten opleveren.
- 2026-09-28T17:00:18Z - When exact-title results are dominated by amendments or case-law citations, search separately for the original publication record and exclude documents that merely cite the instrument.
- 2026-09-28T17:01:47Z - For standards identifiers, prioritize standards-catalogue records and exact identifier/title queries over general legal databases.
- 2026-09-28T17:02:25Z - Controleer bij exacte-titelzoekopdrachten eerst of het resultaat het basisinstrument is en niet slechts een artikel-, wijzigings- of citeerpagina.
- 2026-09-28T17:02:50Z - Geef bij Belgische wetgeving voorrang aan een officiële documentpagina met volledige titel, datum en NUMAC-identificatie boven algemene zoek- of archiefpagina’s.
- 2026-09-28T17:04:44Z - Geef bij Belgische wetgevingszoekopdrachten voorrang aan officiële Staatsbladrecords en controleer expliciet of een resultaat het basisinstrument is in plaats van een document dat het slechts citeert.
- 2026-09-28T17:06:31Z - Combineer bij nationale regelgeving een exacte titelzoekopdracht met de vermoedelijke officiële publicatiedatabase en sluit gelijknamige EU-speelgoedregelgeving expliciet uit.
- 2026-09-28T17:06:52Z - Wanneer een exacte titelzoekopdracht niets oplevert, herhaal de zoekactie met afzonderlijke termen voor documenttype, bevoegdheidsniveau en onderwerp, en controleer daarna de officiële publicatiebron.
- 2026-09-28T17:07:27Z - Controleer bij titelzoekopdrachten eerst de officiële titel en documentsoort; resultaten die de gezochte datum of tekst slechts citeren zijn geen bevestiging van het basisinstrument.
- 2026-09-28T17:08:05Z - When broad legal-name searches surface case-law pages, verify the result’s document kind before treating cited legislation as a candidate.
- 2026-09-28T19:05:52Z - When a query names a technical standard, prioritize standards-body catalogs and treat EU legal acts that cite the standard as non-matches.
- 2026-09-28T19:07:22Z - When exact-title searches return amendment acts, inspect the official source’s related or base-instrument record rather than treating amendment hits as the requested instrument.
- 2026-09-28T19:17:35Z - For standards references, distinguish the standard’s official catalogue record from EU notices or other documents that merely cite the standard.
- 2026-09-28T19:19:49Z - For standards queries, retain only results whose official title or metadata explicitly contains the standard designation or a clearly matching standards-document identity.
- 2026-09-28T19:27:32Z - For standards searches, query the issuing standards body’s catalog using the exact national designation and distinguish the base standard from EU notices that merely cite it.
- 2026-09-28T19:35:21Z - When searching for a technical standard, distinguish the standard’s official catalogue record from legal notices or harmonisation documents that merely cite it.
- 2026-09-28T19:43:16Z - Vraag bij juridische zoekopdrachten expliciet om het basisinstrument, omdat titel- en datumzoekopdrachten vaak wijzigingsakten of verwijzingen opleveren.
- 2026-09-28T19:45:17Z - For standards searches, verify that the result is the standard record itself rather than a legal act that merely cites the standard.
- 2026-09-28T19:58:19Z - Controleer bij zoekresultaten voor wetgeving eerst de officiële titel en documentsoort; zoek bij ruis op de onderscheidende onderwerpformulering in plaats van alleen op datum.
- 2026-09-28T20:00:36Z - Behandel treffers naar EU-rechtshandelingen die een technische norm slechts citeren niet als kandidaat voor de norm zelf; zoek daarnaast in de officiële catalogus van de nationale normalisatie-instelling.
- 2026-09-29T07:23:16Z - For national adoptions of European standards, search the relevant national standards body's catalogue directly rather than relying on general web results.
- 2026-09-29T07:56:41Z - For technical-standard references, search standards catalogs or standards-body sources in addition to general legal-text indexes.
- 2026-09-29T08:01:00Z - For standards identifiers, include the national standards body and standard title in the query, then prioritize standards-catalogue results over general legal databases.
- 2026-09-29T08:03:21Z - For standards searches, distinguish the standard record from legislation or EU notices that merely publish, cite, or list the standard.
