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
from queryforge.exceptions import (
    AlreadySoftDeleted,
    EntityNotFound,
    NotSoftDeleted,
    ProjectionError,
    QueryForgeError,
)
from queryforge.filters import FilterSet, contains, eq, gte, lte
from queryforge.pagination import Page, offset_for_page
from queryforge.projection import ProjectionMode, ProjectionNested
from queryforge.query import JoinOp, PaginateTerminal, Query, QueryState
from queryforge.repository import Repository
from queryforge.soft_delete import (
    SoftDeleteMixin,
    get_soft_delete_policy,
    is_soft_deleted,
    set_soft_delete_policy,
)
from queryforge.sorting import SortSet, asc, desc, sort_expressions

__all__ = [
    "FilterSet",
    "JoinOp",
    "Page",
    "PaginateTerminal",
    "Query",
    "QueryState",
    "Repository",
    "SoftDeleteMixin",
    "is_soft_deleted",
    "set_soft_delete_policy",
    "get_soft_delete_policy",
    "SortSet",
    "offset_for_page",
    "QueryForgeError",
    "EntityNotFound",
    "AlreadySoftDeleted",
    "NotSoftDeleted",
    "ProjectionError",
    "ProjectionMode",
    "ProjectionNested",
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
