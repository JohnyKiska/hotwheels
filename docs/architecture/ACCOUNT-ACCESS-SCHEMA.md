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

Модель `ExternalIdentity` должна хранить OAuth/OIDC identity по паре (`issuer`, `provider_subject`). Для email/password использовать отдельную сущность `PasswordCredential`, связанную с User, а не притворяться внешним OAuth-провайдером.

### PasswordCredential
- `id`, `user_id` FK RESTRICT (уникальная активная credential на пользователя).
- `password_hash`, `password_hash_algorithm`/параметры при необходимости.
- `created_at`, `updated_at`, `changed_at`, `disabled_at` nullable.

Пароли никогда не хранить в открытом виде и не шифровать обратимым способом. Использовать современный password hashing алгоритм (предпочтительно Argon2id; параметры выбирать по актуальным рекомендациям и возможностям хостинга). Сброс пароля выполняется одноразовым ограниченным по времени токеном, в БД хранится только его hash. Добавить rate limiting, защиту от перебора, нейтральные ответы на login/reset и аудит событий безопасности. MFA можно добавить отдельным этапом.

### EmailAddress и подтверждение
Email следует моделировать отдельно от OAuth identity, поскольку у пользователя могут быть несколько адресов и один primary:
- `EmailAddress`: `id`, `user_id`, `email_normalized`, `email_display`, `is_primary`, `verified_at`, `created_at`, `disabled_at`.
- глобальная уникальность `email_normalized` среди всех записей, включая отключённые. Адрес не удалять физически и не переиспользовать после отключения.
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
- `created_at`, `updated_at`, `last_login_at`, `closed_at` nullable.

Email не дублировать в User: единственный источник истины — `EmailAddress`; primary email определяется записью с `is_primary=true` и `verified_at IS NOT NULL`. Не хранить `is_admin` или `is_premium`: доступ определяется ролями и entitlements. При закрытии аккаунта сохранять стабильный User ID для ссылочной целостности и аудита, а профиль анонимизировать согласно политике хранения.

### ExternalIdentity
- `id`, `user_id` FK RESTRICT.
- `issuer` (точный доверенный issuer/идентификатор провайдера), `provider_subject` (стабильный subject; для GitHub — numeric ID).
- `provider` как нормализованный код (`github`, `google`).
- `provider_username`, `provider_email` как снимки профиля, не ключ идентичности.
- `created_at`, `last_authenticated_at`, `disabled_at` nullable.

Уникальность: (`issuer`, `provider_subject`). Для OIDC subject уникален в контексте issuer, а не только названия провайдера. GitHub username изменяем, поэтому не использовать его как primary key. OAuth access tokens по умолчанию не сохранять.

### Session
- `id` (случайный opaque token ID), `user_id` FK RESTRICT.
- `token_hash` (хранить hash, не исходный session token).
- `created_at`, `expires_at`, `last_seen_at`, `revoked_at`.
- `ip_hash`/краткая информация о клиенте — только если это действительно нужно для безопасности и политики приватности.

Индекс по `user_id`, уникальность `token_hash`, индекс по `expires_at`. Сессии отзываются сервером; cookies HttpOnly/Secure/SameSite. Если будет введено обновление сессий, refresh token rotation и reuse detection проектируются отдельным дополнением, а не добавляются автоматически.

### Invitation
- `id`, `email_normalized` nullable, `token_hash` unique, `created_by_user_id`, `accepted_by_user_id` nullable.
- `status`: `pending`, `accepted`, `revoked`, `expired`.
- `expires_at`, `accepted_at`, `created_at`.

Если приглашение ограничено email, пользователь обязан подтвердить владение именно этим адресом. Приглашение не назначает привилегированную роль. Начальный режим регистрации — invite-only; OAuth callback сам по себе не создаёт User без действительного приглашения или разрешения.

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
- `id` primary key, `user_id`, `role_id`, `assigned_by_user_id` nullable, `assigned_at`, `expires_at` nullable, `revoked_at` nullable, `revoked_by_user_id` nullable.
- Каждое назначение — историческая запись. При отзыве выставлять `revoked_at`; повторная выдача создаёт новую строку.
- Не допускать двух одновременно действующих назначений одной роли одному пользователю; проверять транзакционно.

