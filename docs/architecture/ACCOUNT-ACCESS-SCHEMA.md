# HW Catalog — схема аккаунтов, доступа и Premium

Дата: 2026-11-12  
Статус: проект схемы для обсуждения; не является миграцией и не создаёт таблицы.

## 1. Цели и границы

Схема должна поддерживать:
- вход через GitHub OAuth сейчас и добавление других identity providers без создания второго аккаунта;
- закрытый доступ по приглашению/разрешению администратора;
- собственные роли и permissions HW Catalog;
- коммерческие тарифы и Premium entitlements независимо от RBAC;
- платную периодическую подписку и ручную бесплатную выдачу;
- аудит административных и коммерческих действий;
- PostgreSQL как целевую БД и перенос без изменения API.

Каталожные JSON и GitHub Repository adapter не входят в эту схему. Секреты OAuth, GitHub App и платёжного провайдера хранятся в secret manager окружения, не в таблицах и не в репозитории.

## 2. Связи верхнего уровня

```text
User 1---N ExternalIdentity
User N---M Role (через UserRole)
Role N---M Permission (через RolePermission)

User 1---N Session
User 1---N Invitation (created_by / accepted_by)

SubscriptionPlan 1---N Subscription
SubscriptionPlan N---M Entitlement (через PlanEntitlement)
User 1---N Subscription
User 1---N EntitlementGrant
Subscription 1---N SubscriptionEvent
Subscription 1---N Payment
ProviderWebhookEvent — журнал входящих событий провайдера
User 1---N AuditEvent (actor)
```

## Поддерживаемые способы входа

HW Catalog должен поддерживать несколько независимых способов аутентификации, привязанных к одному User:

- GitHub OAuth;
- Google OAuth / OpenID Connect;
- email + пароль.

Модель `ExternalIdentity` должна хранить OAuth/OIDC identity по паре (`provider`, `provider_subject`). Для email/password использовать отдельную сущность `PasswordCredential`, связанную с User, а не притворяться внешним OAuth-провайдером.

### PasswordCredential
- `id`, `user_id` FK RESTRICT (уникальная активная credential на пользователя).
- `password_hash`, `password_hash_algorithm`/параметры при необходимости.
- `created_at`, `updated_at`, `changed_at`, `disabled_at` nullable.

Пароли никогда не хранить в открытом виде и не шифровать обратимым способом. Использовать современный password hashing алгоритм (предпочтительно Argon2id; параметры выбирать по актуальным рекомендациям и возможностям хостинга). Сброс пароля выполняется одноразовым ограниченным по времени токеном, в БД хранится только его hash. Добавить rate limiting, защиту от перебора, нейтральные ответы на login/reset и аудит событий безопасности. MFA можно добавить отдельным этапом.

### EmailAddress и подтверждение
Email следует моделировать отдельно от OAuth identity, поскольку у пользователя могут быть несколько адресов и один primary:
- `EmailAddress`: `id`, `user_id`, `email_normalized`, `email_display`, `is_primary`, `verified_at`, `created_at`, `disabled_at`.
- уникальный индекс по нормализованному адресу для активных записей (с учётом возможностей целевой БД);
- `EmailVerificationToken`: hash токена, срок действия, использован/отозван, дата отправки.

Email от OAuth-провайдера считается подтверждённым только если провайдер достоверно сообщает verified status. Не полагаться на username или непроверенный email. Правила нормализации должны быть консервативными: не удалять точки/плюсы и не применять провайдер-специфичные догадки.

### Привязка и объединение identity
- В настройках аккаунта пользователь может подключить или отключить OAuth identity после повторной аутентификации.
- Нельзя удалить последний действующий способ входа, если не настроен другой способ восстановления.
- Автоматически объединять User по совпавшему email запрещено.
- Для связывания identity с существующим User требуется активная сессия и повторное подтверждение нового провайдера; перенос identity с другого User требует подтверждения владения обоими аккаунтами и отдельной аудируемой операции.
- Если OAuth callback возвращает identity, уже принадлежащую другому User, входить в исходный User; не перепривязывать её молча.
- Смена primary email и сброс пароля требуют подтверждения и создают AuditEvent.

## 3. Таблицы аккаунтов и идентификации

### User
- `id`: UUID/opaque string, primary key.
- `status`: `pending`, `active`, `suspended`, `closed`.
- `display_name`: nullable.
- `primary_email`: nullable; подтверждение и уникальность учитывать только после проверки email.
- `created_at`, `updated_at`, `last_login_at`.

Не хранить `is_admin` или `is_premium`: доступ определяется связями ролей и entitlements. Закрытие аккаунта не должно каскадно удалять историю аудита, платежей и каталожных пользовательских данных.

