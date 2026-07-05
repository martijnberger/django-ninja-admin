from django_ninja_admin.models import LogEntry


def test_no_drf_imports():
    import django_ninja_admin

    assert django_ninja_admin.site is not None
    assert LogEntry._meta.db_table == "django_ninja_admin_log"


def test_public_api_exports_are_curated():
    import django_ninja_admin

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
    assert set(django_ninja_admin.__all__) == expected_exports
    assert {name for name in expected_exports if getattr(django_ninja_admin, name, None) is None} == set()
