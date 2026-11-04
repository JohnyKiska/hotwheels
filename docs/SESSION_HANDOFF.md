# HW Catalog · передача контекста

Дата: 2026-11-04.

## Главная договорённость

Пользователь уточнил, что прежний `main` содержит старый интерфейс проекта, сделанный с Gemini, и не является визуальной основой текущей версии.

Актуальная основа каталога — `prototype/catalog-visual-v1`, файл `prototype/catalog-visual/index.html`. Именно этот интерфейс переносится в корень проекта и должен стать будущей главной страницей `main`.

Из прежнего `catalog/editor.html` можно заимствовать только drag & drop. Старую страницу целиком переносить нельзя.

## Что уже сделано

- Создана `integration/catalog-foundation` от `prototype/catalog-visual-v1`.
- Создана `archive/gemini-main-2026-11-04` от прежнего `main`.
- В интеграционной ветке корневой `index.html` заменён содержимым актуального визуального каталога.
- `schema-editor.html` скопирован в корень, чтобы ссылка из каталога оставалась рабочей.
- Исходная папка `prototype/catalog-visual/` сохранена.
- Документация создана/обновлена в интеграционной ветке.

## Что важно не перепутать

- Это ещё не перенос в `main`. Изменения находятся в интеграционной ветке.
- Архивная ветка создана как страховочная копия прежнего `main`, но не является окончательным архивом всех исторических веток.
- Drag & drop пока не интегрирован.
- Новый визуальный каталог пока прототип: демо-данные и действия не подключены к backend/API.
- Не выполнять полный merge старой `main` или `feature/scheduled-market-data` без выборочного аудита.
- Не удалять ветки и файлы без отдельного решения пользователя.

## Следующий шаг

Адаптировать drag & drop из `catalog/editor.html` к новому интерфейсу, затем провести аудит backend/API и ALLHW. После этого собрать проверяемый PR в `main`.


## Дополнение после синхронизации веток · 2026-11-04

- Проведена инвентаризация веток GitHub: на момент проверки было 89 веток.
- Созданы 82 архивные копии исторических веток: `archive/2026-11-04/<исходное-имя-ветки>`.
- Все 82 копии сверены с исходными SHA; пропусков и несовпадений нет.
- `prototype/catalog-visual-v1` и `integration/catalog-foundation` оставлены рабочими.
- В ходе консолидации `main` не изменялся; HEAD при проверке — `b315431d279c42d94a76766d89dd18187278039c`. `archive/gemini-main-2026-11-04` является историческим снимком, но сейчас diverged от `main` (29/90 commits по GitHub compare), не считать его точной копией текущей ветки.
- Исходные refs пока не удалялись. GitHub default branch и Pages остаются на `main`.
- Визуальный прототип представляет собой статическую страницу без внешних CSS/JS-зависимостей и без подключения backend/API.

## Ближайший практический шаг

Запустить `integration/catalog-foundation` локально из корня репозитория командой `py -m http.server 8000`, открыть `http://localhost:8000/` и пройти визуальную проверку. Зафиксировать отсутствующие и неработающие функции. После этого проверить исторические ветки по конкретному списку недостающих возможностей, не переносить их целиком.

## Выборочный перенос backend из PR #72 и #73 · 2026-11-04

