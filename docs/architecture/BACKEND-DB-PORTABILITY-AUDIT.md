# Backend database portability audit

Дата: 2026-11-12  
Ветка: `integration/catalog-foundation`  
Область: текущие SQLAlchemy models, DB engine и Alembic migrations. Это статический аудит исходников; тестовый прогон на PostgreSQL ещё не выполнялся.

## Итог

Текущая ORM-модель в целом использует переносимые SQLAlchemy-типы и UUID-строки, поэтому переход на PostgreSQL реалистичен. Но backend пока нельзя безопасно переключить на PostgreSQL одной заменой `DATABASE_URL`. Есть несколько конкретных SQLite-зависимостей и пробел в миграционной истории.

## Найденные блокеры

### 1. Engine всегда передаёт SQLite connect argument

Файл: `backend/app/db.py`

Сейчас `create_engine()` всегда получает `connect_args={"check_same_thread": False}`. Это параметр sqlite-драйвера, не универсальный параметр DBAPI. При PostgreSQL URL он может привести к ошибке подключения.

Решение: выбирать connect_args по dialect URL; для PostgreSQL не передавать sqlite-параметры. SQLite foreign-key PRAGMA listener также должен выполняться только для SQLite.

### 2. Alembic migration chain не создаёт core catalog tables

Файлы: `backend/migrations/versions/20261026_evidence_layer.py` и последующие.

Первая миграция имеет `down_revision = None`, но создаёт только evidence/source/conflict/media/change-log таблицы. Core tables (`castings`, `casting_variants`, `series`, `releases`, `release_series`) в списке отсутствуют. Текущий `init_db` отдельно вызывает metadata create_all, что может скрывать проблему при локальной разработке, но не является воспроизводимым Alembic bootstrap для чистой БД.

Решение: добавить начальную миграцию core schema перед evidence migration либо пересобрать цепочку как корректную baseline migration. Существующие базы нельзя ломать: перед изменением цепочки проверить фактические alembic_version и поддерживаемые способы инициализации.

### 3. Append-only triggers используют SQLite SQL

Файл: `backend/migrations/versions/20261027_change_log_append_only.py`

Триггеры с `RAISE(ABORT,...)` и синтаксисом SQLite не выполнятся в PostgreSQL.

Решение: реализовать dialect-aware migration: PostgreSQL trigger function + trigger, SQLite оставить текущую реализацию. Downgrade также должен ветвиться по dialect.

### 4. Boolean seed использует integer literals

Файл: `backend/migrations/versions/20261027_catalog_identifiers.py`

Вставка `0` в boolean `is_globally_unique` совместима с SQLite, но не является корректным portable SQL для PostgreSQL.

Решение: использовать bind parameters или dialect-aware boolean literals (`FALSE` для PostgreSQL, `0` для SQLite).

## Дополнительные замечания

- `JSON`, `String`, `Text`, `Integer`, `DateTime` и большинство FK/unique/check constraints в моделях поддерживаются SQLAlchemy для SQLite и PostgreSQL.
- Модель использует UUID как строку длиной 36 символов. Это переносимо, хотя позже можно рассмотреть native UUID type без изменения внешних opaque IDs.
- `DateTime(timezone=True)` следует проверить на round-trip тестах: SQLite не сохраняет timezone semantics так же, как PostgreSQL.
- `DATABASE_URL` уже является правильной точкой конфигурации для будущей БД; текущий resolver следует сохранить, но проверить на managed PostgreSQL URL/SSL параметры.
- Нельзя использовать `Base.metadata.create_all()` как production migration mechanism. Только Alembic migrations.
- Текущие таблицы пользователя/ролей ещё не существуют. Их следует добавлять отдельной additive migration после исправления базовой migration chain.
- Audit `ChangeLog` сейчас имеет actor_type/actor_id, но не полноценную ссылку на пользователя. Будущие user audit events лучше хранить отдельной таблицей с FK на User, не меняя смысл исторических catalog ChangeLog rows без отдельного плана.

## План исправления перед PostgreSQL staging

1. Зафиксировать текущее состояние схемы и revision IDs на копии текущей dev DB.
2. Проверить чистый SQLite bootstrap только через `alembic upgrade head`.
3. Добавить/исправить core baseline так, чтобы новая пустая БД полностью создавалась Alembic.
4. Сделать engine и PRAGMA dialect-aware.
5. Сделать append-only migration и boolean seed dialect-aware.
6. Добавить PostgreSQL в CI service matrix и прогнать все backend tests на обеих БД.
7. Добавить auth/RBAC schema только после зелёного migration test на пустой и существующей SQLite DB и на PostgreSQL.
8. Сохранить отдельную резервную копию БД перед любой миграцией на staging.

## Ограничение

Этот документ не означает, что PostgreSQL уже поддерживается. Он фиксирует объём работ и конкретные места, которые необходимо исправить и проверить.
