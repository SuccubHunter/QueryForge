# QueryForge — typed query / repository layer для SQLAlchemy 2.0.
from __future__ import annotations

from queryforge.audit import (
    AuditContext,
    add_audit_listener,
    build_event,
    emit_audit_event,
    get_audit_context,
    remove_audit_listener,
)
from queryforge.exceptions import EntityNotFound, QueryForgeError
from queryforge.filters import FilterSet, contains, eq, gte, lte
from queryforge.pagination import Page, offset_for_page
from queryforge.query import PaginateTerminal, Query, QueryState
from queryforge.repository import Repository
from queryforge.soft_delete import SoftDeleteMixin
from queryforge.sorting import SortSet, asc, desc, sort_expressions

__all__ = [
    "FilterSet",
    "Page",
    "PaginateTerminal",
    "Query",
    "QueryState",
    "Repository",
    "SoftDeleteMixin",
    "SortSet",
    "offset_for_page",
    "QueryForgeError",
    "EntityNotFound",
    "contains",
    "eq",
    "gte",
    "lte",
    "asc",
    "desc",
    "sort_expressions",
    "AuditContext",
    "add_audit_listener",
    "remove_audit_listener",
    "emit_audit_event",
    "build_event",
    "get_audit_context",
]

__version__ = "0.1.0"