Создана рабочая ветка `integration/import-idempotency-conflict-traceability` от `integration/catalog-foundation` и черновой PR [#80](https://github.com/JohnyKiska/hotwheels/pull/80). PR открыт в draft, не смержен.

Перенесено:
- Идемпотентная регистрация Evidence: повторная обработка одного `SourceRecord` с тем же нормализованным identifier claim повторно использует Evidence.
- Разные `SourceRecord` остаются разными наблюдениями; один Evidence может быть связан с несколькими Release без дублирования.
- Добавлена сущность `ConflictRelease` и миграция `20261104_conflict_releases`, построенная непосредственно поверх текущей цепочки миграций integration и не зависящая от PR #74.
- Конфликты идентификаторов связываются с затронутыми Release и только с релевантными Evidence.
- Очередь/детали конфликтов показывают Release и provenance; история решений поддерживает отдельное аудируемое действие пересмотра.
- Страница `catalog/conflicts.html` обновлена для отображения Release и истории решений.

Проверки GitHub Actions для HEAD `a44c17abed1319162b08ad3a332dd66ebf9d36ff`:
- Backend tests: success, `92 passed`, 4 warnings.
- Catalog UI checks: success.
- PR #80 mergeable, draft, открыт.

В процессе CI выявили и исправили две интеграционные несовместимости: импорт отсутствующего `catalog_tree_api` из PR #74 в `main.py` и безопасное создание `conflict_releases`, когда ORM уже создал таблицу. Также обновлено ожидание текущей Alembic head в тесте.

Следующее: вручную проверить diff PR #80 и миграционную цепочку, затем согласовать снятие draft/merge. Не переносить PR #74 целиком. После принятия PR #80 продолжить выборочный перенос backend и импортеров #74/#75.

## Follow-up after PR #80 merge · 2026-11-04

PR #80 was merged into `integration/catalog-foundation` with merge commit `c5909c995eb17b16af80710eb1d10849cafd9b9a`. `main` remains untouched.

A new isolated branch, `integration/importers-safe-preview`, was created from that integration head. It selectively restores the following from PR #74:

- `backend/app/importers/mainline.py`: Mainline TSV and local Fandom yearly HTML parsers.
- `backend/app/importers/all_hot_wheels.py`: parser for saved All Hot Wheels model-card HTML.
- Preview-only API routes for all three input formats.
- Synthetic parser and API tests.
- Mainline importer specification and synthetic fixture/test plan, plus All Hot Wheels importer documentation.

Safety boundary: these routes only parse user-supplied text/HTML and return candidates. They do not write to the database, fetch pages, or confirm catalog identity. No Fandom network access is enabled. No old PR #74 ORM models, Catalog Tree API, or risky migration chain were copied.

GitHub Actions run #179 completed successfully on the importer code: `113 passed`, 4 warnings. A later documentation-only commit added the historical hierarchy design reference; it did not change backend code. After CI, inspect parser behavior using local saved HTML fixtures if available. Next architecture step is a shared observation/preview/matching contract, not a direct importer-to-canonical-record write path.

## Latest handoff · 2026-11-04

The current working branch is `integration/catalog-foundation`. PR #80 and PR #81 are merged into it. The latest backend code validation is GitHub Actions run #179 (`113 passed`, 4 warnings).

The read-only Mainline TSV, local Fandom yearly HTML, and All Hot Wheels saved-card HTML preview endpoints are available. They do not write to the database or fetch network pages. The visual catalog frontend is not yet connected to these endpoints.

Useful design documents recovered and retained:
- `docs/importers/MAINLINE_IMPORTER_SPEC.md`
- `docs/importers/MAINLINE_FIXTURE_TEST_PLAN.md`
- `docs/ALL_HOT_WHEELS_IMPORTER.md`
- `docs/architecture/CATALOG_HIERARCHY_DESIGN.md`
- `docs/architecture/RELEASE_LINEAGE_RULES.md`
- `docs/architecture/SCHEMA_ALIGNMENT_2026-10-29.md` (historical snapshot; not current schema truth)

Superseded PRs #1, #29, #59, #70, #71, #72, #73, #74, #78 and #79 are closed. Their useful code/docs were retained where relevant, and archive refs were left intact. No historical branches were deleted. `main` and GitHub Pages remain untouched.

PR #82 added and merged a pure in-memory `preview_to_observations()` adapter. It normalizes all three source-specific previews into a versioned observation envelope, keeps catalog year distinct from release year, preserves source provenance/raw values, and emits only identifier hints. It does not access the database or network. GitHub Actions run #183: `118 passed`, 4 warnings.

Next: design a read-only matcher and explainable preview diff over the shared observation contract. Continue to prohibit direct catalog writes, automatic entity merges, and network fetching until separately designed and explicitly reviewed.


## Matcher implementation · 2026-11-04

Создана feature-ветка `feature/read-only-import-matcher` от `integration/catalog-foundation`.

Добавлено:
- `backend/app/importers/matcher.py`: read-only `match_import_observation(session, observation, source_snapshot=None)`.
- `backend/tests/test_importer_matcher.py`: проверки exact name/year, exact identifier, collision, неизвестного namespace и exact source replay.
- Обновлён `docs/importers/IMPORTER_OBSERVATION_CONTRACT.md`.

Matcher использует существующие Release/Casting/Identifier/SourceRecord модели и только SELECT-запросы. Он не создаёт Evidence, SourceRecord или Conflict, не вызывает `register_identifier()`, не подтверждает и не объединяет сущности. Exact replay возможен только при явном `source_id` и `content_hash`; текущий adapter пока не поставляет эти значения, поэтому обычный observation не классифицируется как replay по одному URL/SKU.

Текущий результат до CI: код и тесты закоммичены в feature branch; draft PR ещё не открыт. Следующий шаг: проверить diff, открыть draft PR в `integration/catalog-foundation`, дождаться GitHub Actions и исправить найденные ошибки. Затем реализовать attribute preview diff. `main`, GitHub Pages и архивные ветки не трогать.
