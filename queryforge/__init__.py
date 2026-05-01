# QueryForge: типизированный слой query/repository для SQLAlchemy 2.0.
from __future__ import annotations

from queryforge.exceptions import (
    EntityNotFound,
    InvalidPaginationError,
    InvalidQueryStateError,
    InvalidSortError,
    ProjectionError,
    QueryForgeError,
    UnknownUpdateFieldError,
)
from queryforge.filters import FilterSet, contains, eq, gte, lte
from queryforge.pagination import Page, offset_for_page
from queryforge.projection import ProjectionMode, ProjectionNested
from queryforge.query import JoinOp, PaginateTerminal, Query, QueryState
from queryforge.repository import Repository
from queryforge.sorting import SortSet, asc, desc, sort_expressions

__all__ = [
    "FilterSet",
    "JoinOp",
    "Page",
    "PaginateTerminal",
    "ProjectionMode",
    "ProjectionNested",
    "Query",
    "QueryForgeError",
    "QueryState",
    "Repository",
    "SortSet",
    "EntityNotFound",
    "InvalidPaginationError",
    "InvalidQueryStateError",
    "InvalidSortError",
    "ProjectionError",
    "UnknownUpdateFieldError",
    "asc",
    "contains",
    "desc",
    "eq",
    "gte",
    "lte",
    "offset_for_page",
    "sort_expressions",
]

__version__ = "0.1.0"
