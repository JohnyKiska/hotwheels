# Casting Identity and Grouping Rules

**Status:** proposed matching rule; documentation and audit only  
**Scope validated:** 2024 Hot Wheels Mainline export  
**Implementation status:** not yet applied to catalog records or importer persistence

## 1. Core distinction

The catalog must keep these concepts separate:

- **Model name**: the displayed/source-provided model name. It is not a unique identity key.
- **Release**: one particular catalog-year product occurrence, identified by its own SKU and other release-level facts.
- **Casting**: the physical die-cast construction/tooling identity. Different constructions may share the same model name.
- **Collector number (Col.#)**: a numbering value within a particular catalog context. It is a useful grouping signal, not a globally stable Casting ID.

A repeated name must never, by itself, merge Releases into one Casting.

## 2. Proposed conservative grouping key

For a source that explicitly provides a collector number, use this key for a **provisional grouping proposal**:

`(product_line, catalog_year, collector_number)`

Rules:

1. Same product line + same catalog year + same non-empty collector number: propose the same provisional Casting group.
2. Same name but different collector numbers in that context: propose separate Casting groups.
3. Different product lines or catalog years: do not group based on collector number alone.
4. Missing, malformed, or conflicting collector numbers: leave ungrouped and require review.
5. SKU identifies a Release candidate; it is not the Casting grouping key.
6. Model name is descriptive/searchable metadata, never a fallback grouping key.
7. A grouping proposal is not a confirmation. Preserve provenance and require review before applying identity changes.

The rule is intentionally conservative. It must not silently merge records when context or numbering evidence is incomplete.

## 3. Important namespace separation

Do not silently map Fandom `Col.#` to a generic `catalog_number` identifier namespace unless that namespace is explicitly defined for the same numbering system and context.

Keep the source claim identifiable as `collector_number` (or an equally explicit typed field/identifier). Do not conflate it with:
- assortment number;
- SKU / Toy #;
- a generic catalog number from another product line;
- Mainline # unless the source explicitly establishes that equivalence for the relevant year.

The current Mainline HTML parser already preserves Fandom `Col.#` as `collector_number` and documents that it is not an assortment number. Any future matching layer should retain that distinction.

## 4. 2024 Mainline audit

The read-only `mainline_2024_export.json` was independently analyzed by following each Release's Evidence link to its SourceRecord and reading the captured `raw_data.collector_number`.

| Measure | Result |
|---|---:|
| Releases | 441 |
| Existing Casting groups | 249 |
| Distinct non-empty collector numbers | 250 |
| Existing Casting groups containing multiple collector numbers | 1 |
| Collector numbers assigned to multiple existing Casting groups | 0 |
| Releases in the identified cross-number group | 2 |

The sole cross-number group is:

| SKU | Col.# | Source model name | Existing Casting |
|---|---:|---|---|
| HTC65 | 191 | Nissan Skyline 2000GT-R LBWK | Nissan Skyline 2000GT-R LBWK |
| HRY85 | 213 | Nissan Skyline 2000GT-R LBWK | Nissan Skyline 2000GT-R LBWK |

Under the proposed key, these become two provisional Casting groups while retaining the same displayed model name.

For this 2024 Mainline dataset, applying the key yields **250 provisional groups instead of 249 existing name-based groups**. All 250 collector numbers currently map to exactly one existing Casting group; one existing group incorrectly spans two numbers. This is a dataset-specific audit result, not proof that collector number alone is universally sufficient across all years or product lines.

## 5. Data model and implementation guardrails

The current model defines Casting as an identity independent of a particular year's Release. Therefore, do not permanently identify a Casting by a year-scoped collector number. Treat the key above as a **source-context grouping proposal** for the relevant Mainline year.

Before implementing persistence or changing existing rows:

- confirm how product line is represented on Release/source observations;
- add or use an explicitly typed collector-number claim without reusing an ambiguous identifier namespace;
- produce an explainable, read-only grouping preview;
- show the proposed group key and all contributing Release/SKU/source records;
- report conflicts (same key with incompatible evidence, or different keys currently sharing one Casting);
- preserve existing IDs and provenance in any later migration;
- require explicit review/apply before changing canonical Casting relationships.

No database migration, merge, split, or record mutation is authorized by this document.

## 6. Acceptance tests for a future grouping preview

1. Same year, same product line, same collector number, different SKUs and colors -> one provisional group.
2. Same year and product line, different collector numbers, same model name -> separate provisional groups.
3. Same collector number in different years -> separate proposals unless a separate cross-year identity rule is supported.
4. Same collector number in different product lines -> separate proposals.
5. Missing collector number -> ungrouped/manual review; never fall back to name.
6. Conflicting collector-number claims for one Release -> conflict/manual review.
7. Duplicate SKU or source replay -> preserve as a Release/source matching concern; do not merge Casting.
8. Preview is read-only and reports `writes_to_catalog: false`.
9. The 2024 fixture reproduces the Nissan Skyline split: HTC65 / 191 and HRY85 / 213.
10. Applying a reviewed split must preserve Release IDs, SKU identifiers, Evidence, SourceRecords, and series links.

## 7. Current implementation boundary

The active `backend/app/importers/mainline.py` parser is read-only and emits source observations. The active `backend/app/importers/matcher.py` matches import observations to Release candidates using source replay, identifiers, and exact name/year signals; it does not create or merge Casting entities.

Consequently, this rule belongs in a future explainable Casting-grouping preview stage, not as a quick change to the existing Release matcher. The current 2024 export remains unchanged.
