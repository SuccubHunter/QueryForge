# QueryForge

Typed query and repository layer for SQLAlchemy 2.0 and FastAPI.

## Установка

```bash
pip install queryforge
# или
pip install queryforge[fastapi]
```

## FastAPI: сессия

Перед `Depends(repo(Model))` укажите зависимость `AsyncSession`:

```python
from queryforge.fastapi import repo, set_session_dep

# Вариант 1: глобально
set_session_dep(get_async_session)  # ваша async def / yield session

# Вариант 2: явно
users: Repository[User] = Depends(repo(User, session_dep=get_async_session))
```

## Кратко

- `Repository(session, model)` — `query()`, `get` / `get_or_none` / `exists` / `add` / `delete` / `update`, `from_statement(select(...))`.
- `Query` — `where` / `where_if`, `order_by` / `sort`, `apply(FilterSet)`, `project(DTO)` / `select` + `into`, `paginate` (await → `Page[T]`). Для `project(DTO)` имена полей Pydantic должны совпадать с mapped-атрибутами модели.
- Мягкое удаление: `SoftDeleteMixin` + `deleted_at`.
- Аудит: `AuditContext`, `add_audit_listener`, события при `add` / `update` / `delete`.

См. примеры в `tests/`.

## Демо с Docker и PostgreSQL

Полноценный пример с `docker compose`, сидами в БД и эндпоинтами: [examples/queryforge-demo/README.md](examples/queryforge-demo/README.md).

## Лицензия

MIT
