# HW Catalog · старт проекта

## Текущая рабочая основа

- Основная визуальная точка входа: `index.html`.
- Источник интерфейса: `prototype/catalog-visual/index.html`, перенесён в корень репозитория в ветке `integration/catalog-foundation`.
- Редактор схемы: `schema-editor.html`.
- Промежуточная ветка консолидации: `integration/catalog-foundation`.
- Снимок прежнего `main`: `archive/gemini-main-2026-11-04`.

## Важные оговорки

Текущий визуальный каталог пока является фронтенд-прототипом. Его демонстрационные данные и локальные действия ещё не подключены к рабочему backend/API и постоянному хранилищу.

`catalog/editor.html` не является основой нового интерфейса. Его разрешено использовать как источник реализации drag & drop после адаптации к структуре данных нового каталога. Нельзя переносить редактор целиком.

## Архитектура данных

- Casting — базовая отливка.
- Release — конкретный выпуск Casting в конкретном году.
- Каждый выпуск в конкретном году является отдельным Release.
- Mainline и Premium — разные выпуски, а не варианты одной записи.
- Отличия колёс, маркировки днища, декора и цвета могут указывать на разные Releases.
- TH/STH/Chase — свойства Release; отдельные исполнения фиксируются по подтверждённым фактам.
- SKU и annual catalog number не являются глобально уникальными идентификаторами.

См. `PROJECT_CONTEXT.md`, `docs/CURRENT_STATE.md` и `docs/ROADMAP.md`.


## Локальный запуск визуального прототипа

Страница статическая и не требует сборки или установки npm-зависимостей.

В PowerShell из корня репозитория:

```powershell
git fetch origin
git switch integration/catalog-foundation
git pull --ff-only
py -m http.server 8000
```

Открыть в браузере: http://localhost:8000/

Остановка локального сервера: Ctrl+C в окне PowerShell.

Важно: это запуск фронтенд-прототипа. Backend уже предоставляет read-only preview API для Mainline TSV, локального Fandom HTML и All Hot Wheels HTML, но визуальный каталог пока не подключён к этим endpoint и постоянному хранению данных.


## Backend importer status · 2026-11-04

Backend уже содержит read-only source parsers, общий observation adapter и read-only Release matcher, интегрированный в `integration/catalog-foundation` через PR #83. Matcher только ищет кандидатов и объясняет сигналы; он не пишет в БД и не объединяет записи. См. `docs/importers/IMPORTER_OBSERVATION_CONTRACT.md` и `docs/SESSION_HANDOFF.md`.

The importer pipeline also includes a read-only Release matcher and a pure in-memory claim preview diff. The diff distinguishes unchanged values, new evidence candidates, conflicting values, evidence-only attributes, and insufficient evidence. It does not write to the catalog. See `docs/importers/IMPORTER_OBSERVATION_CONTRACT.md`.

The read-only orchestration endpoint is `POST /imports/preview`. It accepts Mainline TSV, locally supplied Fandom yearly HTML, or locally supplied All Hot Wheels car HTML and returns parser issues, normalized observation, matching signals, and an optional claim diff for an explicitly selected Release. It does not write to the catalog.
