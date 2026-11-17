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

\`\`\`powershell
py -3 -m venv .venv-scrapling
.\.venv-scrapling\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install scrapling
\`\`\`

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

Из корня каталога \`tools/scrapling_pilot\`:

\`\`\`powershell
$htmlFiles = Get-ChildItem .\pilot-input -Filter *.html | ForEach-Object { $_.FullName }
python .\extract_cards.py @htmlFiles --output .\pilot-output\scrapling-pilot-v3.json
\`\`\`

Из корня репозитория:

\`\`\`powershell
$htmlFiles = Get-ChildItem .\tools\scrapling_pilot\pilot-input -Filter *.html | ForEach-Object { $_.FullName }
python .\tools\scrapling_pilot\extract_cards.py @htmlFiles --output .\tools\scrapling_pilot\pilot-output\scrapling-pilot-v3.json
\`\`\`

## Политика извлечения изображений

- Для миниатюры приоритетны \`data-src\`, \`data-original\`,
  \`data-lazy-src\` и \`data-url\`; затем \`data-srcset\` / \`srcset\`, и только
  после них обычный \`src\`.
- URL миниатюры сохраняется в \`thumbnail_url\`. Старое поле \`src\` оставлено
  как совместимый дубль этого значения.
- Извлекается точный \`href\` ближайшей родительской ссылки изображения в
  \`parent_link_url\`. Он может вести на страницу файла или на сам ресурс.
  Скрипт не переименовывает его в «оригинал» и не пытается угадывать прямой
  URL оригинального файла.
- Сохраняются \`data-image-key\`, \`data-image-name\` и
  \`data-image-relevant\`, если они присутствуют в HTML.
- Дедупликация использует приоритет: \`data-image-key\`, затем URL родительской
  ссылки без query-параметров, затем URL миниатюры без query-параметров.
- Каждому изображению присваиваются роли: \`gallery\`, \`release_table\`
  и/или \`article\`. Одно изображение может иметь несколько ролей.
- Маленькие изображения больше не отбрасываются только из-за размера:
  фотографии блистера, колёс и мелких деталей могут быть важны.
- Отбрасываются только уверенно распознаваемые UI-заглушки и элементы
  интерфейса. Эвристика всё равно требует визуальной проверки.

## Проверка v3

1. Сравнить число записей изображений с v2: рост может быть нормальным,
   поскольку маленькие фотографии больше не фильтруются.
2. Проверить, заполняется ли \`parent_link_url\` у фотографий галерей и таблиц.
3. Убедиться, что ссылка действительно ведёт к странице файла или ресурсу,
   а не на постороннюю страницу.
4. Проверить, что одинаковый файл в разных ролях объединён, а разные файлы
   не склеены ошибочно.
5. Отдельно проверить \`data_image_key\`, \`data_image_name\` и
   \`data_image_relevant\`, если Fandom сохранил эти атрибуты.
6. Убедиться, что таблицы, строки, ячейки и исходный HTML остались целыми.
7. Сравнить те же HTML с read-only импортёром all_hot_wheels.

## Вне рамок

Нет production-зависимости, сетевого краулера, прокси-ротации, браузерной
автоматизации, обхода ограничений доступа, записи в БД или интеграции
импортёра. Любое извлечённое значение остаётся кандидатом до проверки.


## Выгрузка фотографий для ручной проверки (v3)

После того как `scrapling-pilot-v3.json` уже находится в `pilot-output`,
запусти из корня репозитория:

```powershell
python .\tools\scrapling_pilot\pilot-output\export_images.py `
  --input .\tools\scrapling_pilot\pilot-output\scrapling-pilot-v3.json `
  --output-dir .\tools\scrapling_pilot\pilot-output\photos
```

Или из папки `tools\scrapling_pilot\pilot-output`:

```powershell
python .\export_images.py --input .\scrapling-pilot-v3.json --output-dir .\photos
```

Скрипт:
- создаёт отдельные папки по страницам/моделям;
- для прямых ссылок скачивает указанный ресурс;
- для ссылок на Fandom File page пытается извлечь полноразмерный URL из HTML
  страницы файла; если это не удаётся, скачивает сохранённую миниатюру;
- не удаляет повторы и сомнительные изображения;
- создаёт `photo_manifest.csv` рядом с папкой `photos`;
- оставляет пустыми поля `photo_type_manual` и `quality_manual`, чтобы их
  можно было заполнить после визуального просмотра;
- сохраняет исходные URL, фактический URL загрузки, размер файла и ошибки.

Выгрузка выполняет сетевые GET-запросы только к URL, уже записанным в JSON,
с короткой паузой между изображениями. Учитывай условия использования Fandom.
Она не меняет JSON-отчёт, исходный HTML, код импортёра или базу данных.


## Выгрузка изображений через Chrome (Cloudflare)

Если обычный экспортёр получает HTTP 403, используй отдельный браузерный
экспортёр. Он открывает установленный Chrome через Playwright и использует
постоянный профиль `pilot-output/chrome-test-profile`. Если появится
Cloudflare challenge, его нужно пройти вручную в окне Chrome. Скрипт не
обходит и не автоматизирует проверку.

Установка (один раз):

```powershell
py -m pip install playwright
```

Пробный запуск первых пяти записей (из корня репозитория):

```powershell
py .\tools\scrapling_pilot\pilot-output\export_images_browser.py --limit 5
```

Если тест прошёл, выгрузка всех записей:

```powershell
py .\tools\scrapling_pilot\pilot-output\export_images_browser.py --limit 0
```

По умолчанию JSON читается из той же папки, фотографии сохраняются в
`pilot-output/photos` по папкам страниц/моделей, а отдельный манифест
`photo_manifest_browser.csv` создаётся рядом с папкой `photos`.
Уже существующие файлы пропускаются. Старый `export_images.py` и его
`photo_manifest.csv` остаются без изменений.
