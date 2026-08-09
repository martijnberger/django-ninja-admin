from django_veo_admin_api.models import LogEntry


def test_no_drf_imports():
    import django_veo_admin_api

    assert django_veo_admin_api.site is not None
    assert LogEntry._meta.db_table == "django_veo_admin_api_log"


def test_public_api_exports_are_curated():
    import django_veo_admin_api

    expected_exports = {
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
    }
    assert set(django_veo_admin_api.__all__) == expected_exports
    assert {name for name in expected_exports if getattr(django_veo_admin_api, name, None) is None} == set()


def test_ninja_integration_has_a_canonical_import_path():
    from django_veo_admin_api.integrations.ninja import NinjaAdminSite

    assert NinjaAdminSite.__module__ == "django_veo_admin_api.integrations.ninja.site"


def test_legacy_exception_module_reexports_core_vocabulary():
    from django_veo_admin_api.core.exceptions import AdminValidationError as CoreAdminValidationError
    from django_veo_admin_api.exceptions import AdminValidationError

    assert AdminValidationError is CoreAdminValidationError
