__all__ = [
    "AllValuesFieldListFilter",
    "BooleanFieldListFilter",
    "ChoicesFieldListFilter",
    "DateFieldListFilter",
    "EmptyFieldListFilter",
    "FieldListFilter",
    "HORIZONTAL",
    "InlineModelAdmin",
    "ListFilter",
    "ModelAdmin",
    "NinjaAdminSite",
    "RelatedFieldListFilter",
    "RelatedOnlyFieldListFilter",
    "SimpleListFilter",
    "StackedInline",
    "TabularInline",
    "VERTICAL",
    "action",
    "autodiscover",
    "display",
    "register",
    "site",
]


def autodiscover() -> None:
    from django_ninja_admin.sites import site
    from django_ninja_admin.utils.module_loading import autodiscover_modules

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
        from django_ninja_admin import filters

        return getattr(filters, name)
    if name in {"InlineModelAdmin", "StackedInline", "TabularInline"}:
        from django_ninja_admin.admins import inline

        return getattr(inline, name)
    if name in {"HORIZONTAL", "VERTICAL", "ModelAdmin"}:
        from django_ninja_admin.admins import model

        return getattr(model, name)
    if name in {"action", "display", "register"}:
        from django_ninja_admin import decorators

        return getattr(decorators, name)
    if name in {"NinjaAdminSite", "site"}:
        from django_ninja_admin import sites

        return getattr(sites, name)
    raise AttributeError(f"module 'django_ninja_admin' has no attribute {name!r}")
