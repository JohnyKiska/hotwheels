# Развёртывание HW Catalog на тестовом стенде

Этот комплект предназначен для отдельного staging-сервера. Он не развёртывает приложение автоматически и не выполняет реальный end-to-end тест. До появления домена, OAuth credentials и SMTP credentials соответствующие сценарии останутся выключенными.

## Схема

- Caddy принимает HTTP/HTTPS, автоматически получает и обновляет TLS-сертификат.
- Статические страницы каталога и аккаунта отдаются с того же origin, что и API.
- FastAPI работает отдельным контейнером.
- PostgreSQL хранит постоянные данные и аккаунты.
- Почтовый worker запускается отдельным Compose profile только после настройки SMTP.
- Данные PostgreSQL и сертификаты хранятся в Docker volumes.

Frontend и API намеренно используют один HTTPS origin. Не настраивайте отдельный домен API: credentialed cross-origin CORS в приложении пока не включён.

## Требования к серверу

- Linux-сервер с актуальным Docker Engine и Docker Compose plugin.
- DNS A/AAAA-записи `HW_PUBLIC_HOST`, указывающие на сервер.
- Открытые входящие TCP 80 и 443. UDP 443 желателен для HTTP/3.
- Постоянное дисковое пространство для PostgreSQL и Caddy volumes.
- Резервное копирование PostgreSQL volume или регулярные логические дампы.

Не публикуйте порты PostgreSQL и FastAPI наружу. В Compose они доступны только во внутренней Docker-сети.

## Подготовка

На сервере клонируйте репозиторий и переключитесь именно на рабочую ветку:

```bash
git clone https://github.com/JohnyKiska/hotwheels.git
cd hotwheels
git switch integration/catalog-foundation
```

Создайте локальный файл окружения:

```bash
cp .env.example .env
chmod 600 .env
```

Измените в `.env` как минимум:

- `HW_PUBLIC_HOST`, `HW_PUBLIC_BASE_URL`, `HW_FRONTEND_URL` и `HW_ALLOWED_ORIGINS` на один и тот же реальный HTTPS origin.
- `POSTGRES_PASSWORD` на длинный случайный пароль. Для простоты URL подключения пароль должен состоять из URL-safe символов.
- `HW_EMAIL_ENCRYPTION_KEY` и `HW_OAUTH_ENCRYPTION_KEY` на два независимых Fernet-ключа.
- `HW_AUTH_RATE_LIMIT_KEY` на отдельный случайный секрет длиной не менее 32 символов.

Сгенерировать Fernet-ключи можно локально в окружении с установленной backend-зависимостью `cryptography`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Каждый запуск команды создаёт новый ключ. Не используй один ключ для двух переменных. Сохрани резервную копию ключей в менеджере секретов: потеря email encryption key лишит возможности расшифровать ожидающие отправки письма, а потеря OAuth encryption key сделает незавершённые OAuth-транзакции нечитаемыми.

Файл `.env` не должен попадать в Git, Docker image или публичные логи.

## Первый запуск

Проверьте конфигурацию и запустите базовые сервисы:

```bash
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs -f api web
```

API применяет Alembic migrations перед запуском Uvicorn. Дождитесь статуса healthy у `db` и `api`, затем проверьте:

- `https://<ваш-домен>/`
- `https://<ваш-домен>/login.html`
- `https://<ваш-домен>/health`

Health endpoint проверяет доступность процесса API, но сам по себе не подтверждает работу OAuth, SMTP или пользовательского сценария.

## Первичный Super Admin

Регистрация остаётся invite-only. Автоматического назначения первого администратора при старте приложения нет.

После успешного запуска миграций один раз выполните bootstrap с **числовым GitHub account ID**, который оператор предварительно проверил независимо. Не используйте GitHub username вместо ID:

```bash
HW_BOOTSTRAP_GITHUB_ID=12345678 \
HW_BOOTSTRAP_GITHUB_USERNAME=your-github-login \
docker compose exec \
  -e HW_BOOTSTRAP_GITHUB_ID \
  -e HW_BOOTSTRAP_GITHUB_USERNAME \
  api python -m app.bootstrap_super_admin
```

Скрипт создаёт активную учётную запись и привязывает к ней GitHub identity по неизменяемому числовому ID. Он не создаёт пароль или пользовательскую сессию. Команда одноразовая: если Super Admin уже назначен, повторный запуск будет отклонён. После bootstrap удалите временные переменные из shell history, если они туда попали.

Чтобы войти, сначала зарегистрируйте GitHub OAuth application и заполните:

- `HW_GITHUB_CLIENT_ID`
- `HW_GITHUB_CLIENT_SECRET`
- `HW_GITHUB_REDIRECT_URI=https://<ваш-домен>/api/v1/account/oauth/github/callback`

В настройках GitHub OAuth application укажите точно такой же callback URL. Затем пересоздайте API:

```bash
docker compose up -d --build api
```

Google OAuth можно подключить отдельно. Для него используются `HW_GOOGLE_CLIENT_ID`, `HW_GOOGLE_CLIENT_SECRET` и точный callback `/api/v1/account/oauth/google/callback`. До заполнения credentials соответствующая кнопка входа не будет работать.

## Почта

Пока SMTP не настроен, не запускайте email-worker profile. Для проверки приглашений, подтверждения email и сброса пароля настройте SMTP-переменные из `.env.example`, затем выполните:

```bash
docker compose --profile email up -d --build
docker compose logs -f email-worker
```

Worker отдельный от API и использует ту же PostgreSQL базу. SMTP доставка имеет at-least-once семантику в редком случае обрыва соединения после принятия письма сервером.

## Обновление

Перед обновлением сделайте резервную копию БД. Получите изменения только рабочей ветки и пересоберите сервисы:

```bash
git fetch origin
git switch integration/catalog-foundation
git pull --ff-only origin integration/catalog-foundation
docker compose up -d --build
```

При включённом email profile используйте `docker compose --profile email up -d --build`.

Миграции применяются при старте API. Не выполняйте downgrade на рабочей базе без отдельного плана восстановления.

## Резервная копия PostgreSQL

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > hw-catalog-staging.sql
```

Храните дамп отдельно от сервера и проверьте процедуру восстановления до использования стенда с ценными данными.

## Что ещё не подтверждено

Подготовка конфигурации и успешный CI не равны реальному staging-тесту. После появления сервера, домена, OAuth applications и SMTP нужно вручную пройти:

1. TLS и доступность страниц с внешней сети.
2. Первый вход Super Admin через GitHub.
3. Создание приглашения и получение письма.
4. Принятие приглашения, подтверждение email и настройку пароля.
5. Вход/выход, смену и сброс пароля.
6. Google OAuth и привязку второго провайдера.
7. Проверку RBAC, CSRF, сессий и аудита.
8. Перезапуск контейнеров и сохранность данных PostgreSQL.

До прохождения этих шагов стенд считается подготовленным, но не проверенным в реальной эксплуатации.