Ограничения super admin серверные: нельзя снять, заблокировать или закрыть последнего активного super admin; назначение требует отдельного permission и подтверждения. Первый super admin создаётся одноразовой bootstrap-процедурой, сопоставляющей заранее заданный GitHub numeric ID с проверенной GitHub identity; после успешного выполнения bootstrap отключается.

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
- `id`, `user_id`, `plan_id`, `status`.
- `provider_code` и `provider_subscription_id`; до создания у провайдера допустимы только в состоянии `pending`. Уникальность внешнего ID в пределах провайдера.
- `plan_price_id` и snapshot цены/валюты/интервала.
- `current_period_start`, `current_period_end`, `cancel_at_period_end`, `canceled_at`, `ended_at`, `grace_until`, timestamps.

Subscription представляет платную recurring-подписку через провайдера. Ручная бесплатная выдача и промо-доступ моделируются через EntitlementGrant.

Статусы: `pending`, `active`, `past_due`, `canceled`, `expired`. При `cancel_at_period_end=true` доступ сохраняется до конца оплаченного `current_period_end`. При немедленной отмене доступ заканчивается в подтверждённый провайдером момент `ended_at`. Grace действует только до `grace_until`.

### EntitlementGrant
- `id`, `grant_batch_id`, `user_id`, `entitlement_id`.
- `value_json`, `starts_at`, `ends_at` nullable.
- `granted_by_user_id`, `reason`, `source` (`admin` или `promotion`), `source_reference` nullable, `revoked_at`, `revoked_by_user_id`.

Для «Premium целиком» одна операция создаёт несколько строк с общим `grant_batch_id`. Начальная модель additive-only: entitlements складываются из активных подписок и grants; deny/override пока не вводятся.

### SubscriptionEvent
- `id`, `subscription_id`, `event_type`, `occurred_at`, `actor_type`, `actor_user_id` nullable, `provider_event_id` nullable, `payload_summary` JSON.
- append-only: исправление — новая запись, не UPDATE/DELETE истории.

### Payment
- `id`, `user_id`, `subscription_id` nullable, `provider_code`, `provider_payment_id`, `amount_minor`, `currency`, `status`, `created_at`, `paid_at` nullable.
- Возвраты и частичные возвраты хранить отдельными связанными финансовыми событиями/записями с суммой, валютой, provider refund ID и временем.
- Уникальность внешнего payment ID в пределах провайдера. Не хранить PAN/CVV/полные карточные реквизиты.

### ProviderWebhookEvent
- `id`, `provider_code`, `provider_event_id`, `event_type`, `received_at`, `processed_at` nullable, `processing_status`, `failure_code` nullable, `attempt_count`, `payload_hash`.
- Уникальность (`provider_code`, `provider_event_id`). Проверять подпись до обработки; повтор события не должен повторно проводить бизнес-переход. Хранить hash и минимальную диагностическую сводку, не необработанный payload. Бизнес-изменение и отметка processed должны быть атомарны; ошибки допускают контролируемый retry.

## 6. Аудит

### AuditEvent
- `id`, `actor_user_id` nullable, `actor_type` (user/system/provider).
- `action`, `entity_type`, `entity_id`, `occurred_at`, `request_id`, `result`, `metadata` JSON.
- append-only, без токенов, секретов, платёжных реквизитов и лишних персональных данных.
- FK на actor желательно RESTRICT либо nullable при закрытии/анонимизации аккаунта; историю не удалять каскадно.

## 7. Правила вычисления доступа

1. Проверить, что User активен и сессия действительна.
2. RBAC вычислять из UserRole с `revoked_at IS NULL` и неистёкшим `expires_at`, затем через RolePermission.
3. Entitlements вычислять из действующих подписок и grants.
4. Начальная модель additive-only: отзыв одного grant не отменяет entitlement из другого активного источника.
5. При cancel-at-period-end доступ сохраняется до оплаченного конца; при немедленной отмене до `ended_at`; grace действует только до `grace_until`.
6. API проверяет права на сервере; скрытие кнопки во frontend не является контролем доступа.
7. Отмена/истечение Premium не удаляет аккаунт, коллекцию или данные пользователя.

