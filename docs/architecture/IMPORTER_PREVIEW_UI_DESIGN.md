# Importer Preview UI Design

**Status:** Draft, implementation not yet authorized  
**Branch:** `feature/live-casting-grouping-review`  
**Scope:** New standalone `importer-preview.html`; the existing `importer.html` remains untouched.

## 1. Purpose

Provide a browser interface for inspecting source files, reviewing parser output, matching individual observations to catalog Releases, and comparing source claims with a manually selected Release.

The interface is a review tool only. It must not create or modify Castings, Releases, identifiers, Sources, SourceRecords, Evidence, Conflicts, or review decisions.

## 2. Design principles

1. Preserve source values and provenance. Never silently normalize away meaningful source terminology.
2. Keep every parsed row visible, including duplicates and rows with warnings.
3. A matcher candidate is a suggestion, not an accepted identity.
4. Never auto-select a Release for comparison.
5. A claim diff is informational. Suggested actions are not executable actions.
6. Make the read-only boundary visible in the UI.
7. Use same-origin relative API paths. Do not add a configurable arbitrary backend URL or broaden CORS.
8. Do not fetch source pages from the browser. The user supplies saved HTML/TSV files.

## 3. Page structure

A single page with three sequential work areas:

### Step A — Source

Source selector:
- Mainline TSV
- Fandom yearly HTML
- All Hot Wheels individual model HTML

Inputs:
- File picker accepting `.txt`, `.tsv`, and `.html` as appropriate.
- Mainline TSV and Fandom require a catalog year.
- All Hot Wheels optionally accepts an expected release year.
- Show the selected filename and file size.
- Read file contents locally with the browser File API; do not upload to a storage service.

Primary action: **Parse source**.

### Step B — Parser results

Show summary values:
- records found;
- errors;
- warnings;
- ready-for-review state.

Show source metadata when available:
- source title;
- canonical source URL;
- detected Mainline numbering statement and total.

Render all records in a selectable table. Suggested columns:
- source row;
- Toy Number / SKU;
- model name;
- catalog year or release year;
- assortment number;
- collector number;
- series and series position;
- rarity / special label;
- parser row status.

The exact visible columns may vary by source. Do not label Fandom `Col.#` as an assortment number.

Show parser issues in a separate list with severity, code, message, and source row. Link an issue to its row where possible. Duplicate Toy Numbers remain separate rows; display duplicate warnings without collapsing records.

Selecting a row advances to Step C. Keep the source and parsed result in page memory so the user can inspect multiple records without reloading the file.

### Step C — Record review

Show the selected record's:
- normalized observation claims;
- subject hints;
- identifier hints;
- raw source values and source-field mapping;
- raw text / source row where available.

Show matcher output:
- status;
- candidate Releases;
- candidate Casting and Release names/years;
- matching signals and explanations;
- contradictions / identifier collisions;
- ignored identifier hints and reasons.

Provide a separate manual Release search. The user must explicitly choose a Release before requesting a claim diff. A matcher candidate may be offered as a convenient search result, but must never be selected automatically.

After explicit selection, show the Release snapshot and claim diff:
- attribute;
- incoming value;
- raw value;
- source field;
- existing value;
- status;
- reason;
- suggested action.

Render statuses distinctly: `same`, `new_evidence`, `conflicting_value`, `insufficient_evidence`, and `evidence_only`.

No Apply, Save, Confirm, Merge, Resolve, or equivalent write action is part of this page.

## 4. API contracts

All requests use same-origin relative paths.

### 4.1 Initial parser preview

Use one source-specific endpoint to parse the complete file and populate Step B.

| Source | Method and path | Request body |
|---|---|---|
| Mainline TSV | `POST /imports/mainline/preview` | `{ "text": string, "catalog_year": integer }` |
| Fandom yearly HTML | `POST /imports/mainline/fandom-html-preview` | `{ "text": string, "catalog_year": integer }` |
| All Hot Wheels HTML | `POST /imports/all-hot-wheels/html-preview` | `{ "text": string, "expected_year": integer | null }` |

The parser response includes `records`, `issues`, and `summary`, plus source-specific metadata. The UI must tolerate optional fields and render source-specific columns without assuming every source provides every attribute.

Validation constraints currently enforced by the API:
- Mainline/Fandom text: 1 to 2,000,000 characters for HTML; Mainline TSV has a 500,000-character limit.
- All Hot Wheels expected year, when supplied: 1968–2100.
- Mainline/Fandom catalog year: 1968–2100.

### 4.2 Selected record pipeline preview

When a user selects a row, call:

`POST /imports/preview`

Request:
```json
{
  "source": "mainline_tsv",
  "text": "<original file text>",
  "catalog_year": 2026,
  "record_index": 0
}
```

Allowed `source` values:
- `mainline_tsv`
- `fandom_html`
- `all_hot_wheels_html`

