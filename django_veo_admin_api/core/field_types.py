from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from django.db import models


@runtime_checkable
class ModelFieldTypeResolver(Protocol):
    """Resolve a Django model field to a Pydantic-compatible Python type."""

    def resolve(self, field: models.Field) -> Any | None: ...


def resolve_model_field_type(
    field: models.Field,
    resolvers: Iterable[ModelFieldTypeResolver],
) -> Any | None:
    """Return the first field type supplied by an ordered resolver chain."""
    for resolver in resolvers:
        field_type = resolver.resolve(field)
        if field_type is not None:
            return field_type
    return None
