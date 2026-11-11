# HW Catalog: canonical data model

## Purpose
Build a durable, independently maintainable catalog. Public wikis, marketplaces and other catalogs are research sources, not the canonical database and not required at runtime.

## Core entities

### Casting
A physical tooling identity. It represents the mould/tooling, not a colorway or retail release. A casting may have many releases over many years and lines.

Suggested fields:
- `id`: permanent internal ID (opaque, never derived from a mutable model name)
- `canonical_name`
- `manufacturer`, `casting_number` (when known)
- `identity_status`: `provisional`, `user_confirmed_same_casting`, `documented_distinct`, `unreviewed_single_entry`
- `evidence_refs[]`: references to observations and sources
- `notes`

Do not merge records merely because names, Collector numbers or catalog groupings match. Do not split a casting for paint, tampo, wheels, base finish or packaging alone. Record genuine geometric/tooling differences as distinct castings.

### Release
A catalog appearance of a casting in a defined year and product line/series/assortment.

Suggested fields:
- `id`, `casting_id`
- `year`, `catalog_family` (Mainline, Premium, etc.)
- `series_name` (normalized series label), `series_raw` (unaltered source label), `series_normalization_status`, `release_tags[]`, `exclusive` (retailer or distribution channel when known)
- `toy_number`, `collector_number`, `assortment`, `country_of_origin`
- `source_refs[]`

Keep source identifiers and raw strings. A release is not the same thing as a casting.

### Variant
A documented physical/decorative configuration within a release.

Suggested fields:
- `id`, `release_id`
- `variant_label` (First listed, 2nd Color, etc.)
- `color`, `tampo`, `wheel_type`, `window_color`, `interior_color`, `base_finish`
- `observed_differences[]`, `evidence_refs[]`

Do not infer a new casting from a variant difference.

### Image asset
A file that HW Catalog owns or is licensed/authorized to store and serve.

Suggested fields:
- `id`, `file_path`, `mime_type`, `width`, `height`, `sha256`
- `creator`, `source`, `rights_status`, `license`, `permission_reference`
- `review_status`, `view_angle`, `photographed_at`
- `release_ids[]`, `variant_ids[]`

Only first-party or explicitly authorized files belong in the local image store. A remote URL alone is a source reference, not a locally owned asset.

## Evidence and provenance
Every imported fact should retain provenance where possible: source URL, source title, retrieval date, source record/file, and the exact raw value. User physical inspection should be recorded distinctly from catalog-derived evidence. Keep disagreements visible instead of silently choosing one source.

## Stable IDs and relationships
- IDs are permanent opaque identifiers, for example `cst_...`, `rel_...`, `var_...`, `img_...`.
- Never use a model name, year, Toy # or Collector # as the sole primary key.
- One casting can have many releases; one release can have many variants; one image can document one or more releases/variants.
- External catalog records map to internal IDs through explicit cross-reference records, not by making an external site the primary key.

## Migration strategy
1. Keep current generated all-years index as a discovery/search layer.
2. Introduce canonical entity collections in `catalog/data/`.
3. Import records with source provenance and provisional identity; do not auto-merge casting identities.
4. Add reviewed first-party photos to `catalog/images/` and register them in `images.json`.
5. Update the explorer to read canonical data while retaining the generated index as a fallback during migration.

## Current status
Canonical entity collections are populated for Mainline 2026: 250 casting candidates, 440 releases, and 440 variants. Casting identity retains its evidence-based review status. Release series labels and recognized release tags have been normalized from the preserved raw source labels. Existing `catalog-image-manifest.json` remains a research/reference manifest of externally hosted images; it is not the owned image asset registry.


## Series and release-label normalization

For imported Mainline 2026 releases, `series_raw` is preserved exactly as received. `series_name` contains the base series after deterministic removal of recognized suffixes. `series_normalization_status: "normalized_from_source_label"` means the label was parsed from the source string; it is not an independently verified official taxonomy.

Recognized `release_tags` currently include:
- `new_for_2026`
- `new_in_mainline`
- `treasure_hunt`
- `super_treasure_hunt`
- event tags prefixed with `event_` (for example, `event_world_braille_day` and `event_easterseals`)

Recognized retailer values in `exclusive` currently include `Target`, `Walmart`, `Kroger`, `Dollar General`, and `Dollar Tree/Family Dollar`. A retailer suffix is separated from the base series and any release tags. These values are copied from the source label, not independently proof-checked against packaging or retailer documentation. Unknown suffixes must remain in `series_raw` and must not be silently discarded.

Normalization does not alter `casting_id`, variant identity, model names, source references, Toy numbers, or Collector numbers. It must never be used as evidence that two releases share a physical casting.

## Photo evidence priority

For product documentation and catalog research, prioritize photographs of the **carded/blistered product** over loose-car photographs. Packaging is part of the collectible product and contributes to its presentation and collector value, so blistered photos should be the primary image reference whenever available. Loose-car photos are secondary/supplementary evidence, especially useful for close inspection of casting geometry, base details, wheels, and tampo. Record the view angle and whether the item is carded or loose; do not treat a loose-car image as a substitute for missing packaging evidence.


## Packaging variants and source-identifier suffixes

Packaging is tracked independently from casting identity and from the car's decorative/mechanical variant. When the same release/model is documented with different blister or card formats (for example, tall and short blisters), retain both as distinct packaging observations/variants rather than selecting one as canonical or treating the difference as a new casting.

Preserve every source article/SKU identifier exactly as published, including all suffixes. Never strip, overwrite, or normalize away a suffix during import or matching. Store the full raw identifier and, where useful, parse a base identifier and suffix into additional fields without losing the original string. Different suffixes are evidence of distinct catalog/article records, but do not by themselves prove a different casting or even a packaging difference; verify the physical packaging from photographs or reliable documentation.

For photo research, seek and prioritize carded/blistered images for each identifier/packaging variant. Keep the tall/short blister observations and their evidence links separately associated with the relevant release/article identifier. Loose-car photos remain supplementary.


## Packaging reverse-side evidence and article suffix history

For blister/card packaging research, retain reverse-side (card-back) photographs as first-class evidence alongside front-facing blister photographs. The reverse can carry article/SKU identifiers and suffixes, distribution or packaging codes, and other clues needed to reconstruct packaging changes over time.

Preserve the complete identifier exactly as printed or published, and associate it with the specific packaging observation (for example, tall blister versus short blister). Do not collapse records that differ by suffix. Use front and reverse views together where available to trace the chronology and logic of packaging formats. A suffix is a traceable clue, not proof on its own: correlate it with visible packaging dimensions/features and reliable source documentation.
