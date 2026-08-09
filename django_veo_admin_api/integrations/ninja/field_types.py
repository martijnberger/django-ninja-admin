from typing import Any

from django.db import models
from ninja.orm.fields import TYPES


class NinjaModelFieldTypeResolver:
    """Adapt Django Ninja's ``register_field()`` registry to the core seam."""

    def resolve(self, field: models.Field) -> Any | None:
        return TYPES.get(field.get_internal_type())
