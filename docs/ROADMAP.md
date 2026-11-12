# HW Catalog · дорожная карта консолидации

## Этап 1. Зафиксировать новую основу

- [x] Создать интеграционную ветку от `prototype/catalog-visual-v1`.
- [x] Сохранить прежний `main` в архивной ветке.
- [x] Перенести визуальный каталог в корневой `index.html` интеграционной ветки.
- [x] Перенести редактор схемы рядом с корневой страницей.
- [x] Зафиксировать правила и состояние проекта в документации.

## Этап 2. Перенести drag & drop

- [ ] Выделить механику drag & drop из `catalog/editor.html`.
- [ ] Сопоставить типы узлов, допустимые связи и DOM-структуру с новым каталогом.
- [ ] Перенести только необходимые обработчики и визуальные состояния.
- [ ] Сохранить проверки допустимости перемещения и защиты от циклов.
- [ ] Добавить предварительный просмотр изменения связи до подтверждения.
- [ ] Проверить работу мышью, прокрутку во время перетаскивания и поведение на узких экранах.
- [ ] Убедиться, что drag & drop не обходит валидацию и не записывает данные без подтверждения.

## Этап 3. Аудит backend и данных

- [ ] Сравнить backend и каталожные данные между `main` и `prototype/catalog-visual-v1`.
- [ ] Выбрать актуальные изменения backend, миграции, API и тесты.
- [ ] Проверить соответствие модели Casting / Release / Package.
- [ ] Сохранить provenance, Evidence, конфликты и историю решений.
- [ ] Проверить, что импорт не перезаписывает подтверждённые значения и не объединяет записи без достаточных оснований.

## Этап 4. ALLHW и импортеры

- [ ] Инвентаризировать все файлы `ALLHW` в `feature/scheduled-market-data`.
- [ ] Сохранить исходные HTML и изображения без переименования и изменения байтов.
- [ ] Отдельно оценить JSON-выгрузки, парсеры, тесты и workflows.
- [ ] Перенести только совместимые компоненты.
- [ ] Не выполнять полный merge `feature/scheduled-market-data`.
- [ ] Учитывать, что Fandom и AllHW могут не быть независимыми источниками.

## Этап 5. Проверка и переход в main

- [ ] Проверить ссылки, пути к ресурсам и GitHub Pages.
- [ ] Проверить интерфейс в браузере, включая таблицу без фотографий, фильтры и карточки.
- [ ] Запустить backend- и UI-тесты.
- [ ] Провести проверку миграций и целостности данных.
- [ ] Открыть PR из `integration/catalog-foundation` в `main`.
- [ ] Обсудить состав PR и только после согласования выполнить merge.

## Этап 6. Архив и уборка

- [ ] Составить карту веток: актуальные, архивные, кандидаты на удаление.
- [ ] Перенести ценные исторические ветки в согласованный архивный контур.
- [ ] Проверить, что архив содержит нужные исходники и историю.
- [ ] Только после отдельного подтверждения удалять ненужные ветки.


## Этап 6. Архив и уборка · обновлено 2026-11-04

- [x] Составить карту актуальных и исторических веток.
- [x] Создать архивные копии 82 исторических веток в `archive/2026-11-04/<исходное-имя-ветки>`.
- [x] Сверить SHA архивных копий с исходными ветками.
- [x] Сохранить `prototype/catalog-visual-v1` и `integration/catalog-foundation` как рабочие.
- [ ] Отдельно согласовать удаление исходных refs после проверки архива.
- [ ] После проверки приложения решить, когда переключать default branch и GitHub Pages с `main`.

## Backend consolidation · 2026-11-04