## 8. Индексы и целостность

Минимум:
- unique: ExternalIdentity(issuer, provider_subject), Role.code, Permission.code, SubscriptionPlan.code, PlanPrice(plan_id, version), Entitlement.code, ProviderWebhookEvent(provider_code, provider_event_id), внешние payment/subscription IDs с учётом nullable;
- индексы FK и полей выборки: Session(user_id, expires_at), UserRole(user_id, role_id, revoked_at), Subscription(user_id, status), Subscription(current_period_end), EntitlementGrant(user_id, starts_at, ends_at), AuditEvent(occurred_at, actor_user_id), Payment(user_id, created_at);
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
- UX регистрации/приглашений, восстановления доступа и управления identity;
- сроки хранения финансовых и security-аудитных данных.

До принятия этих решений не создавать жёстко зашитые тарифы и entitlement codes, кроме технических тестовых данных.


## 11. Зафиксированные проектные решения после schema review

- `EmailAddress` — единственный источник primary email; поле `User.primary_email` не создаётся.
- Нормализованный email уникален глобально; отключённые адреса сохраняются и не переиспользуются.
- OIDC identity уникальна по паре `issuer + subject`.
- Назначения ролей исторические: отзыв через `revoked_at`, повторная выдача — новая строка.
- Subscription описывает платный recurring-договор; ручные/промо Premium выдаются через пакет EntitlementGrant.
- В первой версии entitlements additive-only, без deny overrides.
- Отмена подписки не отбирает уже оплаченный период.
- Регистрация на старте invite-only; публичный signup остаётся конфигурируемой политикой.
- Bootstrap Super Admin привязывается к заранее известному GitHub numeric ID и выполняется однократно.


## 12. Дополнительные технические гарантии перед реализацией

### Конкурентные операции и ограничения

- Назначение роли выполняется в транзакции: блокировать строку User (SELECT FOR UPDATE на PostgreSQL), проверить отсутствие действующего назначения и только затем вставить UserRole. На SQLite использовать транзакционный write-lock/повтор операции при конфликте. Это защищает от двух параллельных выдач одной роли.
- UserRole не получает переносимого partial-unique constraint на активную пару: правила активного назначения обеспечиваются сервисом и конкурентными тестами для обеих СУБД. Исторические строки остаются неизменными.
- PasswordCredential.user_id уникален: одна запись credential на User, отключение меняет disabled_at, а не создаёт вторую активную запись.
- EmailAddress.email_normalized имеет обычный глобальный UNIQUE, включая отключённые адреса. Повторное использование старого адреса запрещено.
- Для внешних ID платежа и подписки применять составную уникальность (provider_code, provider_*_id); nullable ID допустим только до присвоения провайдером. Пустую строку вместо NULL не использовать.
- Все операции, которые меняют права, способы входа, подписку или grants, должны быть атомарны и создавать соответствующий AuditEvent в той же транзакции.

### Сессии и токены

- Клиент получает криптографически случайный session token; в cookie передаётся только исходный token, в БД хранится его криптографический hash. Уникальный token_hash обязателен.
- Logout отзывает текущую сессию; функция «выйти на всех устройствах» отзывает все активные сессии пользователя. Проверка сессии всегда учитывает revoked_at и expires_at.
- Invitation, email verification и password reset используют отдельные токены с hash, сроком действия и одноразовым состоянием. Секреты токенов и исходные OAuth credentials не попадают в AuditEvent или логи.
- Для state/nonce/PKCE OAuth flow использовать серверную проверку и короткоживущий одноразовый контекст; это часть auth service, а не отдельная пользовательская сессия.

### Подписки и вычисление entitlements

