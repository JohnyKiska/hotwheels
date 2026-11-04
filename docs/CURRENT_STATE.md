# HW Catalog · текущее состояние

Дата синхронизации: 2026-11-04.

## Выполнено в текущем цикле

1. Создана ветка `integration/catalog-foundation` от `prototype/catalog-visual-v1`.
2. Создана архивная ветка `archive/gemini-main-2026-11-04` от прежнего `main`. Архивная ветка пока только сохраняет исходное состояние и не очищалась.
3. В `integration/catalog-foundation` визуальный каталог из `prototype/catalog-visual/index.html` скопирован в корневой `index.html`.
4. Файл редактора схемы скопирован в корень как `schema-editor.html`.
5. Исходная папка `prototype/catalog-visual/` сохранена без удаления.
6. `catalog/editor.html` оставлен как справочный источник механики drag & drop. Сам drag & drop в новый интерфейс пока не переносился.
7. Добавлена документация проекта и правила дальнейшей консолидации.

## Подтверждённые ограничения текущего интерфейса

- Корневая страница теперь использует визуальный каталог из prototype.
- В README прототипа указано, что изменения демонстрационных записей не сохраняются в backend.
- Новый интерфейс пока не подключён к постоянному хранилищу/API.
- Drag & drop требует отдельной адаптации и тестирования.
- Перенос файлов в корень сделан только в интеграционной ветке. `main` не изменён.

## Важные источники для следующего аудита

- `prototype/catalog-visual-v1`: актуальный визуальный каталог и его последние правки.
- `main`: прежний проект и потенциальные backend/инфраструктурные наработки. Не считать весь branch актуальным, но и не удалять без проверки.
- `feature/scheduled-market-data`: папка `ALLHW` и связанные импортеры/эксперименты. Ветка diverged относительно main, целиком не сливать.
- `catalog/editor.html` из старого main: источник drag & drop, не источник новой страницы.

## Не выполнено

- Перенос и адаптация drag & drop.
- Аудит различий между `prototype/catalog-visual-v1`, `main` и backend-наработками.
- Аудит и выборочный перенос `ALLHW`.
- Проверка данных каталога и привязок к канонической модели Casting/Release.
- Полный прогон тестов в итоговой интеграционной ветке.
- Подготовка PR в `main`.

## Git-состояние

- Рабочая ветка: `integration/catalog-foundation`.
- Базовая ветка: `prototype/catalog-visual-v1`.
- Архивная ветка: `archive/gemini-main-2026-11-04`.
- `main` не изменён.


## Синхронизация веток и архивирование · 2026-11-04

- Проверен полный список веток репозитория.
- Созданы 82 архивные копии исторических веток по схеме `archive/2026-11-04/<исходное-имя-ветки>`.
- Проверены совпадения SHA между архивными копиями и оригиналами: пропусков и несовпадений не обнаружено.
- Рабочие ветки `prototype/catalog-visual-v1` и `integration/catalog-foundation` не изменялись.
- На контрольной проверке 2026-11-04 HEAD `main` — `b315431d279c42d94a76766d89dd18187278039c`; текущая работа не направляла коммиты в `main`. Важно: `archive/gemini-main-2026-11-04` не совпадает с текущим `main` (GitHub compare показывает diverged: 29 commits ahead / 90 behind относительно merge base). Архив — исторический ref, не зеркало актуального `main`.
- Исторические исходные refs пока сохранены; физическое удаление/переименование веток не выполнялось.
- Default branch остаётся `main`, GitHub Pages не переключался.

## Проверка запуска визуального прототипа

- Корневой `index.html` содержит встроенные CSS и JavaScript.
- Внешние CSS/JS-зависимости не обнаружены.
- В коде страницы не обнаружены вызовы backend fetch, localStorage или IndexedDB.
- Для первичного визуального теста достаточно статического HTTP-сервера.
- Это не проверка backend: постоянное хранение и API пока не подключены.

Команда запуска из корня репозитория в PowerShell: `py -m http.server 8000`. Затем открыть `http://localhost:8000/`.

## Backend: выборочный перенос идентификаторов и конфликтов · 2026-11-04