### ExternalIdentity
- `id`, `user_id` FK RESTRICT.
- `provider` (например, `github`), `provider_subject` (стабильный numeric ID провайдера).
- `provider_username`, `provider_email` как снимки профиля, не ключ идентичности.
- `created_at`, `last_authenticated_at`.

Уникальность: (`provider`, `provider_subject`). Один User может иметь несколько identity. GitHub username изменяем, поэтому не использовать его как primary key. OAuth access tokens по умолчанию не сохранять, если отдельная функция приложения не требует этого.

### Session
- `id` (случайный opaque token ID), `user_id` FK RESTRICT.
- `token_hash` (хранить hash, не исходный session token).
- `created_at`, `expires_at`, `last_seen_at`, `revoked_at`.
- `ip_hash`/краткая информация о клиенте — только если это действительно нужно для безопасности и политики приватности.

Индекс по `user_id`, уникальность `token_hash`, индекс по `expires_at`. Сессии отзываются сервером; cookies HttpOnly/Secure/SameSite. Если будет введено обновление сессий, refresh token rotation и reuse detection проектируются отдельным дополнением, а не добавляются автоматически.

### Invitation
- `id`, `email` nullable, `token_hash`, `created_by_user_id`, `accepted_by_user_id` nullable.
- `status`: `pending`, `accepted`, `revoked`, `expired`.
- `expires_at`, `accepted_at`, `created_at`.

Приглашение не назначает привилегированную роль само по себе. Роль/permissions выдаются отдельной операцией с аудитом. Хранить только hash токена.

## 4. RBAC

### Role
- `id`, `code` (unique), `name`, `description`, `is_system`, timestamps.

Начальные коды: `super_admin`, `admin`, `editor`, `reviewer`, `viewer`. Системные роли нельзя случайно удалить. Реальные проверки выполнять по permissions, а не сравнением строк роли в каждом endpoint.

### Permission
- `id`, `code` (unique), `description`, `scope`/resource/action при необходимости.

Примеры кодов: `catalog.read`, `catalog.create`, `catalog.update`, `catalog.delete`, `catalog.review`, `users.read`, `users.manage`, `roles.assign`, `billing.manage`, `settings.manage`.

### RolePermission
- составной PK (`role_id`, `permission_id`), оба FK RESTRICT.

### UserRole
- составной PK (`user_id`, `role_id`), `assigned_by_user_id` nullable, `assigned_at`, `expires_at` nullable.
- При отзыве роли предпочтительно сохранять событие в AuditEvent; действующее назначение можно удалить или закрыть через `revoked_at`, решение закрепить до реализации.

Ограничения super admin должны быть серверными: нельзя снять последнего активного super admin; нельзя назначить super admin без отдельного permission/подтверждения. Первый super admin создаётся bootstrap-процедурой по GitHub numeric ID из серверной конфигурации, а не публичным signup.

## 5. Тарифы и entitlements

### SubscriptionPlan
- `id`, `code` unique, `name`, `description`, `is_active`.
- Период/цена задаются через отдельную версию цены, чтобы изменение цены не переписывало существующие договорённости.

### PlanPrice
- `id`, `plan_id`, `version`, `amount_minor` (целое число в минимальных единицах валюты), `currency` (ISO 4217), `billing_interval`, `interval_count`, `valid_from`, `valid_until` nullable.
- Уникальность (`plan_id`, `version`). Не использовать float для денег. Подписка сохраняет snapshot применённой цены/валюты/периода.

### Entitlement
- `id`, `code` unique, `name`, `description`, `value_type` (например boolean, integer limit, text/config).
- Коды возможностей стабильны; отображаемые названия можно менять.

### PlanEntitlement
- составной PK (`plan_id`, `entitlement_id`).
- `value_json` или типизированные поля значения; выбрать один единый формат после определения первых реальных функций.
- Отсутствующая запись означает, что план не предоставляет entitlement.

### Subscription
- `id`, `user_id`, `plan_id`, `status`, `source` (`provider`, `admin`, `promotion`).
- `provider_code` и `provider_subscription_id` nullable; уникальность внешнего ID в пределах провайдера.
- `current_period_start`, `current_period_end`, `cancel_at_period_end`, `canceled_at`, `ended_at`, `grace_until`.
- snapshot цены/валюты/интервала, действовавших при оформлении.
- Время хранить timezone-aware в UTC; правила отображения локального времени оставить frontend.

Статусы как минимум: `pending`, `active`, `past_due`, `canceled`, `expired`. Grace period лучше моделировать отдельным `grace_until`, а не отдельным статусом, чтобы не смешивать состояние оплаты и временное право доступа. Допустимые переходы определить в сервисе и тестах.

