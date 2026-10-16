# Official federal and European web search

Use this source for Belgian federal instruments and European Union instruments
when the Vlaamse Codex does not cover the referenced legal level. Search only
official publisher pages returned from these exact HTTPS hosts:

- `ejustice.just.fgov.be` for Belgian federal legislation;
- `economie.fgov.be` for official FOD Economie legislation pages;
- `eur-lex.europa.eu` for European Union legislation;
- `www.remi.legal` for legal-reference results from Remi.

The adapter uses DDGS only for discovery. It sends one request per allowed host
with a query of the form `query site:host`; do not add `site:` expressions to
the tool argument.
For Belgian decrees and executive orders, the Belgian request is narrowed to
`site:ejustice.just.fgov.be/eli/besluit`, the official ELI path for decisions.
These searches use only eJustice and FOD Economie; EUR-Lex and Remi remain
available for searches without a Belgian decree/executive-order document type.
Returned URLs must still use HTTPS and one of the exact configured hosts.

DDGS title and body remain discovery evidence, and the adapter additionally
fetches each accepted HTTPS result from the allowlisted host. Fetching follows
redirects only after validating every destination against the same host
allowlist and rejecting private, loopback, and link-local addresses. Pages are
bounded and must be HTML; fetch or parse failures stay attached to the
candidate as `metadata.enrichment` and do not make an otherwise successful
discovery incomplete.

When available, enriched metadata includes `canonical_url`, `legal_source_url`,
`numac`, `celex`, `eur_lex_uri` for non-CELEX EUR-Lex identifiers such as
`NIM:...`, `page_title`, and publication-only `update_date`. URL-derived
identifiers are retained even when EUR-Lex returns an empty `202` response. The
`snippet`, title, URL, and URL-derived `doc_id` remain unchanged. A legal-source
identifier may fill an otherwise empty `doc_id`, but page titles and update
dates never become identifiers or enactment dates. Treat all evidence as
supporting validation evidence and remain unresolved or ambiguous when it
cannot uniquely identify the cited instrument. Never accept a result from
another host, an HTTP URL, a subdomain, or a page that merely cites the
instrument.

The optional document type narrows Belgian decree and executive-order
discovery to the official Justel ELI decision path. Refine the title or
identifier when useful, and treat an empty successful lookup separately from a
failed lookup.

## Query construction rules

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
  - `economie.fgov.be` for official FOD Economie legislation pages;
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

Add newly confirmed, valuable lessons here using `YYYY-MM-DDTHH:MM:SSZ - lesson`.

- 2026-08-01T12:19:38Z - Search the base instrument first and validate article locators afterward.
- 2026-08-01T12:19:38Z - Use distinctive subject terms with dates for generic legal titles.
- 2026-09-24T11:08:53Z - Add the official identifier or full title when a generic title returns referring documents.
- 2026-09-28T08:38:09Z - Distinguish the official base instrument or consolidated text from amendments and citations.
- 2026-09-28T14:52:46Z - Search standards in the relevant standards-body catalogue rather than relying on legal databases.
- 2026-09-28T16:24:33Z - Prefer official title-field matches over full-text hits for common legal shorthand.
- 2026-10-05T09:18:07Z - For Belgian legal acts, prioritize exact title-and-date searches in official national legal databases.
