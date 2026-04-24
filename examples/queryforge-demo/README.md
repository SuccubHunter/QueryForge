# QueryForge demo (FastAPI + PostgreSQL)

Показательный сервис: локальный пакет [queryforge](../../queryforge) + `asyncpg` + сиды в PostgreSQL.

## Схема и данные

- Таблица `users` и индексы: [docker/initdb/00-schema.sql](docker/initdb/00-schema.sql)
- Сиды (в т.ч. мягкое удаление для одной записи): [docker/initdb/01-seed.sql](docker/initdb/01-seed.sql)

Имя/типы полей в SQL должны совпадать с [app/models.py](app/models.py) (и с `project` в Pydantic [app/schemas.py](app/schemas.py)).

## Типизация QueryForge

Пайплайн в [app/api/users.py](app/api/users.py) согласован с проверкой типов: `Repository[User]`, `query()` даёт `Query[User, User]`, после `project(UserRead)` — `Query[User, UserRead]`, `await … paginate(…)` — `Page[UserRead]`. Линтер/IDE не должны сужать `to_list` или `Page` до «сырого» union.

## Запуск (Docker)

Из **этого каталога** (`examples/queryforge-demo`):

```bash
docker compose up --build
```

- API: <http://localhost:8000/docs>
- `GET /health` — проверка процесса
- `GET /users?page=1&size=20` — список (мягкое удаление скрыто, как в QueryForge)
- `GET /users/11111111-1111-1111-1111-111111111101` — одна запись (Alice)

Повторный подъём с тем же volume: данные в БД сохраняются. Для **чистой** инициализации сидами:

```bash
docker compose down -v
docker compose up --build
```

## Локальный запуск без Docker

Нужен PostgreSQL с той же схемой/сидами (или применить SQL вручную) и `DATABASE_URL`.

```bash
# из репозитория QueryForge
cd examples/queryforge-demo
pip install -e .
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Переменная `DATABASE_URL` по умолчанию: `postgresql+asyncpg://queryforge:queryforge@localhost:5432/demodb`.

## Примеры

```bash
curl -s http://localhost:8000/health
curl -s "http://localhost:8000/users?page=1&size=10"
curl -s "http://localhost:8000/users/11111111-1111-1111-1111-111111111101"
```

Пароли в `docker-compose` — только для демо, не для продакшена.
