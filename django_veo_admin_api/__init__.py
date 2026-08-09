__all__ = [
    "HORIZONTAL",
    "VERTICAL",
    "AllValuesFieldListFilter",
    "BooleanFieldListFilter",
    "ChoicesFieldListFilter",
    "DateFieldListFilter",
    "EmptyFieldListFilter",
    "FieldListFilter",
    "InlineModelAdmin",
    "ListFilter",
    "ModelAdmin",
    "NinjaAdminSite",
    "RelatedFieldListFilter",
    "RelatedOnlyFieldListFilter",
    "ShowFacets",
    "SimpleListFilter",
    "StackedInline",
    "TabularInline",
    "action",
    "autodiscover",
    "display",
    "register",
    "site",
]


def autodiscover() -> None:
    from django_veo_admin_api.sites import site
    from django_veo_admin_api.utils.module_loading import autodiscover_modules

    autodiscover_modules("admin", register_to=site)


def __getattr__(name):
    if name in {
        "AllValuesFieldListFilter",
        "BooleanFieldListFilter",
        "ChoicesFieldListFilter",
        "DateFieldListFilter",
        "EmptyFieldListFilter",
        "FieldListFilter",
        "ListFilter",
        "RelatedFieldListFilter",
        "RelatedOnlyFieldListFilter",
        "SimpleListFilter",
    }:
        from django_veo_admin_api import filters

        return getattr(filters, name)
    if name in {"InlineModelAdmin", "StackedInline", "TabularInline"}:
        from django_veo_admin_api.admins import inline

        return getattr(inline, name)
    if name == "ShowFacets":
        from django_veo_admin_api.constants import ShowFacets

        return ShowFacets
    if name in {"HORIZONTAL", "VERTICAL", "ModelAdmin"}:
        from django_veo_admin_api.admins import model

        return getattr(model, name)
    if name in {"action", "display", "register"}:
        from django_veo_admin_api import decorators

        return getattr(decorators, name)
    if name in {"NinjaAdminSite", "site"}:
        from django_veo_admin_api import sites

        return getattr(sites, name)
    raise AttributeError(f"module 'django_veo_admin_api' has no attribute {name!r}")
