# HW Catalog · контекст проекта

## Цель

Создать проверяемый каталог Hot Wheels с разделением базовых моделей, конкретных выпусков, упаковок, источников и доказательств. Интерфейс каталога должен помогать исследовать и редактировать структуру, не подменяя фактические данные визуальными предположениями.

## Источник актуального интерфейса

Актуальная визуальная основа выбрана пользователем:

- Исходная ветка: `prototype/catalog-visual-v1`.
- Исходный файл: `prototype/catalog-visual/index.html`.
- Рабочая копия главной страницы в интеграционной ветке: `index.html`.
- Редактор схемы: `schema-editor.html`.

Прежний корневой интерфейс из `main` (проект раннего этапа, созданный с Gemini) не считается актуальной визуальной основой. Его исходное состояние сохранено в ветке `archive/gemini-main-2026-11-04`.

Из `catalog/editor.html` разрешено заимствовать только механику drag & drop. Перед интеграцией нужно адаптировать её к DOM, типам узлов, правилам связей и состоянию нового каталога. Переносить старую страницу целиком нельзя.

## Модель предметной области

- Casting — базовая отливка.
- Release — выпуск Casting в конкретном году.
- Для каждого сочетания Casting и года создаётся отдельный Release.
- Mainline/Premium и другие типы выпусков не объединяются в одну запись.
- Колёса, маркировка днища, цвет, декор и иные отличия могут быть признаками разных выпусков.
- TH/STH/Chase описываются как свойства выпуска; отдельные исполнения выделяются только при наличии фактических оснований.
- Package — самостоятельная сущность упаковки; состав и порядок вложений задаются явно.
- SKU и номер каталога не используются как единственный глобальный ключ.

## Достоверность и происхождение данных

- Сохранять источники, снимки источников, Evidence, конфликты и историю решений.
- Импорт не должен перезаписывать подтверждённые поля.
- Автоматическое объединение допустимо только при достаточных основаниях.
- Каталоговое подтверждение и физическое подтверждение разделяются.
- Fandom и AllHW не считаются автоматически независимыми источниками.
- Отсутствие фотографии само по себе не является ошибкой. Недостаток свидетельств означает необходимость проверки, а не автоматическое отклонение.

## Рабочие правила

- Все изменения консолидации выполнять в `integration/catalog-foundation`.
- `main` не менять до проверки и отдельного решения о переносе.
- Исторические наработки сохранять в архивной ветке до завершения аудита.
- Не выполнять массовое слияние divergent-веток.
- Не удалять ветки, файлы или данные без отдельного согласования.


## Состояние архива веток на 2026-11-04

- Созданы архивные копии 82 исторических веток в пространстве `archive/2026-11-04/<исходное-имя-ветки>`.
- SHA каждой архивной копии проверен на совпадение с соответствующей исходной веткой.
- Две рабочие ветки сохранены: `prototype/catalog-visual-v1` и `integration/catalog-foundation`.
- `main` не изменён; его состояние совпадает с `archive/gemini-main-2026-11-04`.
- Исходные имена исторических веток пока оставлены. Удаление исходных refs не выполнялось.
- GitHub default branch по-прежнему `main`; GitHub Pages пока не переключался.

## Backend status · 2026-11-04

- `integration/catalog-foundation` includes the merged identifier idempotency/conflict traceability work from PR #80 and the read-only import previews from PR #81.
- Preview endpoints accept user-supplied Mainline TSV, local Fandom yearly HTML, and saved All Hot Wheels card HTML. They do not fetch network pages or write to the catalog.
- The importer code is covered by GitHub Actions run #179: 113 passed, 4 warnings.
- The current backend model set does not yet include ProductLine/CatalogNode, Package, Manufacturer/Brand, or Origin entities. These remain separate design/model tasks; no old PR #74 migrations were imported.
- Mainline's complete observation/matching/confirmation/apply pipeline is not implemented. Current endpoints are parser previews only.
- PRs #1, #29, #59, #70, #71, #72, #73, #74, #78 and #79 were closed after preserving useful importer code, fixtures, specifications, and architecture notes in the active integration branch or archive refs. No historical branches were deleted.
