# Visual catalog · Pro Racing 1:43 pilot

## Filter reset behavior

The catalog toolbar shows removable chips for active local/global search queries and the selected record type or review status. The **«Сбросить всё»** action clears both search inputs, resets the type/status selectors to their default values, and returns the tree selection to **«Весь каталог»**.

The reset action is available whenever the visible catalog is narrowed by a tree selection, search query, record type, or review status—even if no search/type/status chip is present. When the full catalog is already shown with no active filters, the reset row stays hidden.

## Manual acceptance checklist

- Enter a local search query: an active chip appears; removing it clears only the local query.
- Enter a global search query: an active chip appears; removing it clears only the global query.
- Select a record type or review status: the matching chip appears and can be removed independently.
- Select one car or another nested item in the tree without using search/type/status filters: **«Сбросить всё»** is still visible and returns the full catalog.
- Combine several filters and click **«Сбросить всё»**: all search inputs and type/status selectors reset, the tree returns to **«Весь каталог»**, and all cards are shown.
- With the full catalog selected and no active search/type/status filters, the active-filter row remains hidden.
- Confirm that the **«Весь каталог»** tree item still performs navigation independently.

The deployed page reads the read-only export generated from the Pro Racing 1:43 SQLite pilot in `JohnyKiska/hotwheels-fandom-archive`. Synthetic demo cards have been removed. The page currently shows 41 source rows and 55 visually inspected Gallery images. It intentionally shows 0 fully verified canonical product releases; inspected images and probable group matches are not product identities. Editing and write-back are not enabled.
