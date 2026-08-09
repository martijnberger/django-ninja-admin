"""Compatibility exports for the core operation error vocabulary."""

from django_veo_admin_api.core.exceptions import (
    NON_FIELD_ERRORS,
    AdminError,
    AdminPermissionError,
    AdminValidationError,
    AlreadyRegistered,
    DisallowedModelAdminLookup,
    DisallowedModelAdminToField,
    MissingSearchFields,
    NotRegistered,
    normalize_admin_errors,
)

__all__ = [
    "NON_FIELD_ERRORS",
    "AdminError",
    "AdminPermissionError",
    "AdminValidationError",
    "AlreadyRegistered",
    "DisallowedModelAdminLookup",
    "DisallowedModelAdminToField",
    "MissingSearchFields",
    "NotRegistered",
    "normalize_admin_errors",
]
