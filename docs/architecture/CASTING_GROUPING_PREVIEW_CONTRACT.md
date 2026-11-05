# Casting Grouping Preview Contract

**Status:** read-only implementation proposal  
**Scope:** explicit source-context grouping proposals; no catalog identity changes

## Input

The pure preview accepts a list of record snapshots. Each record has a stable \`record_id\` and may include:

- \`release_id\`, \`sku\`, \`model_name\`, \`existing_casting_id\`;
- explicit \`product_line\` and \`catalog_year\`;
- \`collector_number_claims\`, preserving each claim's value, source record ID, and source field;
- \`source_record_ids\`.

The caller must provide product line explicitly. The current canonical Release model has no product-line field, so the preview must not infer it from a model name, SKU, or generic identifier namespace.

## Grouping behavior

The proposal key is:

\`(product_line, catalog_year, collector_number)\`

- Same explicit key, different SKUs or colors: one provisional group.
- Same name, different collector numbers: separate groups.
- Different years or product lines: separate groups.
- Missing product line/year/collector number, or conflicting collector-number claims within or across source snapshots for one Release: manual review.
- Multiple existing Casting IDs under one proposed key: conflict; no automatic merge.
- One existing Casting spanning multiple proposed keys: keep proposals separate and flag a split conflict.
- Model name is descriptive metadata only and is never a fallback key.

Collector number values are preserved as source strings, including leading zeroes. SKU remains Release-level information.

## Output and safety

The contract is \`hw_catalog.casting_grouping_preview\`, version 1. It returns proposed groups, record-level manual-review items, conflicts, reason codes, source provenance, and a summary.

Every response states \`mode=preview_only\` and \`writes_to_catalog=false\`. The core grouping module remains pure Python. A separate catalog adapter exposes `POST /castings/grouping-preview/from-catalog`: it reads Releases, linked SKU identifiers, and Release-linked `collector_number` Evidence using SELECT queries only. The request must supply `product_line` explicitly and may optionally filter by `catalog_year`. The adapter returns the same preview contract plus a `catalog_snapshot` summary. It performs no INSERT, UPDATE, DELETE, commit, migration, merge, split, or apply operation. Evidence outside the exact `collector_number` attribute is not treated as a Col.# claim.

## Validation cases

Tests cover same-number/different-SKU grouping, the Nissan Skyline HTC65 / Col.#191 versus HRY85 / Col.#213 split, year and product-line boundaries, missing and conflicting claims, existing-casting conflicts, input immutability, catalog-backed SKU/Evidence loading, missing-number review, and unchanged database row counts.
