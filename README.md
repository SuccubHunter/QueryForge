# QueryForge

Typed query/repository layer для SQLAlchemy 2.0 и FastAPI.
`Query[ModelT, ResultT]` типизируется по фактическому результату терминалов (`to_list`, `first`, `one`, `paginate`).

## Установка

```bash
pip install queryforge
# или
pip install queryforge[fastapi]
```

## Core Query typing

- `Repository(session, User).query()` возвращает `Query[User, User]`.
- `Query` immutable: каждый шаг (`where`, `sort`, `project`, `select`, `paginate`) возвращает новый объект.
- `paginate()` возвращает `Page[ResultT]` с типизированным `items`.

## select / select_value / into

- `select(User.id, User.email)` -> `Query[User, tuple[UUID, str]]`.
- `select_value(User.email)` -> `Query[User, str]` (без tuple-обертки).
- `into(UserRead)` маппит текущую форму результата в Pydantic DTO.

## project и Projection mode

- `project(DTO)` выбирает колонки по полям DTO.
- Поддерживаются режимы `strict` и `loose`.
- Alias-поля поддерживаются через Pydantic field alias.
- По умолчанию `nested="forbid"` (вложенные DTO не поддерживаются в текущей версии).

## FilterSet (Pydantic-based)

- `FilterSet` основан на Pydantic v2 (`extra=forbid`, валидация на входе).
- Поля фильтров собираются декларативно и конвертируются в SQL `where` через `to_wheres()` / `apply()`.

## SortSet

- Multi-sort по входной строке/списку.
- Alias-поля сортировки.
- Поддержка `nulls first/last`.
- Fallback на PK для стабильного порядка.

## include / join / selectin / joined

- `join(...)` добавляет SQL join.
- `include(...)` (алиас `selectin`) и `joined(...)` добавляют eager-loader options.
- Loader options допустимы только для entity-query (`Query[Model, Model]`).
- Для `project` / `select` / `select_value` вызов `include/selectin/joined` вызывает `QueryForgeError`.

## Soft delete

- `SoftDeleteMixin` + фильтрация по умолчанию (`deleted_at is null`).
- `with_deleted()` и `only_deleted()`.
- `restore()` и `hard_delete()`.

## TenantContext / TenantMixin

- `TenantContext` задает текущий tenant в контексте запроса.
- `TenantMixin` добавляет `tenant_id`.
- `for_tenant(...)` и `with_all_tenants()` управляют tenant-scoping на уровне query.
- `Repository.add/get/update/delete` учитывают tenant-ограничения.

## Policy hooks

- `Repository(..., read_scope=...)` + `query().visible_for(user)`.
- `allowed_by(action, user)` для action-based фильтрации.

## Audit / outbox / after_commit

- `AuditContext` для actor/reason/correlation metadata.
- События на `add/update/delete/restore/hard_delete`.
- After-commit delivery listener-ов best-effort.
- Outbox-режим поддерживается как durable канал доставки.

## FastAPI QueryParams

- `set_session_dep(...)` и `repo(...)` для DI репозиториев.
- `QueryParams` и helper-и для pagination/sort/filter binding.
- `page_response(...)` для типизированного ответа страниц.

## Ограничения и контракты

- `from_statement(...)` — escape hatch: может обходить soft-delete/tenant/policy фильтры и loader helpers.
- `nested DTO` в projection пока ограничены (`nested="forbid"` по умолчанию).
- `include/selectin/joined` совместимы только с entity-результатом, не с `project/select/select_value`.
- `count()` для entity-query с `join` считает `distinct` по PK; для projection/select считает строки.

## FastAPI: подключение сессии

```python
from queryforge.fastapi import repo, set_session_dep

set_session_dep(get_async_session)
users_repo: Repository[User] = Depends(repo(User))
```

## Разработка

- Примеры: `tests/`.
- Typing checks: `tests/typing/`.
- Dev setup: `pip install -e ".[dev]"`.

## Лицензия

MIT
