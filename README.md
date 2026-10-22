# PromQL SLO Checker

Веб-приложение (FastAPI) для проверки SLO: выполняет PromQL-запросы к Prometheus/VictoriaMetrics за заданный период и находит точки, выходящие за допустимый диапазон значений (`condition_min` / `condition_max`). Результаты группировать можно в **профили** (набор запросов), запуски сохраняются в историю.

Возможности:

- пользователи (регистрация/вход, JWT);
- глобальные источники данных (Prometheus / VictoriaMetrics) с проверкой доступности и автоподсказкой label'ов;
- сохранённые PromQL-запросы с условиями (min/max) и шагом;
- профили проверок (набор запросов), публичные профили можно копировать себе;
- запуск отдельного запроса или всего профиля за период → список нарушений с временными метками, значениями и отклонением;
- история выполнений;
- готовый веб-интерфейс (`/`) и Swagger-документация API (`/docs`).

## 1. Структура проекта

| Файл / каталог | Назначение |
|---|---|
| `main.py` | FastAPI-приложение: все HTTP-эндпоинты, логика анализа SLO |
| `models.py` | SQLAlchemy-модели (таблицы БД) |
| `schemas.py` | Pydantic-схемы запросов/ответов API |
| `database.py` | подключение к PostgreSQL (параметры из `.env`), сессии |
| `auth.py` | JWT-токены (HS256, 24 ч), bcrypt-хеши паролей |
| `prometheus_service.py` | вспомогательный сервис запросов к Prometheus (не используется в main.py, дублирует его логику) |
| `alembic/`, `alembic.ini` | миграции БД (есть стартовая: `initial_tables`) |
| `templates/`, `static/` | веб-интерфейс (Jinja2 + JS/CSS) |
| `requirements.txt` | Python-зависимости |
| `.env` | конфигурация (БД, секрет) — **не коммитить реальные пароли** |

## 2. Требования

- Python 3.10+ (проверено на 3.12);
- PostgreSQL 12+ (локально или удалённый);
- доступный по HTTP Prometheus/VictoriaMetrics (для проверки запросов).

## 3. Установка

```bash
cd fapi2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **Корпоративное зеркало PyPI (sberworks):** старая версия starlette 0.46.2 (зависимость fastapi 0.115.12) блокируется зеркалом. Установится более новый fastapi — это нормально, `requirements.txt` уже позволяет версию `>=0.115.12`. Для нового SQLAlchemy нужен драйвер `psycopg[binary]` (уже в `requirements.txt`).

## 4. Конфигурация (`.env`)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `POSTGRES_USER` | `promql_user` | пользователь БД |
| `POSTGRES_PASSWORD` | — | пароль БД |
| `POSTGRES_HOST` | `localhost` | хост БД |
| `POSTGRES_PORT` | `5432` | порт БД |
| `POSTGRES_DB` | `promql_checker` | имя БД |
| `SECRET_KEY` | `zaglushkatuta` | **обязательно задать** случайный длинный секрет — от него зависит подпись JWT |

`SECRET_KEY` не задан по умолчанию в `.env` — добавьте строку `SECRET_KEY=<случайные 32+ символа>`. Все токены, выпущенные со старым секретом, перестанут действовать после смены.

## 5. База данных

Создать пользователя и БД (пример для локального PostgreSQL):

```sql
CREATE USER promql_user WITH PASSWORD 'promql_pass';
CREATE DATABASE promql_checker OWNER promql_user;
```

Или Docker:

```bash
docker run -d --name fapi2-pg -e POSTGRES_USER=promql_user \
  -e POSTGRES_PASSWORD=promql_pass -e POSTGRES_DB=promql_checker \
  -p 5432:5432 postgres:16
```

Применить миграции:

```bash
alembic upgrade head
```

(`alembic/env.py` сам читает `.env`, URL в `alembic.ini` не нужен.)

Таблицы: `users`, `datasources`, `saved_queries`, `profiles`, `profile_queries`, `profile_runs`, `execution_history`.

## 6. Запуск

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

| Адрес | Что это |
|---|---|
| `http://localhost:8000/` | веб-интерфейс (при отсутствии сессии — редирект на `/login`) |
| `http://localhost:8000/login` | страница входа/регистрации |
| `http://localhost:8000/docs` | Swagger UI (интерактивная документация API) |
| `http://localhost:8000/openapi.json` | OpenAPI-спецификация |

БД должна быть доступна в момент первого запроса — приложение стартует и без неё, ошибки появятся при обращении к API.

## 7. Работа с приложением (сценарий)

1. **Регистрация** — `/login` (или `POST /api/auth/register`). Токен возвращается в ответе; в веб-интерфейсе — cookie, в API — заголовок `Authorization: Bearer <token>` (токен живёт 24 ч; принимаются также cookie `token` и query-параметр `token`).
2. **Источники данных** — добавить URL Prometheus/VM (например, `http://prometheus:9090`). Есть проверка доступности (`/check`) и список label'ов (`/labels`, `/label-values/{name}`) для автодополнения.
3. **Запросы** — сохранить PromQL с условиями:
   - `condition_min` — значение не должно опускаться ниже (например, SLA не ниже 99.9);
   - `condition_max` — не должно подниматься выше (например, latency p99 ≤ 300 мс);
   - можно задать только одно условие;
   - `step` — шаг выборки (по умолчанию `60s`).