- [x] Выборочно перенести идемпотентность Evidence из PR #72.
- [x] Добавить связь `ConflictRelease` и migration поверх текущей integration schema.
- [x] Перенести traceability конфликтов, историю решений и audited revision endpoint из PR #73.
- [x] Обновить страницу очереди конфликтов.
- [x] Проверить Backend tests: 92 passed.
- [x] Проверить Catalog UI checks: success.
- [x] Проверить и смержить PR #80 в `integration/catalog-foundation`.
- [x] Выборочно восстановить read-only импортёры из PR #74 в PR #81; не переносить старые модели и миграции целиком.

## Importer recovery · 2026-11-04

- [x] Create isolated branch `integration/importers-safe-preview` from the updated `integration/catalog-foundation`.
- [x] Restore Mainline TSV parser as read-only preview.
- [x] Restore local Fandom yearly HTML parser as read-only preview; no network fetch path.
- [x] Restore All Hot Wheels saved-card HTML parser as read-only preview.
- [x] Add preview-only API endpoints and synthetic parser/API tests.
- [x] Preserve Mainline importer specification, synthetic fixture plan/data, and All Hot Wheels importer documentation.
- [x] Run GitHub Actions on importer code: 113 passed, 4 warnings (run #179).
- [ ] Review source-level parser behavior against representative local HTML files from `ALLHW` without network access.
- [x] Define the shared observation contract and implement pure in-memory adapters for all three preview sources.
- [x] Validate the adapter with GitHub Actions run #183: 118 passed, 4 warnings.
- [ ] Design a read-only matcher and explainable preview diff before adding DB writes.
- [ ] Separately assess ProductLine/Package/Brand/Origin model additions and safe additive migrations; do not merge PR #74 wholesale.

## PR cleanup · 2026-11-04

- [x] Merge PR #81 into `integration/catalog-foundation` after successful backend CI (113 passed, 4 warnings).
- [x] Preserve the useful hierarchy and release-lineage design notes in `docs/architecture/`.
- [x] Close superseded PRs #1, #29, #59, #70, #71, #72, #73, #74, #78 and #79.
- [x] Keep archive branches and historical refs; no branch deletion performed.
- [ ] Review saved local ALLHW HTML against the committed parsers without network access.
- [ ] Design the shared observation/matching/confirmation/apply pipeline.
- [ ] Revisit Package, Manufacturer/Brand, ProductLine/CatalogNode and Origin models with safe additive migrations.


## Import matching · 2026-11-04

- [x] Реализовать первый read-only Release matcher поверх существующих моделей и identifier services (без вызова write-сервисов).
- [x] Возвращать объяснимые сигналы и состояния exact replay / strong candidate / collision / ambiguous / no match.
- [x] Добавить тесты на безопасный identifier lookup, exact name+catalog year, collisions, неизвестный namespace и replay по source ID + content hash.
- [x] Подтвердить GitHub Actions для matcher branch: run #184, 124 passed, 4 warnings.
- [x] Merge PR #83 в `integration/catalog-foundation`; `main` не изменён.
- [ ] Реализовать explainable claim-to-Release attribute diff (same / new evidence / conflicting value / insufficient evidence).
- [ ] Подключить read-only preview API только после стабилизации matcher/diff contracts.
- [ ] Отдельно спроектировать persistence, confirmation и apply; никаких автоматических merges.


## Claim preview diff · 2026-11-04

- [x] Добавить pure in-memory claim diff для явно выбранного Release.
- [x] Разделить совпадающие значения, новые evidence claims, conflicts, evidence-only и insufficient evidence.
- [x] Не допускать автоматической перезаписи canonical значений.
- [ ] Подтвердить GitHub Actions для claim diff branch.
- [ ] Спроектировать read-only preview API, который связывает parser → observation → matcher → diff.
- [ ] Только после этого отдельно проектировать persistence/confirmation/apply.


## Claim preview diff validation · 2026-11-04

- [x] GitHub Actions run #187: 131 passed, 4 warnings.
- [x] Merge PR #84 в `integration/catalog-foundation` (squash `058ac4ffc6da11284dc2f97414203e3299b4459b`).
- [ ] Спроектировать read-only preview API orchestration parser → observation → matcher → diff.


## Pipeline preview API · 2026-11-04

- [x] Добавить read-only orchestration endpoint parser → observation → matcher → optional diff.
- [x] Поддержать Mainline TSV, локальный Fandom yearly HTML и локальный All Hot Wheels HTML.
- [x] Для multi-row inputs потребовать явный record index; для attribute diff — явный Release ID.
- [x] Проверять, что endpoint не создаёт SourceRecord/Evidence/Conflict и не меняет Release.
- [ ] Подтвердить GitHub Actions для API branch.
- [ ] После CI спроектировать UX для просмотра parser issues, candidate signals и claim diff.
- [ ] Persistence/confirmation/apply остаются отдельной задачей после UI review.


## Pipeline preview API validation · 2026-11-04

- [x] GitHub Actions run #188: 138 passed, 4 warnings.
- [x] Merge PR #85 в `integration/catalog-foundation` (squash `c787696e9dc25abfc985de485710fd8f2569d0aa`).
- [ ] Изучить существующий frontend admin workflow и подключить read-only preview UI без persistence/apply.

## Admin foundation · 2026-11-12

- [x] Зафиксировать целевую архитектуру: существующий FastAPI как единственный backend, GitHub OAuth для идентификации, собственный RBAC, GitHub Repository adapter для временного хранения каталога.
- [x] Зафиксировать принцип переноса: API и доменная логика не зависят от провайдера размещения; будущая SQL-БД — PostgreSQL.
- [x] Выполнить статический аудит SQLAlchemy-моделей и Alembic migrations на совместимость с PostgreSQL.
- [x] Исправить SQLite-only connect_args/PRAGMA в engine и сделать их dialect-aware.
- [x] Восстановить полный Alembic bootstrap для core catalog schema на чистой БД.
- [x] Сделать append-only triggers и boolean seed совместимыми с SQLite и PostgreSQL.
- [x] Добавить migration tests на пустой и существующей SQLite БД; подключить PostgreSQL migration/trigger smoke tests в CI.
- [ ] Только после portability gate добавлять auth/RBAC schema.
- [ ] Спроектировать и добавить User, ExternalIdentity, Role, Permission, UserRole, Session и AuditEvent.
- [ ] Реализовать закрытый GitHub OAuth flow и одноразовое назначение первого Super Admin.
- [ ] Закрыть все изменяющие API endpoints RBAC-проверками и тестами.
- [ ] Реализовать серверный GitHub App adapter с минимальными правами и optimistic concurrency.
- [ ] Добавить страницы Login и Admin в существующий frontend.
- [ ] Выбрать временный backend host и managed PostgreSQL, настроить staging и backup/restore.
- [ ] Подключать frontend к API только после проверки авторизации, CORS и доступа.

**Проверка DB portability · 2026-11-12:** GitHub Actions run #253: 165 passed, 6 warnings; PostgreSQL 16 clean Alembic upgrade и повторный upgrade прошли; PostgreSQL отклоняет UPDATE/DELETE в change_log. SQLite clean bootstrap и upgrade существующей БД с сохранением записи проверены отдельными тестами. Полный набор backend-тестов на PostgreSQL пока не запускался.

Архитектурное решение: `docs/architecture/FOUNDATION-ADR-001.md`.\n\nРезультат статического DB portability audit: `docs/architecture/BACKEND-DB-PORTABILITY-AUDIT.md`.

Важно: Cloudflare Workers не добавляем как второй backend. Используем существующий FastAPI и переносим его между хостингами без изменения API.

## Premium и коммерческие entitlements · 2026-11-12

- [x] Зафиксировать разделение RBAC (административные права) и entitlements (доступ к функциям продукта).
- [x] Предусмотреть архитектуру тарифов, возможностей, подписок, платежей, событий провайдера и аудируемых ручных Premium grants.
- [x] Зафиксировать поддержку платной recurring-подписки и бесплатной/комплиментарной выдачи администратором.
- [x] Оставить список Premium-функций, цены, валюты, периоды и платёжного провайдера открытыми до продуктового решения.
- [ ] Спроектировать единую схему User/RBAC + Subscription/Entitlement до создания auth migrations.
- [ ] Определить продуктовый список Premium-функций, тарифы, цены и правила доступа после отмены/истечения подписки.
- [ ] Выбрать платёжного провайдера и описать webhook, идемпотентность, возвраты и обработку неуспешных платежей.
- [ ] Реализовать entitlement resolver и ручные grants с аудитом.
- [ ] Реализовать платёжную интеграцию отдельным этапом после OAuth/RBAC и тестов доступа.

Архитектурные правила Premium зафиксированы в `docs/architecture/FOUNDATION-ADR-001.md`, раздел «Коммерческий доступ: планы, подписки и Premium».


## Account identity, RBAC and account security implementation · 2026-11-12

- [x] Добавить SQLAlchemy-модели User, ExternalIdentity, EmailAddress и PasswordCredential.
- [x] Добавить Role, Permission, RolePermission и историческую UserRole.
- [x] Добавить Alembic migration с идемпотентным seed системных ролей, permissions и матрицы прав.
- [x] Добавить модельные тесты уникальности identity/email/credential, FK, статусов и истории назначения ролей.
- [x] Добавить UserSession с хранением только hash токена, сроком действия и отзывом.
- [x] Добавить Invitation с hash одноразового токена, статусом, сроком действия и связью с приглашённым пользователем/ролью.
- [x] Добавить EmailVerificationToken с hash токена, сроком действия и отметкой однократного использования.
- [x] Добавить AuditEvent и защиту append-only на уровне SQLite/PostgreSQL.
- [x] Добавить отдельную Alembic migration для сессий, приглашений, email verification и account audit.
- [x] Добавить модельные тесты и проверку неизменяемости AuditEvent.
- [ ] Проверить полный CI после последних изменений; устранить найденные ошибки.
- [ ] Реализовать сервисы создания User, linking identity и транзакционного назначения/отзыва ролей.
- [ ] Реализовать session lifecycle, invitation acceptance и email verification services.
- [ ] Затем подключить OAuth/email-password flows и API permission dependencies.

Модели и миграции persistence-слоя добавлены, но authentication flows, выдача/проверка сессий, отправка email, OAuth callbacks и API authorization ещё не реализованы. Миграция не выдаёт Super Admin автоматически: bootstrap будет отдельным защищённым шагом.

### Account Lifecycle и очистка неактивных аккаунтов

- [x] Зафиксировать бессрочную жизнь аккаунтов по умолчанию: автоматическое удаление выключено.
- [x] Предусмотреть будущую настраиваемую политику неактивности; ориентир — 2 года без значимой активности.
- [x] Зафиксировать уведомления на подтверждённый email за 90, 30 и 7 дней до планируемого удаления.
- [x] Предусмотреть отмену удаления при повторном входе или явном подтверждении сохранения аккаунта.
- [x] Предусмотреть отдельные retention hold для Premium/платежей, споров, поддержки, юридических обязательств и Super Admin.
- [ ] При реализации добавить учёт last_activity_at, lifecycle schedule и надёжную очередь/outbox email-уведомлений.
- [ ] Добавить dry-run отчёт и административное подтверждение перед включением политики.
- [ ] Утвердить сроки хранения/анонимизации данных и юридические основания до включения реального удаления.

Подробные правила: `docs/architecture/ACCOUNT-ACCESS-SCHEMA.md`, раздел 13. Политика неактивности не действует, пока её явно не включит администратор.

## Схема аккаунтов, RBAC и Premium · 2026-11-12

- [x] Изучить текущие SQLAlchemy-модели, Alembic bootstrap и соглашения миграций.
- [x] Подготовить проект схемы User/ExternalIdentity/Session/Invitation.
- [x] Разделить RBAC (Role/Permission/UserRole) и коммерческие entitlements.
- [x] Предусмотреть тарифы с версиями цены, подписки, платежи, webhook idempotency и ручные Premium grants.
- [x] Зафиксировать правила аудита, индексов, FK, временных зон и PostgreSQL portability.
- [x] Провести consistency review схемы: устранить дублирование primary email, уточнить OIDC identity key, историчность назначений ролей, invite-only регистрацию, lifecycle подписки и additive entitlement grants.
- [x] Зафиксировать технический контракт базовой схемы; продуктовые решения по тарифам, ценам, платёжному провайдеру и grace policy оставить открытыми.
- [ ] Реализовать модели и миграции небольшими этапами, начиная с аккаунтов и RBAC.
- [ ] Проверить миграции и полный backend suite на SQLite и PostgreSQL 16.
- [ ] После проверки реализовать GitHub OAuth, сессии и серверные permission checks.

Проект схемы: `docs/architecture/ACCOUNT-ACCESS-SCHEMA.md`. Это проектирование, не реализация: новые таблицы и миграции пока не добавлялись.

### Способы входа и управление identity

- [x] Подтвердить мультипровайдерную модель: GitHub OAuth, Google OAuth/OIDC и email + пароль.
- [x] Предусмотреть привязку нескольких способов входа к одному User, отдельное хранение пароля и подтверждённых email.
- [x] Зафиксировать безопасную процедуру связывания аккаунтов без автоматического объединения по совпавшему email.
- [ ] Определить UX регистрации/приглашений, восстановления доступа, привязки и отвязки identity.
- [ ] Реализовать password hashing, email verification/reset tokens, rate limiting и тесты безопасности.
- [ ] Подключить Google OIDC и GitHub OAuth через единый identity service.



**Schema consistency review · 2026-11-12:** `docs/architecture/ACCOUNT-ACCESS-SCHEMA.md` уточнён: EmailAddress — единственный источник primary email; ExternalIdentity использует issuer+subject; UserRole хранит историю отзывов; Subscription отделена от ручных Premium grants; доступ после отмены привязан к оплаченному периоду; стартовая регистрация invite-only. Миграции и модели пока не создавались.


**Final technical safeguards review · 2026-11-12:** В схему добавлены требования к транзакционной защите от гонок при назначении ролей и bootstrap Super Admin, одноразовым токенам и сессиям, неизменяемым snapshot цен, правилам объединения entitlements, атомарной/idempotent обработке webhook и возвратов, закрытию аккаунта и retention policy. Уточнено, что migration smoke test PostgreSQL не заменяет полный backend suite на PostgreSQL. Модели и миграции по-прежнему не создавались.


### Account services · 2026-11-12

- [x] Добавить транзакционные сервисы создания User и привязки GitHub/Google identity без автоматического объединения по email.
- [x] Добавить идемпотентное назначение и исторический отзыв RBAC-ролей; обычный сервис не может назначить Super Admin.
- [x] Реализовать выпуск сессии, проверку, touch с ограничением частоты и отзыв; хранить только SHA-256 hash bearer-токена.
- [x] Реализовать создание приглашения и его однократное принятие с подтверждением владения приглашённым email.
- [x] Реализовать выпуск и однократное потребление email verification token.
- [x] Добавить аудит основных операций без записи raw-токенов и секретов.
- [x] Добавить unit tests для session, invitation, role lifecycle и email verification.
- [ ] Проверить полный backend CI и устранить ошибки.
- [ ] Подключить безопасный email delivery/outbox и API endpoints после определения конфигурации почтового провайдера.
- [x] Реализовать GitHub OAuth и Google OIDC callbacks; email/password login/reset остаётся отдельным этапом.



### GitHub OAuth и Google OIDC · 2026-11-12

- [x] Добавить короткоживущую одноразовую OAuth transaction в БД: state hash, Google nonce hash, encrypted PKCE verifier, provider, redirect URI и срок действия.
- [x] Привязать OAuth linking transaction к конкретной текущей HW Catalog session.
- [x] Реализовать GitHub authorization-code flow с PKCE и идентификацией по неизменяемому numeric user ID.
- [x] Реализовать Google OIDC с проверкой подписи RS256, JWKS, issuer, audience, exp и nonce.
- [x] Разделить вход по уже связанной identity и привязку identity из активной сессии; не объединять аккаунты по email.
- [x] Добавить OAuth API tests для PKCE/state replay, session binding и запрета auto-link по email.
- [x] Проверить CI: 223 passed; Alembic clean upgrade и повторный upgrade на SQLite и PostgreSQL 16 прошли.
- [ ] Добавить UI кнопки входа/привязки, управление связанными identity и понятные ошибки.
- [ ] Добавить rate limiting, security monitoring и отдельную процедуру ротации OAuth encryption key.
- [ ] Выполнить ручную проверку с тестовыми GitHub OAuth App и Google OAuth Client; реальные secrets не хранить в репозитории.

OAuth login не создаёт аккаунт автоматически: начальная регистрация остаётся invite-only. Пользователь принимает приглашение, входит в созданную сессию и привязывает GitHub/Google; после этого может использовать провайдера для входа.


### SMTP adapter и email worker · 2026-11-12

- [x] Добавить SMTP provider с STARTTLS, SMTP-over-TLS и явным опциональным режимом без TLS.
- [x] Проверять SMTP-конфигурацию, адрес отправителя и заголовки; поддержать текстовые и HTML-письма.
- [x] Добавить отдельный CLI worker с однократным и непрерывным режимом, настраиваемыми batch size и polling interval.
- [x] Описать конфигурацию секретов и запуск отдельного supervised worker-процесса.
- [x] Добавить unit tests SMTP-адаптера для TLS-режимов, multipart, credentials и ошибочной конфигурации.
- [ ] Проверить backend CI на ветке integration и устранить ошибки.
- [ ] После CI выбрать реальный SMTP-провайдер, добавить секреты только в hosting environment и выполнить тестовую доставку.
- [ ] Добавить метрики/алерты по возрасту pending-сообщений, failed и retrying; не логировать адреса и содержимое писем.

SMTP не гарантирует exactly-once delivery при разрыве соединения после принятия письма сервером. В таком случае retry может привести к повторной доставке; это ограничение зафиксировано в README.


### Email delivery foundation · 2026-11-12

- [x] Добавить transactional outbox с идемпотентным ключом и состояниями pending/sending/sent/failed.
- [x] Шифровать содержимое письма Fernet-ключом из серверного секрета `HW_EMAIL_ENCRYPTION_KEY`; не хранить ссылки с одноразовыми токенами открытым текстом.
- [x] Добавить provider-neutral интерфейс отправки и dispatcher с lease для зависших задач, backoff и ограничением попыток.
- [x] Добавить тесты шифрования, идемпотентности, отправки, повторов и отказа при недоступном ключе.
- [x] Добавить композицию invitation/email verification писем и атомарную постановку в outbox вместе с выпуском токена.
- [x] Добавить сменный SMTP adapter без изменения outbox/domain API.
- [ ] Добавить шаблоны invitation/email verification и постановку писем в outbox в той же транзакции, что и выпуск токенов.
- [x] Добавить отдельный защищённый CLI worker для outbox; мониторинг очереди и scheduler остаются отдельными задачами.
- [x] Добавить account API endpoints для /me, logout, invitations, invitation acceptance и email verification.
- [x] Установить HttpOnly session cookie + отдельный CSRF cookie; проверять Origin и CSRF header для cookie-auth mutations.
- [x] Добавить RBAC permission dependencies для users.manage и roles.assign.
- [ ] Добавить rate limiting для публичных token endpoints и административной отправки приглашений.

### Email/password authentication · 2026-11-12

- [x] Добавить Argon2id password hashing и одноразовую первичную установку пароля для аккаунта после invitation acceptance.
- [x] Реализовать вход только для active User с подтверждённым primary email и активным PasswordCredential.
- [x] Возвращать одинаковую ошибку входа для неизвестного email, неверного пароля, неподтверждённой почты и недоступного аккаунта.
- [x] Добавить persistent rate-limit buckets с HMAC-идентификаторами вместо хранения исходных email/IP; атомарное обновление поддерживает SQLite и PostgreSQL.
- [x] Добавить enumeration-safe password reset request, encrypted email outbox, SHA-256 token hash, TTL 30 минут и одноразовое потребление.
- [x] При успешном сбросе отзывать все существующие сессии и остальные reset tokens пользователя.
- [x] Добавить API tests для Argon2id, входа, generic errors, throttle, reset replay, session revocation и unverified email.
- [x] Проверить полный CI и migration chain на SQLite и PostgreSQL 16; исправить найденные проблемы.
- [ ] Подключить UI форм входа/установки/сброса пароля и проверить реальные email links.
- [x] Добавить смену пароля для вошедшего пользователя с подтверждением текущего пароля, CSRF и throttling; сохранить текущую сессию, отозвать остальные сессии и reset tokens.
- [ ] Добавить мониторинг rate-limit блокировок, reset queue и security events; определить retention/cleanup buckets.
- [ ] Провести ручной E2E тест после настройки SMTP и HTTPS staging.

Операционная настройка: `HW_AUTH_RATE_LIMIT_KEY` (не менее 32 случайных символов), `HW_EMAIL_ENCRYPTION_KEY`, `HW_PUBLIC_BASE_URL` и SMTP secrets задаются только в окружении сервера.


**Email/password CI · 2026-11-12:** GitHub Actions run #314: 227 passed, 7 warnings. Полный backend suite прошёл; clean Alembic upgrade и повторный upgrade на SQLite и PostgreSQL 16 прошли; PostgreSQL append-only enforcement прошёл. Run: https://github.com/JohnyKiska/hotwheels/actions/runs/43166707308.


**Password change · 2026-11-12:** Добавлен `POST /api/v1/account/password/change`: проверка текущего пароля, CSRF, persistent throttling, Argon2id, отзыв остальных сессий и reset tokens; текущая сессия сохраняется. Добавлены API tests.


## Account frontend · 2026-11-12

- [x] Добавить адаптивную статическую страницу `login.html` и ссылку из каталога.
- [x] Подключить email/password login, OAuth login Google/GitHub и отображение результата callback.
- [x] Подключить принятие приглашения, первоначальную установку пароля, reset password и смену пароля.
- [x] Добавить профиль аккаунта, список email/привязанных OAuth identities и привязку провайдера.
- [x] Перевести OAuth callback, invitation, email verification и reset links на `login.html`.
- [x] Добавить frontend smoke tests для DOM-контрактов, маршрутов и синтаксиса inline JavaScript.
- [ ] Проверить UI в реальном браузере на desktop/mobile и выполнить ручной E2E после настройки HTTPS, OAuth credentials и SMTP.
- [ ] Добавить визуальные состояния подписки Premium и настройки профиля после появления соответствующих API.

Production deployment: предпочтительно same-origin HTTPS для статики и API через reverse proxy. `HW_FRONTEND_URL` должен указывать на публичный origin сайта; OAuth redirect URIs остаются адресами API callback.


**Account frontend CI · 2026-11-12:** GitHub Actions run #? завершился успешно: 232 passed, 7 warnings; clean SQLite/PostgreSQL migration checks and PostgreSQL append-only enforcement passed. [CI run](https://github.com/JohnyKiska/hotwheels/actions/runs/43171622250). Manual browser/E2E remains pending until HTTPS staging, OAuth credentials and SMTP are configured.