### EntitlementGrant
- `id`, `user_id`, `entitlement_id` (или ссылка на набор/план, если будет утверждён такой сценарий).
- `value_json`, `starts_at`, `ends_at` nullable.
- `granted_by_user_id`, `reason`, `revoked_at`, `revoked_by_user_id`.

Это отдельная аудируемая выдача, а не фиктивная платная подписка. Поддерживает временный, бессрочный и отозванный grant. Если потребуется «подарить Premium целиком», администратор выдаёт согласованный набор entitlements либо специальный grant на пакет, но не присваивает роль.

### SubscriptionEvent
- `id`, `subscription_id`, `event_type`, `occurred_at`, `actor_type`, `actor_user_id` nullable, `provider_event_id` nullable, `payload_summary` JSON.
- append-only: исправление — новая запись, не UPDATE/DELETE истории.

### Payment
- `id`, `user_id`, `subscription_id` nullable, `provider_code`, `provider_payment_id`, `amount_minor`, `currency`, `status`, `created_at`, `paid_at` nullable, `refunded_at` nullable.
- Уникальность внешнего payment ID в пределах провайдера. Сохранять только безопасные метаданные; не хранить PAN/CVV/полные карточные реквизиты.

### ProviderWebhookEvent
- `id`, `provider_code`, `provider_event_id`, `event_type`, `received_at`, `processed_at` nullable, `processing_status`, `failure_code` nullable.
- Уникальность (`provider_code`, `provider_event_id`) для идемпотентности. Проверка подписи выполняется до обработки; повтор события не должен повторно проводить бизнес-переход.

## 6. Аудит

### AuditEvent
- `id`, `actor_user_id` nullable, `actor_type` (user/system/provider).
- `action`, `entity_type`, `entity_id`, `occurred_at`, `request_id`, `result`, `metadata` JSON.
- append-only, без токенов, секретов, платёжных реквизитов и лишних персональных данных.
- FK на actor желательно RESTRICT либо nullable при закрытии/анонимизации аккаунта; историю не удалять каскадно.

## 7. Правила вычисления доступа

1. Сначала проверить, что User активен и сессия действительна.
2. RBAC permissions вычисляются из действующих UserRole → RolePermission.
3. Entitlements вычисляются отдельно из подписок в действующем периоде (включая grace до `grace_until`) и действующих EntitlementGrant.
4. При конфликте grants/плана нужно определить явный приоритет revoke/deny до появления таких override-сценариев. Не трактовать отсутствие записи как deny override.
5. API проверяет права на сервере; скрытие кнопки во frontend не является контролем доступа.
6. Отмена/истечение Premium не удаляет аккаунт, коллекцию или данные пользователя.

## 8. Индексы и целостность

Минимум:
- unique: ExternalIdentity(provider, provider_subject), Role.code, Permission.code, SubscriptionPlan.code, PlanPrice(plan_id, version), Entitlement.code, ProviderWebhookEvent(provider_code, provider_event_id), внешние payment/subscription IDs с учётом nullable;
- индексы FK и полей выборки: Session(user_id, expires_at), UserRole(user_id), Subscription(user_id, status), Subscription(current_period_end), EntitlementGrant(user_id, starts_at, ends_at), AuditEvent(occurred_at, actor_user_id), Payment(user_id, created_at);
- FK для финансовой и аудиторской истории преимущественно RESTRICT; CASCADE применять только для чисто технических связей вроде RolePermission;
- все даты timezone-aware, хранить UTC; PostgreSQL проверять отдельно, поскольку SQLite не обеспечивает одинаковую семантику timezone-aware DateTime.

## 9. Порядок реализации

1. Утвердить этот контракт и закрыть открытые продуктовые решения, не блокирующие базовую схему.
2. Реализовать модели и миграции отдельными небольшими шагами: User/Identity, RBAC, Session/Invitation/Audit, затем Subscription/Entitlement.
3. Добавить тесты ограничений, закрытия/отзыва, конкурирующих операций, временных границ и идемпотентности webhook.
4. Проверить чистый Alembic upgrade и upgrade существующей БД на SQLite и PostgreSQL 16; затем полный backend suite на PostgreSQL.
5. Только после этого подключать OAuth и API dependencies. Биллинг-провайдера реализовывать отдельным этапом.

## 10. Вопросы, оставленные открытыми

Не блокируют базовый каркас:
- окончательный набор Premium-функций и их лимиты;
- цены, валюта, длительность и доступные планы;
- платёжный провайдер и доступные способы оплаты;
- точная политика grace period, возвратов и read-only доступа после истечения;
- нужны ли email/password или другие OAuth providers помимо GitHub.

До принятия этих решений не создавать жёстко зашитые тарифы и entitlement codes, кроме технических тестовых данных.