4. **Профили** — собрать набор запросов в профиль. Публичный профиль (`is_public=true`) виден всем и может быть скопирован (`/api/profiles/{id}/copy`) в личное редактируемое.
5. **Запуск** — для запроса или профиля указать период (`start_time`, `end_time`) и step. Результат: статус `success`/`failed`, список нарушений (timestamp, значение, порог, отклонение), счётчики точек. Запуск профиля дополнительно сохраняется (`profile_runs`) и виден в `/api/profiles/{id}/runs`; каждое выполнение пишется в историю (`/api/history`).

## 8. API

Все эндпоинты кроме `/api/auth/register` и `/api/auth/login` требуют токен.

### Authentication

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/auth/register` | регистрация: `{username (3–50), password (6–128)}` → JWT |
| POST | `/api/auth/login` | вход: `{username, password}` → JWT |
| GET | `/api/auth/me` | текущий пользователь |

### Data Sources

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/datasources` | список всех источников (глобальные) |
| POST | `/api/datasources` | добавить: `{name (уникальное), url, ds_type}` |
| DELETE | `/api/datasources/{id}` | удалить (каскадно удалит запросы) |
| POST | `/api/datasources/{id}/check` | проверка доступности (запрос `up`) |
| GET | `/api/datasources/{id}/labels` | список label'ов |
| GET | `/api/datasources/{id}/label-values/{label}` | значения label'а |

### Queries

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/queries` | свои сохранённые запросы |
| POST | `/api/queries` | сохранить: `{name, promql, datasource_id, step, condition_min, condition_max, description}` |
| DELETE | `/api/queries/{id}` | удалить свой запрос |

### Profiles

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/profiles` | свои + чужие публичные профили |
| POST | `/api/profiles` | создать: `{name, query_ids[], is_public}` |
| PUT | `/api/profiles/{id}/queries` | заменить набор запросов (своё тело — массив id) |
| DELETE | `/api/profiles/{id}` | удалить свой профиль |
| POST | `/api/profiles/{id}/copy` | скопировать чужой публичный себе |
| GET | `/api/profiles/{id}/runs` | последние 50 запусков профиля |

### Execution

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/execute` | выполнить запрос: `{datasource_id, promql, start_time, end_time, step, condition_min, condition_max}` |
| POST | `/api/profiles/execute` | выполнить профиль: `{profile_id, start_time, end_time, step}` |
| GET | `/api/history` | последние 100 выполнений пользователя |

Ответ `/api/execute`: `{status, message, raw_data, violations[{timestamp, value, type, threshold, deviation}], total_points, success_count, failed_count}`.
Ответ `/api/profiles/execute`: `{profile_id, profile_name, ..., success_count, failed_count, failed_details[], success_details[]}`.

Пример (curl):

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"secret"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST localhost:8000/api/execute \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"datasource_id":1,"promql":"slo:availability:ratio","start_time":"2026-10-20T00:00:00","end_time":"2026-10-22T00:00:00","step":"60s","condition_min":0.999}'
```

## 9. Безопасность (заметки)

- `SECRET_KEY` из `.env` — если вы собираетесь ставить не для личного пользования, а например для продакшена - обязателен уникальный секрет.
- Пароли хранятся как bcrypt(SHA256(password)) (двойной хеш — нестандартно, но рабочий вариант).
- Источники данных глобальные: любой пользователь видит и запускает запросы к источникам других (удаление — любой authenticated).
- Токены принимаются из заголовка, cookie и query-параметра (удобно для веба, но query-параметр — утечка в логи/Referer).
- Для боевого развёртывания: https (reverse-proxy), ограничение хоста, смена дефолтных паролей БД.

## 10. Диагностика

| Симптом | Причина / решение |
|---|---|
| `psycopg.OperationalError` / `connection refused` при запросах API | PostgreSQL не запущен или неверный `.env` |
| `psycopg2.OperationalError: FATAL: role ... does not exist` | создать роль/БД (раздел 5) |
| `TypeError: unhashable type: 'dict'` на страницах `/` и `/login` | старая сигнатура `TemplateResponse` с новым starlette — использовать `TemplateResponse(request, "index.html")` (в `main.py` уже исправлено) |
| `ModuleNotFoundError: No module named 'psycopg'` | `pip install "psycopg[binary]"` (новый SQLAlchemy по умолчанию использует v3) |
| 403 на пакет starlette при `pip install` с корпоративного зеркала | зеркало блокирует старую версию — использовать новый fastapi (`fastapi>=0.116`), как в актуальном `requirements.txt` |
| `{"detail":"Not authenticated"}` | токен не передан/протух (24 ч) — перезалогиниться |
| `400 Username already exists` | пользователь уже зарегистрирован |
