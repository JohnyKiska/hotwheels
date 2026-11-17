# HW Catalog · текущее состояние

**Актуальный срез:** 2026-11-17  
**Рабочая ветка:** `integration/catalog-foundation`  
**Источник истины для кода, документации и состояния Project Manager:** GitHub  
**Внешний диск:** отдельное хранилище данных и будущая синхронизируемая копия; не считать его источником версии кода.

## Состояние Project Manager

- Создана модель данных v1: `docs/project-management/project-state.json`.
- Контракт данных: `docs/project-management/project-state.schema.json`.
- Dashboard: `docs/project-management/index.html`.
- Правила запуска и редактирования: `docs/project-management/README.md`.
- Историческое дерево из прежнего dashboard перенесено в отдельную коллекцию из **56 компонентов**. Это инвентаризационная база, а не подтверждение актуальности каждого узла.
- Задачи, компоненты, рабочие направления, решения, блокеры и changelog теперь раздельные сущности.
- Dashboard загружает canonical JSON, поддерживает локальный черновик и экспорт/импорт. Прямой записи в GitHub нет; токен в браузере не хранится.
- Статусы задач и компонентов не смешиваются в одном проценте готовности.
- Загрузка canonical JSON, строгая JSON Schema validation и проверка cross-references реализованы. Добавлены создание и редактирование компонентов, решений и блокеров с проверкой до применения; блокеры связываются с задачами. В работе аудит дерева компонентов, запланировано браузерное тестирование.

## Текущие ограничения и правила безопасности

- Не открывать dashboard через `file://`; нужен HTTP-сервер, чтобы браузер мог загрузить JSON.
- Локальный черновик хранится только в конкретном браузере и не синхронизируется между устройствами.
- Экспортированный JSON нужно проверить и закоммитить в GitHub. Только после этого он становится canonical.
- Внешняя SQLite БД, пользовательские данные, секреты и machine-specific файлы не добавляются в Git.
- Общую автоматическую синхронизацию репозитория с внешним диском не включать до отдельного аудита include/exclude и сценария восстановления. Подтверждённая точечная синхронизация ALLHW выполнена отдельно.
- Старые статусы и факты из дерева Project Manager требуют проверки по текущему репозиторию и не должны автоматически трактоваться как актуальные.

## Подтверждённый контекст проекта

- `integration/catalog-foundation` остаётся рабочей интеграционной веткой; эта работа не направляла изменения в `main`.
- Backend содержит read-only import preview pipeline: parser → observation → matcher → optional claim diff для Mainline TSV, локального Fandom HTML и локального All Hot Wheels HTML.
- Preview API не должен выполнять автоматический выбор Release, запись в каталог или сетевую загрузку исходников.
- Исторические CI результаты относятся к конкретным коммитам и не заменяют повторный CI на текущем HEAD.
- Staging, постоянное размещение БД, OAuth/SMTP secrets и ручной end-to-end тест требуют отдельной проверки.
- Данные каталога и внешняя SQLite база остаются вне Git.

## Подтверждённая синхронизация ALLHW · 2026-11-16

- Исправлен MANIFEST.csv в архивном репозитории: PR #2, merge commit `3d628fce6e861bd67c13ff4ad7e306805527ac57`.
- Свежий ZIP из `main` проверен локально: 60 записей, 0 ошибок размера/SHA-256.
- Все 60 HTML-файлов скопированы на внешний HDD в `E:\\HW-CATALOG-DATA\\IMPORTS\\ALLHW`.
- Проверка исходников до копирования и повторная проверка HDD завершились с результатом 60/60, ошибок 0.
- `DATABASE/catalog.db` и `BACKUPS` при импорте не затрагивались.

## Следующие шаги

1. Проверить Project Manager в браузере через HTTP на desktop/mobile.
2. Проверить read-only importer preview на репрезентативных локальных HTML из ALLHW.
3. Отдельно спроектировать безопасную общую синхронизацию GitHub ↔ внешний диск; точечный перенос ALLHW не означает разрешение синхронизировать весь репозиторий.

## Исторический журнал состояния

Ниже сохранены ранее записанные контрольные точки. Они отражают состояние на указанные даты и не должны автоматически считаться текущим статусом.

---


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
- `hotwheels-fandom-archive/ALLHW`: исходные HTML-страницы 1968–2026; основной репозиторий содержит совместимый read-only importer, а не копию архива.
- `catalog/editor.html` из старого main: источник drag & drop, не источник новой страницы.

## Не выполнено

