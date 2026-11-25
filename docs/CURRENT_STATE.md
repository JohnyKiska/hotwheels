# HW Catalog · текущее состояние

**Актуальный срез:** 2026-11-25  
**Рабочая ветка:** `integration/catalog-foundation`  
**Последний опубликованный commit:** `d6fc574` — `Complete catalog admin and product line migrations`  
**Состояние GitHub:** commit отправлен в `origin/integration/catalog-foundation`; `main` не изменялась.

## Краткий статус на 2026-11-25

### Выполнено

- Завершена текущая консолидация backend admin и ProductLine; изменения опубликованы в рабочей ветке.
- В `backend/app/admin_catalog_api.py` реализованы административные API для чтения и изменения Casting, Release, Variant, Series и ProductLine, включая прямые назначения ProductLine выпускам и привязку Evidence к таким назначениям.
- В `admin.html` добавлен раздел ProductLine: список, поиск, фильтрация по статусу, просмотр и редактирование. Добавлены элементы выбора Casting с поиском и управление связями.
- Добавлена модель ProductLine с иерархией через parent, а также таблицы `release_product_lines` и `evidence_product_lines`. Связи Release–ProductLine допускают историю статуса назначения; Evidence связывается с конкретным назначением.
- Добавлена миграция `20261123_product_line_tables` с проверками существующих таблиц, ограничений, индексов, повторного upgrade и безопасного downgrade при наличии данных.
- Добавлена миграция `20261123_release_nullable_casting`: Release может оставаться без Casting, пока физическая идентичность не подтверждена.
- Добавлены тесты миграций ProductLine, административного API, моделей и importer matcher; добавлены автоматические тесты обработки eBay notifications.
- Исправлена ORM-обработка удаления Casting: `passive_deletes="all"` позволяет БД применить FK `ON DELETE RESTRICT`, а не пытаться обнулить дочерние ссылки.
- Исправлено устаревшее ожидание ревизии в тесте отказа eBay migration downgrade: после неудачного downgrade версия БД остаётся на исходной head.
- Полный локальный прогон на commit `d6fc574`: **360 passed, 47 warnings, 0 failed**. Предупреждения включают deprecation в Starlette/httpx и настройку `path_separator` в Alembic. Отдельный CI run на этом commit не заявляется.
- Добавлен `docs/architecture/ADR-001-HW-Catalog-Architecture.md` как архитектурное предложение по разделению ProductLine, Assortment, Series, Distribution Assortment, Release, Casting, Variant, Package и ProductSet. Статус ADR — **Proposed**, он ещё не утверждён.

### В процессе / требует проверки

- Новые административные сценарии реализованы в коде, но полноценная ручная проверка UI в браузере (desktop/mobile), включая ошибки, пустые состояния и реальные связи, ещё не отмечена как завершённая.
- ProductLine taxonomy и ADR-001 требуют предметной проверки и явного утверждения; наличие таблиц не означает, что все классификационные термины окончательно согласованы.
- Casting grouping review остаётся предварительным инструментом проверки: предложения группировки не являются автоматическим объединением Casting и не должны применяться без отдельного решения.
- eBay notification processing покрыт тестами, но это не означает завершённую production-интеграцию eBay или проверенный реальный webhook flow.

### Следующие задачи

1. Провести браузерную проверку `/admin` на desktop и mobile: Casting, Release, Series, ProductLine, фильтры, редактирование и связи.
2. Проверить ProductLine taxonomy по официальным каталогам Mattel и утвердить/исправить ADR-001 до массового заполнения.
3. Проверить read-only importer preview на репрезентативных сохранённых HTML из ALLHW; фиксировать parser issues и ложные совпадения.
4. Отдельно спроектировать безопасный этап import apply: candidate → review → confirmation → write, с Evidence, Conflict и changelog. Не включать автоматические merge/overwrite.
5. Доделать UI загрузки Media Library и проверить физический round-trip файлов на внешнем HDD; затем включить MEDIA в backup/restore и проверить восстановление.
6. Настроить staging: HTTPS, постоянную БД/хранилище, OAuth/SMTP secrets в окружении сервера, rate limiting/monitoring и ручные E2E проверки.
7. После проверки текущей ветки подготовить отдельный PR в `main`; не менять default branch и GitHub Pages без согласования.

## Git и данные

- Код и документация: GitHub, ветка `integration/catalog-foundation`.
- Последний опубликованный commit: `d6fc574d239e01a4aaeb5e6903632a78141e7680`.
- `main` не изменялась; перенос в `main` ещё не выполнен.
- Рабочая SQLite БД, media, backups, импорты и пользовательские данные находятся вне Git. Текущие миграционные тесты используют временные БД; рабочая БД не изменялась.
- Не коммитить `.env`, реальные ключи, SQLite, media, backups, machine-specific пути и экспериментальные скрипты.
- Не запускать общую синхронизацию внешнего HDD с репозиторием без отдельного include/exclude и recovery-аудита.

---

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
