# QueryForge

Typed query and repository layer for SQLAlchemy 2.0 and FastAPI. Цепочка `Query` типизирована **по фактическому результату**: `ModelT` — ORM-модель, от которой строится `SELECT`, `ResultT` — то, что возвращают `to_list` / `first` / `one` и срез `Page` после `paginate`.

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

- `Repository(session, model)` — `query()` → `Query[M, M]` (модель и строка выборки в типах совпадают), `get` / `get_or_none` / `exists` / `add` / `delete` / `update`, `from_statement(select(...))` → `Query[M, Any]` (форма строки в произвольном `Select` в типах не фиксируется).
- `Query[ModelT, ResultT]` — `where` / `where_if`, `order_by` / `sort`, `apply(FilterSet)`, `project(DTO)` / `select` + `into`, `paginate` (объект `PaginateTerminal[ResultT]`; `await` → `Page[ResultT]`). Терминалы: `to_list` → `list[ResultT]`, `first` / `one` (и `*_or_none`) → `ResultT` или `None`. После `project(Dto)` / `into(Dto)` получаете `Query[ModelT, Dto]`. Для `project(DTO)` имена полей Pydantic должны совпадать с mapped-атрибутами модели. Для `where_if` с опциональным значением справа (например `User.age >= q.min_age` при `q.min_age: int | None`) передавайте лямбду: `where_if(q.min_age is not None, lambda: User.age >= q.min_age)` — иначе Python вычислит сравнение с `None` до входа в `where_if`.
- `select(…)` (несколько колонок) по типам ведёт к `tuple[…]`; при необходимости сочетайте с `into(DTO)`.
- Мягкое удаление: `SoftDeleteMixin` + `deleted_at`.
- Аудит: `AuditContext`, `add_audit_listener`, события при `add` / `update` / `delete`.

Примеры: `tests/`, статические проверки сигнатур: `tests/typing/`. Установка среды разработки: `pip install -e ".[dev]"` и `pyright queryforge/query.py queryforge/repository.py tests/typing`.

## Демо с Docker и PostgreSQL

Полноценный пример с `docker compose`, сидами в БД и эндпоинтами: [examples/queryforge-demo/README.md](examples/queryforge-demo/README.md).

## Лицензия

MIT
