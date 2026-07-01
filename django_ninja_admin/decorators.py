from collections.abc import Callable
from typing import Any


def action(
    function: Callable[..., Any] | None = None,
    *,
    permissions: list[str] | None = None,
    description: str | None = None,
):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if permissions is not None:
            func.allowed_permissions = permissions  # type: ignore[attr-defined]
        if description is not None:
            func.short_description = description  # type: ignore[attr-defined]
        return func

    if function is None:
        return decorator
    return decorator(function)


def display(
    function: Callable[..., Any] | None = None,
    *,
    boolean: bool | None = None,
    ordering: str | None = None,
    description: str | None = None,
    empty_value: str | None = None,
):
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if boolean is not None and empty_value is not None:
            raise ValueError("The boolean and empty_value arguments to @display are mutually exclusive.")
        if boolean is not None:
            func.boolean = boolean  # type: ignore[attr-defined]
        if ordering is not None:
            func.admin_order_field = ordering  # type: ignore[attr-defined]
        if description is not None:
            func.short_description = description  # type: ignore[attr-defined]
        if empty_value is not None:
            func.empty_value_display = empty_value  # type: ignore[attr-defined]
        return func

    if function is None:
        return decorator
    return decorator(function)


def register(*models, site=None):
    from django_ninja_admin.admins.model import ModelAdmin
    from django_ninja_admin.sites import NinjaAdminSite
    from django_ninja_admin.sites import site as default_site

    def _model_admin_wrapper(admin_class):
        if not models:
            raise ValueError("At least one model must be passed to register.")

        admin_site = site or default_site
        if not isinstance(admin_site, NinjaAdminSite):
            raise ValueError("site must be a NinjaAdminSite instance.")
        if not issubclass(admin_class, ModelAdmin):
            raise ValueError("Wrapped class must subclass ModelAdmin.")

        admin_site.register(models, admin_class=admin_class)
        return admin_class

    return _model_admin_wrapper
