# Аудит: контекст (actor, reason) и глобальные подписчики событий.
from __future__ import annotations

import contextvars
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

AuditListener = Callable[[Mapping[str, Any]], Awaitable[None] | None]

_listeners: list[AuditListener] = []
_actor_id: contextvars.ContextVar[uuid.UUID | str | int | None] = contextvars.ContextVar(
    "queryforge_audit_actor", default=None
)
_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "queryforge_audit_reason", default=None
)


def add_audit_listener(fn: AuditListener) -> None:
    _listeners.append(fn)


def remove_audit_listener(fn: AuditListener) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


async def emit_audit_event(payload: Mapping[str, Any]) -> None:
    for fn in list(_listeners):
        r = fn(payload)
        if r is not None and hasattr(r, "__await__"):
            await r


@asynccontextmanager
async def AuditContext(*, actor_id: uuid.UUID | str | int | None = None, reason: str | None = None):
    t_actor = _actor_id.set(actor_id)
    t_reason = _reason.set(reason)
    try:
        yield
    finally:
        _actor_id.reset(t_actor)
        _reason.reset(t_reason)


def get_audit_context() -> tuple[uuid.UUID | str | int | None, str | None]:
    return _actor_id.get(), _reason.get()


def build_event(
    *,
    action: str,
    entity: str,
    entity_id: Any,
    changes: dict[str, dict[str, Any]] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """reason: явное значение для payload; иначе берётся из AuditContext (если задано)."""
    aid, ctx_reason = get_audit_context()
    eff_reason = reason if reason is not None else ctx_reason
    out: dict[str, Any] = {
        "actor_id": str(aid) if aid is not None else None,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
    }
    if changes is not None:
        out["changes"] = changes
    if eff_reason is not None:
        out["reason"] = eff_reason
    return out
