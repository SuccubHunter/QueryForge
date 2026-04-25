# Policy / RBAC: протоколы и типы для ограничения выборки по «текущему пользователю».
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from sqlalchemy.sql import ColumnElement

UserT = TypeVar("UserT", contravariant=True)
ModelT = TypeVar("ModelT", contravariant=True)

ReadScope = Callable[[type[Any], Any], ColumnElement[bool]]
"""Сигнатура политики по умолчанию: ``(model_orm_class, current_user) -> where``."""

PolicyAction = Callable[[Any], ColumnElement[bool]]
"""Действие (например ``UserPolicy.read``): ``user -> where``."""


class ModelReadPolicy(Protocol[UserT, ModelT]):
    """Протокол: класс/функция, задающая `visible_for` на уровне репозитория."""

    def __call__(self, model: type[ModelT], user: UserT) -> ColumnElement[bool]: ...
