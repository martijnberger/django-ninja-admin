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
