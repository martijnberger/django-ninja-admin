"""Optional Django Ninja REST/OpenAPI integration."""

from django_veo_admin_api._optional import missing_ninja_dependency

try:
    from django_veo_admin_api.integrations.ninja.site import NinjaAdminAPI, NinjaAdminSite, site
except ModuleNotFoundError as exc:
    if exc.name == "ninja" or (exc.name or "").startswith("ninja."):
        raise missing_ninja_dependency(exc) from exc
    raise

__all__ = ["NinjaAdminAPI", "NinjaAdminSite", "site"]