- Перенос и адаптация drag & drop.
- Аудит различий между `prototype/catalog-visual-v1`, `main` и backend-наработками.
- Проверка импортёра на сохранённых HTML из внешнего архива и аудит оставшихся исторических компонентов ALLHW.
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
- PR #83 merged в `integration/catalog-foundation` (squash commit `c9f01d45dedc3e856486388cb910d8ed11dbacfd`). GitHub Actions run #184: `124 passed`, 4 warnings. Integration проверена как identical merge commit; `main` остался на `b315431d279c42d94a76766d89dd18187278039c`.
- Ограничение: matcher пока ориентирован на Release candidates; explainable attribute diff и полноценный preview action builder ещё не реализованы.


## Attribute preview diff · 2026-11-04

- В отдельной feature-ветке добавлен pure in-memory `build_release_claim_diff(observation, release_snapshot)`.
- Diff выдаёт `same`, `new_evidence`, `conflicting_value`, `evidence_only`, `insufficient_evidence` и предлагает только preview actions.
- Прямое сравнение ограничено текущими canonical полями: model name, catalog year, assortment number, series name. Остальные атрибуты сохраняются как evidence-only, без ложного отображения их как полей Release.
- Различия не перезаписываются и не применяются; функция не обращается к БД.
- Добавлены unit tests; CI ожидается после PR.


## Claim preview diff merge · 2026-11-04

- PR #84 merged в `integration/catalog-foundation` (squash commit `058ac4ffc6da11284dc2f97414203e3299b4459b`).
- GitHub Actions run #187: `131 passed`, 4 warnings.
- `build_release_claim_diff()` реализован как pure in-memory diff без DB access и writes.
- Статусы: `same`, `new_evidence`, `conflicting_value`, `evidence_only`, `insufficient_evidence`; unsupported attributes не маппятся в неподходящие canonical columns.
- Следующий шаг: read-only preview API orchestration parser → observation → matcher → diff; persistence/apply остаются за отдельным review.


## Read-only import preview API · 2026-11-04

- В feature-ветке `feature/read-only-import-preview-api` добавлен `POST /imports/preview`.
- Endpoint связывает parser → observation adapter → read-only matcher → optional claim diff.
- Поддержаны `mainline_tsv`, `fandom_html`, `all_hot_wheels_html`; HTML принимается только как локально переданный текст, network fetch отсутствует.
- Для multi-record parser payload применяется `record_index`; diff строится только при явном `selected_release_id`, автоматического выбора Release нет.
- Endpoint возвращает `writes_to_catalog=false`; запись SourceRecord/Evidence/Conflict, identifier registration и catalog updates отсутствуют.
- Добавлены API tests для всех трёх source paths, candidate matching, explicit diff, invalid index, unknown Release, required year и read-only DB invariants. CI ожидает запуска.


## Pipeline preview API merge · 2026-11-04

- PR #85 merged в `integration/catalog-foundation` (squash commit `c787696e9dc25abfc985de485710fd8f2569d0aa`).
- GitHub Actions run #188: `138 passed`, 4 warnings.
- `POST /imports/preview` теперь объединяет parser → observation → matcher → optional claim diff для Mainline TSV, локального Fandom HTML и локального All Hot Wheels HTML.
- `record_index` и `selected_release_id` задаются явно; никакого auto-select и apply.
- Endpoint проверен тестами на отсутствие записей SourceRecord/Evidence/Conflict и отсутствие catalog mutations.

- Backend API deployment target, persistent database hosting, and API authentication are not configured. The current backend includes write-capable conflict resolution endpoints, so public browser access/CORS must not be enabled until authentication and deployment boundaries are designed.

## Media storage and upload · 2026-11-17

- PR #116 (Media Library metadata/API) merged into `integration/catalog-foundation`; merge commit `c6512c0e31e0722f17c425aa9dbf9a43014419ce`.
- PR #117 (filesystem upload + thumbnails) is open against `integration/catalog-foundation`. Latest head: `bc7acfbab18c0ffb7f09da0558fafe5ba4db799c`. GitHub Actions checks for this head completed successfully, including backend tests, clean/repeat SQLite and PostgreSQL migrations, PostgreSQL append-only enforcement and staging Compose validation. Confirmed image build/check conclusion through the run before merge; do not treat an open PR as merged.
- Upload API accepts JPEG/PNG/WEBP up to 15 MiB and 40 MP, preserves original bytes, computes SHA-256, rejects exact duplicates, and creates separate 640 px WEBP thumbnails.
- File routes are authenticated; upload requires catalog.create, CSRF and audit reason. Rights default to unknown. No public image publishing.
- Media files are outside Git and database. Local root: `HW_CATALOG_MEDIA_DIR`; external-drive mode: `HW_CATALOG_DATA_DIR/MEDIA`; development fallback: `backend/media`. Explicit external storage configuration fails closed if its initialized media directory is unavailable.
- Staging Compose declares persistent `media_data` volume. The volume still needs to be included in backup/restore operations.
- The upload UI and physical HDD round-trip test are deliberately deferred to the next work session. External drive contents were not modified or verified by this GitHub-side work.
