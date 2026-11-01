# Fandom Mainline 2025 pilot

**Status:** first live import and comparison completed. Review-only; no catalog records were changed.

## Run

- GitHub Actions: https://github.com/JohnyKiska/hotwheels/actions/runs/41280330299
- Source: https://hotwheels.fandom.com/wiki/List_of_2025_Hot_Wheels
- Local comparison corpus: six saved 2025 All Hot Wheels HTML pages in `ALLHW/`.

## Import result

| Metric | Result |
| --- | ---: |
| Fandom rows imported | 440 |
| Unique collector numbers | 250 |
| Repeated Toy # values | 0 |
| Local AllHW pages matched | 6 |
| Fandom rows without a saved local page | 434 |
| Ambiguous SKU matches | 0 |
| Unreadable AllHW pages | 0 |

The 440 rows represent 250 collector numbers plus color and other listed variants. The importer preserved model-cell annotations such as second/third color and Zamac, and series-cell annotations such as New for 2025, Treasure Hunt, Super Treasure Hunt, and store exclusives.

## Comparison result

Five fields are checked for each matched SKU: model name, release year, collector number vs AllHW Mainline #, series name, and series number vs AllHW Series index.

Five of the six matched pages agree on all five fields. One series-name discrepancy was found:

| SKU | Fandom series | AllHW series | Result |
| --- | --- | --- | --- |
| JBC25 | HW J-Imports | HW J-IMPORT | Conflict; manual review |

This discrepancy is preserved as a source conflict. Do not normalize or overwrite either value automatically.

## Important interpretation

- 434 unmatched rows do not indicate importer failures. The local ALLHW folder contains only six 2025 HTML pages, so the other Fandom rows have no local page to compare yet.
- No repeated Toy # values were found in this Fandom snapshot.
- Collector number is a grouping field, not a release identity key. Color variants remain separate rows.
- The generated JSON and comparison report are available as the `fandom-mainline-2025-review` artifact attached to the GitHub Actions run above.
- The workflow is read-only with respect to the project catalog.

## Next steps

1. Review the JBC25 series-name discrepancy against the source pages.
2. Add more 2025 AllHW pages and rerun the comparison to increase coverage.
3. Review annotation extraction against a sample of color variants, Treasure Hunts, Super Treasure Hunts, and exclusives.
4. Only after review, define any controlled merge or promotion process into the catalog.
