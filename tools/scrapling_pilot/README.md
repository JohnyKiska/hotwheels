# Scrapling Fandom pilot

Изолированный offline-first эксперимент для извлечения исходных структур из
сохранённых HTML-страниц Hot Wheels Wiki/Fandom.

## Границы безопасности

- Читает только переданные локальные HTML-файлы.
- Не выполняет HTTP-запросы и не запускает браузер.
- Не вызывает приложение HW Catalog или базу данных.
- Создаёт только JSON-отчёт, не изменяет каталог.
- Сохраняет исходный текст и HTML ячеек. Не определяет идентичность отливок,
  колёс, тампо, цветов или вариантов.

## Установка

Используй отдельное виртуальное окружение, не окружение backend:

```powershell
py -3 -m venv .venv-scrapling
.\.venv-scrapling\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install scrapling
```

Браузерные дополнения для разбора сохранённого HTML не нужны.

## Подготовка страниц

Сохрани исходный HTML (не скриншот) трёх страниц:

- https://hotwheels.fandom.com/wiki/Custom_Camaro
- https://hotwheels.fandom.com/wiki/%2785_Honda_City_Turbo_II
- https://hotwheels.fandom.com/wiki/BMW_323

Назови файлы custom-camaro-1968.html, 85-honda-city-turbo-ii.html и
bmw-323-1990.html. Используй обычное сохранение страницы браузером и соблюдай
правила сайта, условия использования и robots.txt.

## Запуск

Из корня каталога `tools/scrapling_pilot`:

```powershell
$htmlFiles = Get-ChildItem .\pilot-input -Filter *.html | ForEach-Object { $_.FullName }
python .\extract_cards.py @htmlFiles --output .\pilot-output\scrapling-pilot.json
```

Из корня репозитория:

```powershell
$htmlFiles = Get-ChildItem .\tools\scrapling_pilot\pilot-input -Filter *.html | ForEach-Object { $_.FullName }
python .\tools\scrapling_pilot\extract_cards.py @htmlFiles --output .\tools\scrapling_pilot\pilot-output\scrapling-pilot.json
```

## Политика извлечения изображений

- Для URL изображения приоритетны `data-src`, `data-original`,
  `data-lazy-src` и `data-url`; затем `data-srcset` / `srcset`, и только
  после них обычный `src`.
- Заглушки `data:`, вероятные иконки интерфейса и мелкие изображения
  отфильтровываются.
- Одинаковые URL дедуплицируются без query-параметров. Исходный URL при этом
  сохраняется в записи.
- Каждому изображению присваиваются роли: `gallery`, `release_table` и/или
  `article`. Одно изображение может иметь несколько ролей.
- Счётчики отдельно показывают уникальные изображения, изображения галерей,
  изображения таблиц и число пропущенных элементов.

Фильтр интерфейсных изображений эвристический: итоговый JSON всё равно нужно
проверять глазами, особенно если у страницы нестандартная разметка.

## Проверка

1. Все ли таблицы вариантов/производства обнаружены?
2. Сохранены ли границы строк и текст ячеек?
3. Берутся ли настоящие lazy-load URL, а не прозрачные заглушки?
4. Убраны ли дубли, логотипы и мелкие иконки?
5. Попали ли фотографии галерей и таблиц в соответствующие роли?
6. Сохранены ли ссылки на варианты и детали?
7. Не нормализованы ли неоднозначные формулировки источника?
8. Сравнить те же HTML с read-only импортёром all_hot_wheels.

## Вне рамок

Нет production-зависимости, сетевого краулера, прокси-ротации, браузерной
автоматизации, обхода ограничений доступа, записи в БД или интеграции
импортёра. Любое извлечённое значение остаётся кандидатом до проверки.
