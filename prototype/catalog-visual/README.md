# Visual catalog prototype

## Filter reset behavior

The catalog toolbar shows removable chips for active local/global search queries and the selected record type or review status. The **«Сбросить всё»** action clears both search inputs and resets the type/status selectors to their default values.

Resetting filters deliberately preserves the current catalog-tree section. **«Весь каталог»** remains a separate navigation action that changes the current section.

## Manual acceptance checklist

- Enter a local search query: an active chip appears; removing it clears only the local query.
- Enter a global search query: an active chip appears; removing it clears only the global query.
- Select a record type or review status: the matching chip appears and can be removed independently.
- Combine several filters and click **«Сбросить всё»**: all search inputs and type/status selectors reset, the full list for the current tree section returns, and the active chips disappear.
- With no active search or type/status filters, the active-filter row remains hidden.
- Confirm that the **«Весь каталог»** tree item still performs navigation and is not required merely to reset filters.

This is a visual prototype; changes to demo records are not persisted to a backend.
