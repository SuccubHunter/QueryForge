# Аудит: contextvars, отложенная доставка после commit, outbox, изоляция listeners.
from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from queryforge.audit_storage import AuditStorageBackend

logger = logging.getLogger(__name__)

AuditListener = Callable[[Mapping[str, Any]], Awaitable[None] | None]

_listeners: list[AuditListener] = []
_actor_id: contextvars.ContextVar[uuid.UUID | str | int | None] = contextvars.ContextVar(
    "queryforge_audit_actor", default=None
)
_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "queryforge_audit_reason", default=None
)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "queryforge_audit_request_id", default=None
)
_client_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "queryforge_audit_client_ip", default=None
)
_user_agent: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "queryforge_audit_user_agent", default=None
)

_PENDING_KEY = "queryforge_audit_pending"
_HOOKS_KEY = "queryforge_audit_hooks"


@dataclass
class AuditConfig:
    """Глобальные настройки доставки: listeners после commit, outbox, фоновая async-очередь."""

    deliver_to_listeners: bool = True
    outbox: AuditStorageBackend | None = None
    async_event_queue: asyncio.Queue[dict[str, Any]] | None = None


_audit_config: AuditConfig = AuditConfig()


class _Omit:
    pass


_OMIT = _Omit()


def get_audit_config() -> AuditConfig:
    return _audit_config


def configure_audit(
    *,
    deliver_to_listeners: bool | _Omit = _OMIT,
    outbox: AuditStorageBackend | None | _Omit = _OMIT,
    async_event_queue: asyncio.Queue[dict[str, Any]] | None | _Omit = _OMIT,
) -> None:
    """Смена режима: пропущенные поля не трогать; ``outbox=None`` явно сбрасывает outbox."""
    global _audit_config
    cur = _audit_config
    dl = cur.deliver_to_listeners
    if deliver_to_listeners is not _OMIT:
        dl = bool(deliver_to_listeners)
    ob: AuditStorageBackend | None = cur.outbox
    if outbox is not _OMIT:
        ob = cast(AuditStorageBackend | None, outbox)
    aeq: asyncio.Queue[dict[str, Any]] | None = cur.async_event_queue
    if async_event_queue is not _OMIT:
        aeq = cast(asyncio.Queue[dict[str, Any]] | None, async_event_queue)
    _audit_config = AuditConfig(
        deliver_to_listeners=dl,
        outbox=ob,
        async_event_queue=aeq,
    )


def reset_audit_config() -> None:
    global _audit_config
    _audit_config = AuditConfig()


def add_audit_listener(fn: AuditListener) -> None:
    _listeners.append(fn)


def remove_audit_listener(fn: AuditListener) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def _needs_commit_stage() -> bool:
    c = get_audit_config()
    return c.deliver_to_listeners or c.async_event_queue is not None


def _on_after_commit(sess: Session) -> None:
    raw = sess.info.pop(_PENDING_KEY, None)
    if not raw:
        return
    if isinstance(raw, list):
        pending: list[dict[str, Any]] = raw
    else:
        pending = [raw]
    if not pending:
        return
    c = get_audit_config()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _run_listeners_and_queue_sync(pending, c)
    else:

        async def _safe() -> None:
            try:
                await _commit_stage_async(pending, c)
            except Exception:
                logger.exception("queryforge: commit stage audit (async)")

        loop.create_task(_safe())


def _on_after_rollback(sess: Session) -> None:
    sess.info.pop(_PENDING_KEY, None)


def _run_listeners_and_queue_sync(pending: list[dict[str, Any]], c: AuditConfig) -> None:
    for pl in pending:
        if c.deliver_to_listeners:
            for fn in list(_listeners):
                try:
                    r = fn(pl)
                    if r is not None and hasattr(r, "__await__"):
                        logger.warning("async listener skipped: нет event loop (sync контекст)")
                except Exception:
                    logger.exception("queryforge: ошибка sync audit listener")
        if c.async_event_queue is not None:
            try:
                c.async_event_queue.put_nowait(pl)
            except Exception:
                logger.exception("queryforge: не удалось положить событие в async_event_queue")


async def _commit_stage_async(pending: list[dict[str, Any]], c: AuditConfig) -> None:
    for pl in pending:
        if c.deliver_to_listeners:
            for fn in list(_listeners):
                try:
                    r = fn(pl)
                    if r is not None and hasattr(r, "__await__"):
                        await r
                except Exception:
                    logger.exception("queryforge: ошибка async audit listener")
        if c.async_event_queue is not None:
            try:
                c.async_event_queue.put_nowait(pl)
            except Exception:
                logger.exception("queryforge: не удалось положить событие в async_event_queue")


def _register_session_hooks(s: Session) -> None:
    if s.info.get(_HOOKS_KEY):
        return
    s.info[_HOOKS_KEY] = True
    event.listen(s, "after_commit", _on_after_commit)  # type: ignore[arg-type]
    event.listen(s, "after_rollback", _on_after_rollback)  # type: ignore[arg-type]