- Snapshot цены в Subscription является неизменяемым снимком согласованных условий на момент оформления. Изменение PlanPrice не меняет действующие подписки.
- PlanPrice.valid_from/valid_until определяют возможность оформить новую подписку по этой цене; после оформления источник истины для договора — snapshot Subscription.
- Resolver сначала проверяет статус User, затем определяет временную действительность каждого источника доступа. canceled с cancel_at_period_end=true сохраняет доступ до current_period_end; ended_at немедленно завершает доступ; past_due даёт доступ только в явно заданном grace window. Истёкший или отозванный источник не предоставляет entitlement.
- Если несколько действующих источников дают один entitlement, применяется объединение по типу значения: boolean — OR; числовой лимит — максимум; конфигурационные значения до появления конкретного продукта не объединять автоматически. Конфликтующие типы/значения должны приводить к ошибке конфигурации, а не к случайному выбору.
- PlanEntitlement.value_json и EntitlementGrant.value_json валидируются приложением по Entitlement.value_type. Не интерпретировать произвольный JSON как executable configuration.
- Ручная выдача Premium пакетом создаёт строки EntitlementGrant в одной транзакции с общим grant_batch_id; отзыв пакета отзывает все его строки атомарно. Отзыв одной строки не затрагивает независимые источники доступа.

### Платежи и webhook

- Webhook обрабатывается только после проверки подписи и допустимого временного окна. Уникальный (provider_code, provider_event_id) обеспечивает идемпотентность повторной доставки.
- Сохранение ProviderWebhookEvent, изменение Subscription/Payment, запись SubscriptionEvent и AuditEvent выполняются в одной транзакции. При ошибке транзакция откатывается; состояние retry и диагностический код сохраняются отдельной безопасной операцией.
- Порядок и время доставки webhook не считать гарантированными: обработчик проверяет актуальное состояние/версию объекта у провайдера либо применяет монотонные переходы статусов, чтобы позднее событие не вернуло подписку в старое состояние.
- Возврат/частичный возврат оформляется отдельной сущностью финансового события с уникальным provider refund ID и суммой в minor units. Исходный Payment не переписывается так, будто оплаты не было.
- Не хранить полный payload webhook по умолчанию. Для расследования достаточно hash, типа события, provider IDs, времён, статуса и безопасного кода ошибки.

### Закрытие аккаунта, аудит и bootstrap

- Закрытие аккаунта — явная операция: отозвать сессии, запретить вход, отключить способы аутентификации согласно политике восстановления, прекратить будущие списания через провайдера и зафиксировать событие аудита. Закрытие не должно молча удалять финансовые записи, каталог или историю решений.
- Анонимизация профиля и сроки хранения EmailAddress, финансовых записей и security audit определяются отдельной retention policy с учётом применимого законодательства. До утверждения политики не реализовывать безусловное физическое удаление аккаунтов и не обещать бессрочное хранение персональных данных.
- AuditEvent.metadata — allowlist полей по типу события; не включать пароли, токены, полные email без необходимости, IP в открытом виде или платёжные реквизиты.
- Bootstrap Super Admin должен проверить одновременно ожидаемый GitHub numeric subject и issuer/provider, быть одноразовым и оставлять AuditEvent. Совпадения username или email недостаточно. После bootstrap механизм отключается конфигурацией окружения.
- Начальные системные Role/Permission и их связи создаются идемпотентным seed/migration. Отсутствие административной роли у обычного User является нормальным состоянием: пользовательский аккаунт и личная коллекция не требуют RBAC-роли.
- Последний активный Super Admin защищается от снятия роли, блокировки и закрытия аккаунта в одной транзакции с блокировкой/проверкой остальных активных Super Admin.

### Порядок тестирования

- Для каждой миграции проверить чистую БД и upgrade существующей БД.
- Для SQLite и PostgreSQL 16 отдельно проверить ограничения уникальности, FK RESTRICT, транзакционные гонки UserRole, timezone round-trip и rollback атомарных операций.
- Полный backend suite запускать на обеих СУБД. Успешный migration smoke test PostgreSQL не считать подтверждением полной совместимости.
- OAuth, email delivery и платёжный provider покрывать контрактными тестами с mock provider; реальные секреты и реальные платежи в CI не использовать.
