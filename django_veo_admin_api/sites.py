"""Lazy compatibility exports for the optional Django Ninja integration."""

from importlib import import_module

from django_veo_admin_api._optional import missing_ninja_dependency

__all__ = ["NinjaAdminAPI", "NinjaAdminSite", "site"]  # noqa: F822


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module 'django_veo_admin_api.sites' has no attribute {name!r}")
    try:
        ninja_site_module = import_module("django_veo_admin_api.integrations.ninja.site")
    except ModuleNotFoundError as exc:
        if exc.name == "ninja" or (exc.name or "").startswith("ninja."):
            raise missing_ninja_dependency(exc) from exc
        raise
    return getattr(ninja_site_module, name)
