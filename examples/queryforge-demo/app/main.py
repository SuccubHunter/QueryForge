# Точка входа FastAPI
from __future__ import annotations

from app.api import users
from fastapi import FastAPI

app = FastAPI(title="QueryForge demo", version="0.1.0")
app.include_router(users.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