def _copy_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(payload)


def ensure_session_audit_hooks(session: AsyncSession) -> None:
    """Регистрирует one-shot per-session хуки after_commit / after_rollback у sync Session."""
    if not _needs_commit_stage():
        return
    _register_session_hooks(session.sync_session)


async def schedule_audit_event(session: AsyncSession, payload: Mapping[str, Any]) -> None:
    """
    Outbox/таблица в текущей транзакции; в память — доставка после успешного commit
    (listeners + optional asyncio.Queue), при rollback — не доставляется.
    """
    c = get_audit_config()
    data = _copy_payload(payload)
    if c.outbox is not None:
        await c.outbox.append(session, data)
    if c.deliver_to_listeners or c.async_event_queue is not None:
        ensure_session_audit_hooks(session)
        sync = session.sync_session
        cur = sync.info.get(_PENDING_KEY)
        if cur is None:
            sync.info[_PENDING_KEY] = [data]
        elif isinstance(cur, list):
            cur.append(data)
        else:
            sync.info[_PENDING_KEY] = [cur, data]


async def emit_audit_event(payload: Mapping[str, Any]) -> None:
    """Немедленная доставка (без привязки к commit) — вне ORM-операций; listeners с изоляцией."""
    p = _copy_payload(payload)
    c = get_audit_config()
    if c.deliver_to_listeners:
        for fn in list(_listeners):
            try:
                r = fn(p)
                if r is not None and hasattr(r, "__await__"):
                    await r
            except Exception:
                logger.exception("queryforge: ошибка emit_audit_event listener")
    if c.async_event_queue is not None:
        try:
            c.async_event_queue.put_nowait(p)
        except Exception:
            logger.exception("queryforge: async_event_queue (emit_audit_event)")


@dataclass(frozen=True, slots=True)
class AuditContextState:
    actor_id: uuid.UUID | str | int | None
    reason: str | None
    request_id: str | None
    client_ip: str | None
    user_agent: str | None

    @staticmethod
    def empty() -> AuditContextState:
        return AuditContextState(None, None, None, None, None)


def get_audit_context() -> AuditContextState:
    return AuditContextState(
        actor_id=_actor_id.get(),
        reason=_reason.get(),
        request_id=_request_id.get(),
        client_ip=_client_ip.get(),
        user_agent=_user_agent.get(),
    )


@asynccontextmanager
async def AuditContext(
    *,
    actor_id: uuid.UUID | str | int | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
):
    t1 = _actor_id.set(actor_id)
    t2 = _reason.set(reason)
    t3 = _request_id.set(request_id)
    t4 = _client_ip.set(client_ip)
    t5 = _user_agent.set(user_agent)
    try:
        yield
    finally:
        _actor_id.reset(t1)
        _reason.reset(t2)
        _request_id.reset(t3)
        _client_ip.reset(t4)
        _user_agent.reset(t5)


def _merge_context_into(out: dict[str, Any], ctx: AuditContextState) -> None:
    if ctx.actor_id is not None:
        out["actor_id"] = str(ctx.actor_id)
    else:
        out.setdefault("actor_id", None)
    if ctx.reason is not None:
        out["reason"] = ctx.reason
    if ctx.request_id is not None:
        out["request_id"] = ctx.request_id
    if ctx.client_ip is not None:
        out["ip"] = ctx.client_ip
    if ctx.user_agent is not None:
        out["user_agent"] = ctx.user_agent


def build_event(
    *,
    action: str,
    entity: str,
    entity_id: Any,
    changes: dict[str, dict[str, Any]] | None = None,
    reason: str | None = None,
    snapshot: dict[str, Any] | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    reason: явное значение; иначе из AuditContext. Метаданные запроса: из contextvars или
    явные аргументы. Снимок сущности: ``snapshot`` (часто ``{"old": …, "new": …}``).
    """
    ctx = get_audit_context()
    eff_req = request_id if request_id is not None else ctx.request_id
    eff_ip = client_ip if client_ip is not None else ctx.client_ip
    eff_ua = user_agent if user_agent is not None else ctx.user_agent
    eff_reason = reason if reason is not None else ctx.reason
    out: dict[str, Any] = {
        "actor_id": str(ctx.actor_id) if ctx.actor_id is not None else None,
        "action": action,
        "entity": entity,
        "entity_id": str(entity_id) if entity_id is not None else None,
    }
    if changes is not None:
        out["changes"] = changes
    if snapshot is not None:
        out["snapshot"] = snapshot
    if eff_reason is not None:
        out["reason"] = eff_reason
    if eff_req is not None:
        out["request_id"] = eff_req
    if eff_ip is not None:
        out["ip"] = eff_ip
    if eff_ua is not None:
        out["user_agent"] = eff_ua
    return out