For Mainline TSV and Fandom, `catalog_year` is required. For All Hot Wheels, `catalog_year` must be omitted or null and `expected_year` may be supplied. `record_index` is zero-based and defaults to 0.

To obtain a diff, send `selected_release_id` only after explicit user selection. Without it, `claim_diff` and `selected_release` are null.

Response contract:
- `contract`: `hw_catalog.import_pipeline_preview`
- `contract_version`: 1
- `mode`: `preview_only`
- `writes_to_catalog`: false
- `source`
- `parser_summary`
- `parser_issues`
- `record_index`
- `records_available`
- `observation`
- `matching`
- `selected_release`
- `claim_diff`

The original file text is sent again because the pipeline endpoint parses the source itself. Do not attempt to construct or alter an Observation in browser code.

### 4.3 Manual Release search

Use:

`GET /catalog/admin/releases?q={encoded_query}&catalog_year={optional_year}&limit=50&offset=0`

The endpoint is read-only and returns `total`, `items`, `limit`, and `offset`. Search covers Release name, Casting name, Release ID, identifiers, and series. Each item includes Release ID, name, catalog year, status, Casting identity, assortment number, identifiers, series, and evidence count.

Debounce search input. Use pagination when `total` exceeds the current page. Do not auto-select the first result.

Optional detail request after explicit selection:

`GET /catalog/admin/releases/{release_id}`

Use this only if the UI needs additional detail beyond the Release search result and pipeline response. It is read-only.

## 5. Source-specific display cautions

### Mainline TSV
- Expected row structure: Toy Number, assortment/catalog number, model name, optional series.
- Continuation lines may contain series fractions, TH/Exclusive markers, or notes.
- Duplicate Toy Numbers are retained as separate records and reported as warnings.

### Fandom yearly HTML
- Parse the saved yearly page's primary sortable wikitable.
- Required columns: `Toy #`, `Col.#`, `Model Name`, `Series`, `Series #`.
- `Col.#` is represented as `collector_number`, not assortment number.
- Mainline number is inferred from Col.# only when the page itself contains an explicit yearly statement that Mainline is numbered from X through Y.
- Preserve canonical source URL, raw cell values, and source-field provenance.

### All Hot Wheels individual HTML
- Parse one saved model detail page.
- SKU is a source identifier hint; it is not assumed to be a globally unique source-record ID.
- Preserve the source's special-label wording, including `chase`; do not translate it into TH/STH.
- Display release year separately from catalog year. The parser does not infer catalog year for this source.
- Preserve category, series position, scale, base material, wheels, colors, tags, and raw source values when present.

## 6. Error and loading states

- Disable duplicate submissions while a request is in progress.
- Show API validation errors (422) next to the source controls, preserving the selected file.
- Show 404 for a Release that is no longer available and clear the stale selection.
- Show network/server failures without discarding parser results already displayed.
- If the selected record index is out of range, refresh the parser preview rather than guessing a replacement index.
- Clearly distinguish parser errors from warnings. A parser error does not authorize hiding the affected record.

## 7. Visual direction

Use the existing `admin-live.html` as a visual reference:
- compact system typography;
- neutral page background and restrained cards;
- readable tables with sticky or clearly repeated headers where useful;
- a clear selected-row state;
- responsive layout that stacks the record details on narrow screens.

Do not copy review-session controls, localStorage session persistence, conflict-resolution actions, or any write-capable behavior from the existing admin page.

## 8. Security and deployment boundary

The page must use relative same-origin API calls. Do not introduce:
- user-configurable arbitrary API origins;
- permissive CORS;
- public unauthenticated access to write-capable backend endpoints;
- browser-side fetching of Fandom or All Hot Wheels pages.

Backend deployment, persistent database hosting, authentication/authorization, and allowed origins must be designed before remote browser integration. Until then, local same-origin use is the intended integration target.

## 9. Acceptance criteria

1. Each of the three source formats can be selected and parsed through its documented parser endpoint.
2. The complete parser record list, summary, and issues are visible.
3. Duplicate rows remain distinct and visible.
4. Selecting a record calls the shared pipeline with the correct source, original text, year fields, and zero-based index.
5. Matching signals, contradictions, and ignored identifier hints are visible.
6. Release search is read-only and supports manual selection.
7. No claim diff is requested until the user explicitly selects a Release.
8. The diff displays all returned claims and statuses without applying suggested actions.
9. No catalog write endpoint is called by the page.
10. Existing `importer.html` remains unchanged.
11. All API calls use relative same-origin paths.
12. Tests/manual verification confirm the page handles API errors without losing the loaded source.

## 10. Out of scope

- Persisting import jobs or parser previews.
- Creating Sources or SourceRecords.
- Saving Evidence or identifiers.
- Applying claim diffs.
- Resolving conflicts or merging Castings.
- User authentication implementation.
- Remote deployment configuration.
- Bulk import or automated acceptance.
