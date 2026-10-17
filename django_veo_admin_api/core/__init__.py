"""Transport-neutral Django admin engine primitives."""

__all__ = ["CoreAdminSite"]


def __getattr__(name):
    if name == "CoreAdminSite":
        from django_veo_admin_api.core.site import CoreAdminSite

        return CoreAdminSite
    raise AttributeError(f"module 'django_veo_admin_api.core' has no attribute {name!r}")
