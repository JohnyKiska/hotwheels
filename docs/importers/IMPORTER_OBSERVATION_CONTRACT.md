# Importer observation contract

**Статус:** observation adapter и первый read-only Release matcher реализованы; matching остаётся preview-only и не меняет схему БД.
**Основа:** Mainline/All Hot Wheels preview parsers, Source/SourceRecord/Evidence, identifier registration and conflict traceability.

## 1. Границы ответственности

- Специализированный parser знает формат источника и извлекает только то, что явно присутствует во входном материале.
- Parser остаётся чистой функцией: входной текст/HTML → preview payload. Без ORM, сети и записи.
- Adapter преобразует source-specific payload в общий `ImportObservation`.
- Matcher ищет кандидатов в существующем каталоге и объясняет причины совпадения/неоднозначности.
- Preview builder показывает предлагаемые действия и расхождения. Он ничего не применяет.
- Apply service вызывается только после явного подтверждения и работает в транзакции с audit trail.

## 2. Общий объект наблюдения (in-memory)

Рекомендуемый контракт одного наблюдения:

```json
{
  "source": {
    "code": "all_hot_wheels",
    "record_type": "car_detail",
    "record_url": "https://example.invalid/car/...",
    "external_id": "JBC25",
    "format": "saved_html"
  },
  "subject_hints": {
    "catalog_year": 2025,
    "name": "Synthetic model name",
    "toy_number": "SYN25",
    "collector_number": null,
    "series_name": "Synthetic series"
  },
  "claims": [
    {
      "attribute": "wheel_type",
      "raw_value": "5-Spoke",
      "value": "5-Spoke",
      "source_field": "Wheels",
      "claim_status": "observed"
    }
  ],
  "identifier_hints": [
    {"type_code": "sku", "raw_value": "SYN25", "source_field": "SKU"}
  ],
  "raw": {"source_values": {}, "raw_text": null},
  "issues": []
}
```

Это схема обмена между компонентами, а не готовый Pydantic/SQLAlchemy model. `value` может быть null; неизвестное не восстанавливается догадкой. `identifier_hints` — только подсказки источника, не созданные связи с каноническими Identifier. Неизвестные/неподдерживаемые поля можно сохранять в `raw` без потери исходного материала.

## 3. Правила нормализации

- Хранить `raw_value` рядом с нормализованным `value`; нормализация не должна стирать термин источника.
- Не превращать `chase` в TH/STH; хранить source label отдельно от внутренней классификации.
- Не смешивать Mainline collector number, assortment number и Mainline #.
- Не выводить знаменатель серии, год или номер Mainline из соседних записей.
- Не считать `toy_number` глобальным уникальным ключом.
- Fandom и All Hot Wheels не считать независимыми подтверждениями автоматически.
- Для атрибутов, где правила нормализации ещё не согласованы, использовать только безопасную trim/whitespace-нормализацию.

## 4. Matching и preview

Matcher должен возвращать объяснимый результат, а не только score:

- `exact_source_replay` — тот же источник и тот же immutable source snapshot/content hash;
- `strong_candidate` — достаточно согласованных признаков для показа кандидата, но не для автоматического слияния;
- `identifier_collision` — идентификатор уже назначен несовместимому контексту/нескольким Release;
- `ambiguous` — несколько возможных сущностей;
- `no_match` — подходящий кандидат не найден.

Для каждого результата сохранять matched entity IDs, признаки совпадения, противоречия и причины неопределённости.

Preview action candidates:

- `no_change` — повторная обработка идентичного source snapshot;
- `attach_evidence` — новое наблюдение к уже выбранной сущности без перезаписи её значений;
- `review_conflict` — несовместимые утверждения/идентификаторы требуют ручного решения;
- `create_candidate` — новый кандидат после явного подтверждения;
- `manual_match_required` — нельзя выбрать сущность однозначно.

