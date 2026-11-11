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
- `identity_status`: `provisional`, `user_confirmed_same_casting`, `documented_distinct`
- `evidence_refs[]`: references to observations and sources
- `notes`

Do not merge records merely because names, Collector numbers or catalog groupings match. Do not split a casting for paint, tampo, wheels, base finish or packaging alone. Record genuine geometric/tooling differences as distinct castings.

### Release
A catalog appearance of a casting in a defined year and product line/series/assortment.

Suggested fields:
- `id`, `casting_id`
- `year`, `catalog_family` (Mainline, Premium, etc.)
- `series_name`, `series_raw`, `release_tags[]`, `exclusive`
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
The entity collections are initialized but empty. Existing `catalog-image-manifest.json` remains a research/reference manifest of externally hosted images; it is not the owned image asset registry.
