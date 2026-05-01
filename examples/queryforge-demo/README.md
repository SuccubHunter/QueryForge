# QueryForge FastAPI Demo

Runnable FastAPI example for the current QueryForge core surface.

It demonstrates:

- typed `FilterSet` and `SortSet` query parameters;
- `Repository` injection through `queryforge.fastapi.repo`;
- typed pagination with `Page[T]`;
- Pydantic projection with `project(DTO)`;
- typed scalar selection with `select_value`;
- typed selected-column DTO mapping with `select(...).into(DTO)`;
- strict repository update and physical delete.

## Files

- FastAPI entrypoint: [app/main.py](app/main.py)
- User routes: [app/api/users.py](app/api/users.py)
- ORM models: [app/models.py](app/models.py)
- Pydantic schemas and query params: [app/schemas.py](app/schemas.py)
- `users` table schema: [docker/initdb/00-schema.sql](docker/initdb/00-schema.sql)
- Seed data: [docker/initdb/01-seed.sql](docker/initdb/01-seed.sql)

## Run

```bash
docker compose up --build
```

Open:

- API: <http://localhost:8000>
- OpenAPI UI: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## Example Requests

```bash
curl -s "http://localhost:8000/users?page=1&size=20&sort=-created"
curl -s "http://localhost:8000/users?status=active&min_age=25&sort=email"
curl -s "http://localhost:8000/users/emails"
curl -s "http://localhost:8000/users/selected"
curl -s "http://localhost:8000/users/search/raw?email=example"
curl -s "http://localhost:8000/users/11111111-1111-1111-1111-111111111101"
```

Update a user:

```bash
curl -s -X PATCH "http://localhost:8000/users/11111111-1111-1111-1111-111111111101" \
  -H "Content-Type: application/json" \
  -d '{"age": 29}'
```

Delete a user:

```bash
curl -i -X DELETE "http://localhost:8000/users/11111111-1111-1111-1111-111111111101"
```