Один SKU или похожее имя не являются достаточным основанием для merge, подтверждения Release или автоматического выбора победившего источника.

## 5. Persistence и идемпотентность

Текущие `Source`, `SourceRecord` и `Evidence` подходят как основа provenance. `register_identifier()` умеет безопасно связывать уже существующий Release/Casting/CastingVariant с identifier и source evidence, но это не полный importer orchestration.

До проектирования новых таблиц определить, какие состояния можно выразить текущими моделями. Не создавать параллельную систему Source/Evidence.

Правила:

- SourceRecord представляет конкретный снимок источника и не должен незаметно переписываться новым содержимым.
- Повторная обработка того же SourceRecord и того же нормализованного claim должна быть идемпотентной.
- Другой SourceRecord остаётся отдельным наблюдением даже при идентичном значении.
- Evidence хранит утверждение источника; оно не подтверждает автоматически идентичность Release.
- Конфликт идентификаторов создаёт review signal и traceability, но не объединяет сущности.
- Подтверждённые значения не перезаписываются при импорте.

## 6. Подтверждение и применение

Apply — отдельная операция после явного решения пользователя. Она должна:

1. Проверить, что preview основан на актуальной версии каталога или повторно вычислить diff.
2. Применить только явно выбранные действия.
3. Не объединять Casting/Release автоматически.
4. Использовать существующие identifier/evidence/conflict services там, где их контракт подходит.
5. Записать ChangeLog с причиной и actor.
6. Выполняться транзакционно; ошибка одного элемента не должна оставлять частично применённое состояние без отчёта.
7. Возвращать отчёт по каждому элементу: применён, пропущен, конфликт, ошибка.

## 7. Минимальная матрица приёмки

| Сценарий | Ожидаемое поведение |
|---|---|
| Повтор того же SourceRecord и claim | Нет дубля Evidence/действия; preview сообщает no-op |
| Другой SourceRecord с тем же значением | Отдельное наблюдение и Evidence |
| Один SKU в разных годах/контекстах | Conflict/review, не merge |
| Разные колёса или маркировка днища | Оба утверждения сохраняются, требуется review |
| Неизвестные поля | Остаются null/raw; значения не угадываются |
| Fandom и AllHW сообщают одно и то же | Два provenance claims; независимость источников не предполагается |
| Несколько кандидатов | `ambiguous`; никакого автоматического выбора |
| Preview без подтверждения | Ни одна каноническая запись не изменена |
| Ошибка apply | Транзакция откатывается или item-level результат явно отражает изоляцию ошибки |

## 8. Текущая реализация и следующий шаг

Сейчас существуют три read-only parser endpoints: Mainline TSV, local Fandom yearly HTML и All Hot Wheels saved-card HTML. Чистый in-memory adapter `preview_to_observations()` объединяет их результаты в versioned `hw_catalog.import_observation` envelope, сохраняя source fields, raw values, identifier hints и parser issues. Adapter не обращается к БД и сети.

GitHub Actions run #183 подтвердил adapter: `118 passed`, 4 warnings. В отдельной feature-ветке добавлен первый read-only matcher `match_import_observation()` и тесты. Он ищет exact source replay только при наличии source ID + content hash, сопоставляет exact identifier hints и exact name/catalog-year, возвращает объяснимые сигналы и статусы `exact_source_replay`, `strong_candidate`, `identifier_collision`, `ambiguous`, `no_match`. Parser observation пока не содержит persisted SourceRecord ID/content hash, поэтому replay detection через обычный adapter payload намеренно не предполагается.

Matcher использует только SELECT-запросы. Он не создаёт SourceRecord/Evidence/Conflict, не регистрирует identifiers, не меняет статусы и не объединяет сущности. Это первый matching slice, не полный preview diff и не importer orchestration.

Следующий шаг: прогнать CI, затем добавить explainable attribute diff между claims и выбранным Release, отдельно покрыв конфликтующие значения. Persistence/apply и UI остаются отдельными этапами.