# Catalog enrichment from saved source pages

The first enrichment prototype works offline on HTML pages saved by the user. It does **not** fetch the internet and does **not** overwrite `collection.json`.

## Run locally

1. Install Python dependencies: `python -m pip install -r requirements.txt`
2. Put saved All Hot Wheels model pages in a folder, for example `saved_pages/`.
3. Run:
   `python scripts/enrich_catalog_from_html.py --html-dir saved_pages --output enrichment-preview.json`
4. Review the preview before any merge.

The prototype matches records by the catalog's `toyNum` and records the canonical source URL, release year, scale, wheel description, and raw color attributes where available. Missing data remains missing. Ambiguous or unmatched records are not silently matched.

## Limits

- The source page's HTML structure may change; parser tests must be kept current.
- A saved page may contain related-car sections; the current parser uses the main page's SKU and the first Wheels/Colors sections, but large-scale validation is still required.
- A field's source label and value are preserved as attributes; they should not be collapsed into a guessed color name.
- Live downloading is not implemented. Confirm the source's terms and permitted access method before adding a scheduled fetcher.
- Existing IDs are known to contain duplicates. Do not use the legacy `id` field as the sole merge key; SKU is used for the initial match and a separate ID repair should be reviewed.