- Подготовлена ветка `integration/import-idempotency-conflict-traceability` от `integration/catalog-foundation`.
- Открыт draft PR #80: https://github.com/JohnyKiska/hotwheels/pull/80. Он не смержен.
- Перенесена идемпотентность Evidence из PR #72: одинаковое нормализованное утверждение одного SourceRecord повторно использует Evidence; другой SourceRecord создаёт отдельное наблюдение.
- Перенесена traceability конфликтов из PR #73: `ConflictRelease`, релевантные ConflictEvidence, Release в очереди и деталях, история решений и endpoint пересмотра.
- Добавлена миграция `20261104_conflict_releases`, совместимая с текущей цепочкой integration и безопасная при уже созданной ORM таблице.
- Обновлена страница `catalog/conflicts.html`.
- GitHub Actions на HEAD `a44c17abed1319162b08ad3a332dd66ebf9d36ff`: backend `92 passed`, 4 warnings; Catalog UI checks success.
- PR #80 mergeable и остаётся draft до отдельной проверки/согласования. `integration/catalog-foundation` и `main` не изменялись.

## Read-only importers restored · 2026-11-04

- PR #80 has been merged into `integration/catalog-foundation` (merge commit `c5909c995eb17b16af80710eb1d10849cafd9b9a`).
- A follow-up working branch `integration/importers-safe-preview` was created from that integration head.
- Selectively restored the non-writing Mainline TSV parser, local Fandom yearly HTML parser, and All Hot Wheels saved-card HTML parser from PR #74.
- Added three preview-only API endpoints: `/imports/mainline/preview`, `/imports/mainline/fandom-html-preview`, and `/imports/all-hot-wheels/html-preview`.
- Added synthetic parser and API tests. No database writes, network fetcher, scheduler, matching, candidate persistence, or apply flow were added.
- Preserved Mainline importer specification, synthetic fixture set/test plan, and All Hot Wheels importer notes.
- Fandom HTML is accepted only as user-provided/local content. No network request to Fandom is made.
- Deliberately did not port PR #74's catalog-tree API, extra ORM models, or its migration chain. In particular, the legacy `20261030_core_schema.py` / `create_all()` approach is not imported.
- GitHub Actions run #179 completed successfully on the importer code: `113 passed`, 4 warnings. The final documentation-only follow-up did not change backend code.

## Integration cleanup checkpoint · 2026-11-04

- PR #80 merged: `c5909c995eb17b16af80710eb1d10849cafd9b9a`.
- PR #81 merged: `bde2a1e47443877863fea5e716336640dd37f8d0`. `integration/catalog-foundation` was verified identical to this merge commit before subsequent documentation updates.
- Backend CI run #179 validated the restored parsers: `113 passed`, 4 warnings.
- PR #82 added the pure in-memory `preview_to_observations()` adapter and tests; it was merged as `cf2f178a7524711546ce7c88b1ba7b6fe4bda5db`.
- GitHub Actions run #183 on the adapter code: `118 passed`, 4 warnings.
- The shared adapter keeps `catalog_year` separate from `release_year`, preserves raw source values and provenance, and emits only source-level identifier hints. It performs no matching or persistence.
- Preserved architecture references: `docs/architecture/CATALOG_HIERARCHY_DESIGN.md`, `docs/architecture/SCHEMA_ALIGNMENT_2026-10-29.md`, and `docs/architecture/RELEASE_LINEAGE_RULES.md`.
- Closed stale/superseded PRs #1, #29, #59, #70, #71, #72, #73, #74, #78 and #79 after preserving relevant content. Historical branches and archive refs were not deleted.
- `main`, GitHub Pages default branch and production data remain untouched.
- Remaining important work: inspect saved local HTML fixtures; define shared observation/matching/confirmation contracts; separately design safe additive migrations for Package, Manufacturer/Brand, ProductLine/CatalogNode and Origin.


## Read-only importer matcher · 2026-11-04

- В feature-ветке `feature/read-only-import-matcher` добавлен `backend/app/importers/matcher.py` с функцией `match_import_observation()`.
- Matcher работает поверх существующих `Release`, `Casting`, `IdentifierType`, `CatalogIdentifier`, `ReleaseIdentifier`, `CastingIdentifier` и `SourceRecord`; новые таблицы и миграции не добавлялись.
- Поддержаны объяснимые результаты `exact_source_replay`, `strong_candidate`, `identifier_collision`, `ambiguous`, `no_match`.
- Exact replay определяется только при явной паре `source_id` + `content_hash`; URL или SKU сами по себе не считаются доказательством replay.
- Matching выполняет только SELECT. Нет записи SourceRecord/Evidence/Conflict, регистрации identifier, изменения статусов или merge.
- Добавлены тесты на exact name/year, identifier lookup, collision, неизвестный namespace, exact source replay и read-only поведение.
- CI для этой ветки ожидает запуска после открытия draft PR. До успешного CI не считать реализацию проверенной.
- Ограничение: matcher пока ориентирован на Release candidates; explainable attribute diff и полноценный preview action builder ещё не реализованы.
