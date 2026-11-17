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
.\\.venv-scrapling\\Scripts\\Activate.ps1
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

Из корня репозитория (каталог pilot-output будет создан автоматически):

\`\`\`powershell
python tools/scrapling_pilot/extract_cards.py .\\pilot-input\\custom-camaro-1968.html .\\pilot-input\\85-honda-city-turbo-ii.html .\\pilot-input\\bmw-323-1990.html --output .\\pilot-output\\scrapling-pilot.json
\`\`\`

Скрипт выведет количество таблиц, изображений и ссылок и сохранит полный JSON.

## Проверка

1. Все ли таблицы вариантов/производства обнаружены?
2. Сохранены ли границы строк и текст ячеек?
3. Извлечены ли URL изображений, alt и lazy-load атрибуты?
4. Сохранены ли ссылки на варианты и детали?
5. Не нормализованы ли неоднозначные формулировки источника?
6. Сравнить те же HTML с read-only импортёром all_hot_wheels.

## Вне рамок

Нет production-зависимости, сетевого краулера, прокси-ротации, браузерной
автоматизации, обхода ограничений доступа, записи в БД или интеграции
импортёра. Любое извлечённое значение остаётся кандидатом до проверки.
