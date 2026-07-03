import pytest
from django import forms
from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db import models
from django.forms.models import BaseInlineFormSet
from django.test import RequestFactory
from django.test.utils import isolate_apps

from django_ninja_admin import (
    VERTICAL,
    EmptyFieldListFilter,
    ModelAdmin,
    ShowFacets,
    SimpleListFilter,
    TabularInline,
    action,
    site,
)
from django_ninja_admin.filters import build_filter_spec
from tests.testapp.models import Category, Product, ProductImage, ProductReview, Tag


def _check_site(admin_site):
    return admin_site.check(app_configs=[django_apps.get_app_config("testapp")])


def test_admin_checks_accept_valid_test_admins(db):
    errors = site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert errors == []


def test_admin_checks_report_invalid_model_admin_configuration(db, make_site):
    class BadInline(TabularInline):
        model = Category

    class BadProductAdmin(ModelAdmin):
        list_display = ("missing", "name", "tags")
        list_display_links = ("name",)
        list_editable = ("name",)
        list_filter = ("missing_filter",)
        search_fields = ("category__missing",)
        ordering = ("missing_ordering",)
        date_hierarchy = "name"
        autocomplete_fields = ("stock_status",)
        actions = ["missing_action"]
        inlines = [BadInline]

    admin_site = make_site(Product, BadProductAdmin)

    errors = _check_site(admin_site)
    error_ids = {error.id for error in errors}

    assert {
        "django_ninja_admin.E004",
        "django_ninja_admin.E007",
        "django_ninja_admin.E019",
        "django_ninja_admin.E021",
        "django_ninja_admin.E025",
        "django_ninja_admin.E029",
        "django_ninja_admin.E030",
        "django_ninja_admin.E033",
        "django_ninja_admin.E043",
    } <= error_ids


def test_admin_checks_reject_empty_list_display(db, make_site):
    admin_site = make_site(Product, list_display=())

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E091"}
    assert "list_display" in errors[0].msg


def test_admin_checks_validate_inline_count_options(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        extra = 2
        min_num = None
        max_num = 5

    class BadInline(TabularInline):
        model = ProductImage
        extra = "2"
        min_num = "0"
        max_num = "5"

    class BadBooleanInline(TabularInline):
        model = ProductImage
        extra = True
        min_num = False
        max_num = True

    class BadRangeInline(TabularInline):
        model = ProductImage
        extra = -1
        min_num = -1
        max_num = -1

    class BadMinMaxInline(TabularInline):
        model = ProductImage
        extra = 0
        min_num = 3
        max_num = 1

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])
    bad_boolean_site = make_site(Product, inlines=[BadBooleanInline])
    bad_range_site = make_site(Product, inlines=[BadRangeInline])
    bad_min_max_site = make_site(Product, inlines=[BadMinMaxInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    bad_boolean_ids = {error.id for error in bad_boolean_site.get_model_admin(Product).check()}
    bad_range_ids = {error.id for error in bad_range_site.get_model_admin(Product).check()}
    bad_min_max_ids = {error.id for error in bad_min_max_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E073",
            "django_ninja_admin.E074",
            "django_ninja_admin.E075",
            "django_ninja_admin.E106",
            "django_ninja_admin.E107",
            "django_ninja_admin.E108",
            "django_ninja_admin.E109",
        }
    )
    assert bad_ids == {"django_ninja_admin.E073", "django_ninja_admin.E074", "django_ninja_admin.E075"}
    assert bad_boolean_ids == {"django_ninja_admin.E073", "django_ninja_admin.E074", "django_ninja_admin.E075"}
    assert bad_range_ids == {"django_ninja_admin.E106", "django_ninja_admin.E107", "django_ninja_admin.E108"}
    assert bad_min_max_ids == {"django_ninja_admin.E109"}


def test_admin_checks_reject_non_sequence_inlines_option(db, make_site):
    admin_site = make_site(Product, inlines="not-a-sequence")

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E081"}


def test_admin_checks_validate_inline_boolean_options(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        can_delete = False
        show_change_link = True

    class BadInline(TabularInline):
        model = ProductImage
        can_delete = "no"
        show_change_link = "yes"

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E110", "django_ninja_admin.E111"})
    assert bad_ids == {"django_ninja_admin.E110", "django_ninja_admin.E111"}


def test_admin_checks_validate_inline_form_layout_option_shapes(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        fields = ("title",)
        exclude = ()
        readonly_fields = ()
        fieldsets = (("Main", {"fields": ("title",)}),)

    class BadInline(TabularInline):
        model = ProductImage
        fields = "title"
        exclude = "title"
        readonly_fields = "title"
        fieldsets = "main"

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_errors = bad_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E112" not in valid_ids
    assert [error.id for error in bad_errors] == ["django_ninja_admin.E112"] * 4
    assert {error.msg for error in bad_errors} == {
        "The value of 'fields' must be a list or tuple.",
        "The value of 'exclude' must be a list or tuple.",
        "The value of 'readonly_fields' must be a list or tuple.",
        "The value of 'fieldsets' must be a list or tuple.",
    }


def test_admin_checks_validate_inline_form_layout_option_items(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        fields = ("title",)
        exclude = ()
        readonly_fields = ()

    class BadItemInline(TabularInline):
        model = ProductImage
        fields = (123,)
        exclude = (123,)
        readonly_fields = (123,)

    class BadUnknownInline(TabularInline):
        model = ProductImage
        fields = ("missing",)
        exclude = ("missing",)
        readonly_fields = ("missing",)

    class BadDuplicateInline(TabularInline):
        model = ProductImage
        fields = ("title", "title")
        exclude = ("title", "title")
        readonly_fields = ("title", "title")

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_item_site = make_site(Product, inlines=[BadItemInline])
    bad_unknown_site = make_site(Product, inlines=[BadUnknownInline])
    bad_duplicate_site = make_site(Product, inlines=[BadDuplicateInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_item_ids = [error.id for error in bad_item_site.get_model_admin(Product).check()]
    bad_unknown_ids = [error.id for error in bad_unknown_site.get_model_admin(Product).check()]
    bad_duplicate_ids = [error.id for error in bad_duplicate_site.get_model_admin(Product).check()]

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E113",
            "django_ninja_admin.E114",
            "django_ninja_admin.E115",
            "django_ninja_admin.E116",
        }
    )
    assert bad_item_ids == ["django_ninja_admin.E113", "django_ninja_admin.E113", "django_ninja_admin.E116"]
    assert bad_unknown_ids == ["django_ninja_admin.E114", "django_ninja_admin.E114", "django_ninja_admin.E116"]
    assert bad_duplicate_ids == ["django_ninja_admin.E115", "django_ninja_admin.E115", "django_ninja_admin.E115"]


def test_admin_checks_validate_inline_fieldsets_items(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        fieldsets = (("Main", {"fields": ("title",)}),)

    class BadInline(TabularInline):
        model = ProductImage
        fieldsets = (
            ("MissingFields", {}),
            ("BadOptions", []),
            ("BadFields", {"fields": "title"}),
            ("BadItem", {"fields": (123,)}),
            ("Unknown", {"fields": ("missing",)}),
            ("Duplicate", {"fields": ("title", "title")}),
        )

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = [error.id for error in bad_site.get_model_admin(Product).check()]

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E113",
            "django_ninja_admin.E114",
            "django_ninja_admin.E115",
            "django_ninja_admin.E117",
        }
    )
    assert bad_ids == [
        "django_ninja_admin.E117",
        "django_ninja_admin.E117",
        "django_ninja_admin.E117",
        "django_ninja_admin.E113",
        "django_ninja_admin.E114",
        "django_ninja_admin.E115",
    ]


def test_inline_admin_supports_custom_formset_classes(db, make_site):
    class CustomInlineFormSet(BaseInlineFormSet):
        pass

    class ValidInline(TabularInline):
        model = ProductImage
        formset = CustomInlineFormSet

    class BadInline(TabularInline):
        model = ProductImage
        formset = forms.Form

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])

    inline = valid_site.get_model_admin(Product).get_inline_instances(None, check_permissions=False)[0]
    formset_class = inline.get_formset(RequestFactory().get("/"))
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert issubclass(formset_class, CustomInlineFormSet)
    assert "django_ninja_admin.E076" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E076"}


def test_admin_checks_reject_inline_excluding_parent_foreign_key(db, make_site):
    class ValidInline(TabularInline):
        model = ProductImage
        exclude = ("title",)

    class BadInline(TabularInline):
        model = ProductImage
        exclude = ("product",)

    valid_site = make_site(Product, inlines=[ValidInline])
    bad_site = make_site(Product, inlines=[BadInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_errors = bad_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E077" not in valid_ids
    assert {error.id for error in bad_errors} == {"django_ninja_admin.E077"}
    assert "parent foreign key field 'product'" in bad_errors[0].msg


def test_admin_checks_reject_reverse_relation_in_list_display(db, make_site):
    admin_site = make_site(Product, list_display=("name", "reviews"))

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E043"}
    assert "many-to-many or reverse field" in errors[0].msg


def test_admin_checks_allow_single_valued_relation_path_in_list_display(db, make_site):
    admin_site = make_site(Product, list_display=("name", "category__name"))

    error_ids = {error.id for error in admin_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E003", "django_ninja_admin.E004", "django_ninja_admin.E043"})


def test_admin_checks_validate_action_permission_hooks(db, make_site):
    @action(permissions=["change"])
    def valid_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    @action(permissions=["publish"])
    def custom_permission_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    @action(permissions=["typo"])
    def bad_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    class ValidActionProductAdmin(ModelAdmin):
        actions = [valid_action, custom_permission_action]

        def has_publish_permission(self, request):
            return True

    class BadActionProductAdmin(ModelAdmin):
        actions = [bad_action]

    valid_site = make_site(Product, ValidActionProductAdmin)
    bad_site = make_site(Product, BadActionProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E064" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E064"}


def test_admin_checks_reject_non_sequence_actions_option(db, make_site):
    admin_site = make_site(Product, actions="delete_selected")

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E082"}


def test_admin_checks_report_form_widget_option_conflicts(db, make_site):
    class ConflictProductAdmin(ModelAdmin):
        autocomplete_fields = ("category",)
        raw_id_fields = ("category",)
        filter_horizontal = ("tags",)
        filter_vertical = ("tags",)
        radio_fields = {"category": 999, "price": VERTICAL}

    admin_site = make_site(Product, ConflictProductAdmin)

    errors = _check_site(admin_site)
    error_ids = {error.id for error in errors}

    assert {
        "django_ninja_admin.E037",
        "django_ninja_admin.E038",
        "django_ninja_admin.E039",
        "django_ninja_admin.E040",
        "django_ninja_admin.E041",
        "django_ninja_admin.E042",
    } <= error_ids


def test_admin_checks_validate_list_select_related(db, make_site):
    class ValidProductAdmin(ModelAdmin):
        list_select_related = ("category",)

    class BadTypeProductAdmin(ModelAdmin):
        list_select_related = "category"

    class BadPathProductAdmin(ModelAdmin):
        list_select_related = ("tags", "price", "missing")

    valid_site = make_site(Product, ValidProductAdmin)
    bad_type_site = make_site(Product, BadTypeProductAdmin)
    bad_path_site = make_site(Product, BadPathProductAdmin)

    valid_errors = _check_site(valid_site)
    bad_type_errors = _check_site(bad_type_site)
    bad_path_errors = _check_site(bad_path_site)

    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E045", "django_ninja_admin.E046"})
    assert {error.id for error in bad_type_errors} == {"django_ninja_admin.E045"}
    assert {error.id for error in bad_path_errors} == {"django_ninja_admin.E046"}
    assert len(bad_path_errors) == 3


def test_admin_checks_validate_list_prefetch_related(db, make_site):
    class ValidProductAdmin(ModelAdmin):
        list_prefetch_related = (
            "tags",
            "category__products",
            models.Prefetch("tags", queryset=Tag.objects.order_by("name"), to_attr="prefetched_tags"),
        )

    class BadTypeProductAdmin(ModelAdmin):
        list_prefetch_related = ("tags", 123)

    class BadPathProductAdmin(ModelAdmin):
        list_prefetch_related = ("price", "missing", models.Prefetch("missing_relation"))

    valid_site = make_site(Product, ValidProductAdmin)
    bad_type_site = make_site(Product, BadTypeProductAdmin)
    bad_path_site = make_site(Product, BadPathProductAdmin)

    valid_errors = _check_site(valid_site)
    bad_type_errors = _check_site(bad_type_site)
    bad_path_errors = _check_site(bad_path_site)

    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E118", "django_ninja_admin.E119"})
    assert {error.id for error in bad_type_errors} == {"django_ninja_admin.E118"}
    assert len(bad_type_errors) == 1
    assert {error.id for error in bad_path_errors} == {"django_ninja_admin.E119"}
    assert len(bad_path_errors) == 3


def test_admin_checks_validate_sortable_by(db, make_site):
    class ValidSortableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        sortable_by = ("name",)

    class BadShapeProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = "name"

    class BadItemsProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = (123, "price")

    valid_site = make_site(Product, ValidSortableProductAdmin)
    bad_shape_site = make_site(Product, BadShapeProductAdmin)
    bad_items_site = make_site(Product, BadItemsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_items_ids = {error.id for error in bad_items_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E055", "django_ninja_admin.E056", "django_ninja_admin.E057"})
    assert bad_shape_ids == {"django_ninja_admin.E055"}
    assert bad_items_ids == {"django_ninja_admin.E056", "django_ninja_admin.E057"}


def test_admin_checks_validate_pagination_options(db, make_site):
    class ValidPaginationProductAdmin(ModelAdmin):
        list_per_page = 25
        list_max_show_all = 250

    class BadPaginationProductAdmin(ModelAdmin):
        list_per_page = "25"
        list_max_show_all = "250"

    class BadBooleanPaginationProductAdmin(ModelAdmin):
        list_per_page = True
        list_max_show_all = False

    class BadRangePaginationProductAdmin(ModelAdmin):
        list_per_page = 0
        list_max_show_all = -1

    valid_site = make_site(Product, ValidPaginationProductAdmin)
    bad_site = make_site(Product, BadPaginationProductAdmin)
    bad_boolean_site = make_site(Product, BadBooleanPaginationProductAdmin)
    bad_range_site = make_site(Product, BadRangePaginationProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    bad_boolean_ids = {error.id for error in bad_boolean_site.get_model_admin(Product).check()}
    bad_range_ids = {error.id for error in bad_range_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E067",
            "django_ninja_admin.E068",
            "django_ninja_admin.E104",
            "django_ninja_admin.E105",
        }
    )
    assert bad_ids == {"django_ninja_admin.E067", "django_ninja_admin.E068"}
    assert bad_boolean_ids == {"django_ninja_admin.E067", "django_ninja_admin.E068"}
    assert bad_range_ids == {"django_ninja_admin.E104", "django_ninja_admin.E105"}


def test_admin_checks_validate_paginator_class(db, make_site):
    class CustomPaginator(Paginator):
        pass

    class ValidPaginatorProductAdmin(ModelAdmin):
        paginator = CustomPaginator

    class BadPaginatorProductAdmin(ModelAdmin):
        paginator = object()

    valid_site = make_site(Product, ValidPaginatorProductAdmin)
    bad_site = make_site(Product, BadPaginatorProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E090" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E090"}


def test_admin_checks_validate_boolean_options(db, make_site):
    class CallableViewOnSiteProductAdmin(ModelAdmin):
        save_as = True
        save_as_continue = True
        save_on_top = False
        actions_on_top = True
        actions_on_bottom = False
        actions_selection_counter = True
        show_full_result_count = True
        view_on_site = staticmethod(lambda obj: f"/products/{obj.pk}/")

    class BadBooleanOptionsProductAdmin(ModelAdmin):
        save_as = "yes"
        save_as_continue = "yes"
        save_on_top = "no"
        actions_on_top = "yes"
        actions_on_bottom = "no"
        actions_selection_counter = "yes"
        show_full_result_count = "no"
        view_on_site = "/products/{pk}/"

    valid_site = make_site(Product, CallableViewOnSiteProductAdmin)
    bad_site = make_site(Product, BadBooleanOptionsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E069",
            "django_ninja_admin.E070",
            "django_ninja_admin.E071",
            "django_ninja_admin.E083",
            "django_ninja_admin.E084",
            "django_ninja_admin.E085",
            "django_ninja_admin.E086",
            "django_ninja_admin.E087",
        }
    )
    assert bad_ids == {
        "django_ninja_admin.E069",
        "django_ninja_admin.E070",
        "django_ninja_admin.E071",
        "django_ninja_admin.E083",
        "django_ninja_admin.E084",
        "django_ninja_admin.E085",
        "django_ninja_admin.E086",
        "django_ninja_admin.E087",
    }


def test_admin_checks_reject_mixed_random_ordering(db, make_site):
    class RandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?",)

    class MixedRandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?", "name")

    random_site = make_site(Product, RandomOrderingProductAdmin)
    mixed_site = make_site(Product, MixedRandomOrderingProductAdmin)

    random_ids = {error.id for error in random_site.get_model_admin(Product).check()}
    mixed_errors = mixed_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E072" not in random_ids
    assert {error.id for error in mixed_errors} == {"django_ninja_admin.E072"}
    assert mixed_errors[0].hint == 'Either remove the "?", or remove the other fields.'


def test_admin_checks_validate_show_facets_option(db, make_site):
    class ValidFacetsProductAdmin(ModelAdmin):
        show_facets = ShowFacets.ALWAYS

    class BadFacetsProductAdmin(ModelAdmin):
        show_facets = "ALWAYS"

    valid_site = make_site(Product, ValidFacetsProductAdmin)
    bad_site = make_site(Product, BadFacetsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E088" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E088"}


def test_admin_checks_validate_search_help_text_option(db, make_site):
    class ValidSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = "Search by product name."

    class BadSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = 123

    valid_site = make_site(Product, ValidSearchHelpTextProductAdmin)
    bad_site = make_site(Product, BadSearchHelpTextProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E089" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E089"}


def test_admin_checks_validate_empty_value_display_option(db, make_site):
    class ValidEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = "No value"

    class BadEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = 123

    valid_site = make_site(Product, ValidEmptyValueProductAdmin)
    bad_site = make_site(Product, BadEmptyValueProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E097" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E097"}


def test_admin_checks_allow_relation_path_date_hierarchy(db, make_site):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"

    class BadDateHierarchyProductAdmin(ModelAdmin):
        date_hierarchy = 123

    admin_site = make_site(ProductImage, RelatedDateHierarchyImageAdmin)
    bad_site = make_site(Product, BadDateHierarchyProductAdmin)

    error_ids = {error.id for error in admin_site.get_model_admin(ProductImage).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E028", "django_ninja_admin.E029"})
    assert bad_ids == {"django_ninja_admin.E096"}


def test_admin_checks_allow_expression_ordering(db, make_site):
    class ExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("name").asc(),)

    class MissingExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("missing").desc(),)

    expression_site = make_site(Product, ExpressionOrderingProductAdmin)
    missing_site = make_site(Product, MissingExpressionOrderingProductAdmin)

    expression_ids = {error.id for error in expression_site.get_model_admin(Product).check()}
    missing_ids = {error.id for error in missing_site.get_model_admin(Product).check()}

    assert expression_ids.isdisjoint({"django_ninja_admin.E020", "django_ninja_admin.E021"})
    assert missing_ids == {"django_ninja_admin.E021"}


def test_admin_checks_validate_field_based_list_filter_classes(db, make_site):
    class TupleSimpleFilter(SimpleListFilter):
        title = "tuple simple"
        parameter_name = "tuple_simple"

        def lookups(self, request, model_admin):
            return (("yes", "Yes"),)

    class ValidFieldFilterProductAdmin(ModelAdmin):
        list_filter = (("description", EmptyFieldListFilter),)

    class BadTupleShapeProductAdmin(ModelAdmin):
        list_filter = (("description", EmptyFieldListFilter, "extra"),)

    class BadTupleFilterProductAdmin(ModelAdmin):
        list_filter = (("description", TupleSimpleFilter),)

    valid_site = make_site(Product, ValidFieldFilterProductAdmin)
    bad_shape_site = make_site(Product, BadTupleShapeProductAdmin)
    bad_filter_site = make_site(Product, BadTupleFilterProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_filter_ids = {error.id for error in bad_filter_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E017" not in valid_ids
    assert bad_shape_ids == {"django_ninja_admin.E017"}
    assert bad_filter_ids == {"django_ninja_admin.E017"}

    model_admin = valid_site.get_model_admin(Product)
    request = RequestFactory().get("/")
    with pytest.raises(ImproperlyConfigured, match="must subclass FieldListFilter"):
        build_filter_spec(("description", TupleSimpleFilter), request, request.GET, Product, model_admin)


def test_admin_checks_validate_form_class(db, make_site):
    class ProductAdminForm(forms.ModelForm):
        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class ProductImageAdminForm(forms.ModelForm):
        class Meta:
            model = ProductImage
            fields = ("title",)

    class CategoryAdminForm(forms.ModelForm):
        class Meta:
            model = Category
            fields = ("name",)

    class PlainForm(forms.Form):
        name = forms.CharField()

    class ValidFormProductAdmin(ModelAdmin):
        form_class = ProductAdminForm

    class PlainFormProductAdmin(ModelAdmin):
        form_class = PlainForm

    class WrongModelFormProductAdmin(ModelAdmin):
        form_class = CategoryAdminForm

    class ValidFormInline(TabularInline):
        model = ProductImage
        form_class = ProductImageAdminForm

    class PlainFormInline(TabularInline):
        model = ProductImage
        form_class = PlainForm

    class WrongModelFormInline(TabularInline):
        model = ProductImage
        form_class = ProductAdminForm

    valid_site = make_site(Product, ValidFormProductAdmin)
    plain_site = make_site(Product, PlainFormProductAdmin)
    wrong_model_site = make_site(Product, WrongModelFormProductAdmin)
    valid_inline_site = make_site(Product, inlines=[ValidFormInline])
    plain_inline_site = make_site(Product, inlines=[PlainFormInline])
    wrong_model_inline_site = make_site(Product, inlines=[WrongModelFormInline])

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    plain_ids = {error.id for error in plain_site.get_model_admin(Product).check()}
    wrong_model_ids = {error.id for error in wrong_model_site.get_model_admin(Product).check()}
    valid_inline_ids = {error.id for error in valid_inline_site.get_model_admin(Product).check()}
    plain_inline_ids = {error.id for error in plain_inline_site.get_model_admin(Product).check()}
    wrong_model_inline_ids = {error.id for error in wrong_model_inline_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E058", "django_ninja_admin.E059"})
    assert plain_ids == {"django_ninja_admin.E058"}
    assert wrong_model_ids == {"django_ninja_admin.E059"}
    assert valid_inline_ids.isdisjoint({"django_ninja_admin.E058", "django_ninja_admin.E059"})
    assert plain_inline_ids == {"django_ninja_admin.E058"}
    assert wrong_model_inline_ids == {"django_ninja_admin.E059"}


def test_admin_checks_validate_formfield_overrides(db, make_site):
    class ValidOverrideProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: {"help_text": "Custom help."}}

    class BadShapeProductAdmin(ModelAdmin):
        formfield_overrides = [(models.TextField, {"help_text": "Custom help."})]

    class BadFieldKeyProductAdmin(ModelAdmin):
        formfield_overrides = {"description": {"help_text": "Custom help."}}

    class BadOverrideValueProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: ["help_text", "Custom help."]}

    class BadOverrideKeyProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: {123: "Custom help."}}

    valid_site = make_site(Product, ValidOverrideProductAdmin)
    bad_shape_site = make_site(Product, BadShapeProductAdmin)
    bad_field_key_site = make_site(Product, BadFieldKeyProductAdmin)
    bad_override_value_site = make_site(Product, BadOverrideValueProductAdmin)
    bad_override_key_site = make_site(Product, BadOverrideKeyProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_field_key_ids = {error.id for error in bad_field_key_site.get_model_admin(Product).check()}
    bad_override_value_ids = {error.id for error in bad_override_value_site.get_model_admin(Product).check()}
    bad_override_key_ids = {error.id for error in bad_override_key_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E060",
            "django_ninja_admin.E061",
            "django_ninja_admin.E062",
            "django_ninja_admin.E063",
        }
    )
    assert bad_shape_ids == {"django_ninja_admin.E060"}
    assert bad_field_key_ids == {"django_ninja_admin.E061"}
    assert bad_override_value_ids == {"django_ninja_admin.E062"}
    assert bad_override_key_ids == {"django_ninja_admin.E063"}


def test_admin_checks_reject_reverse_relation_widget_fields(db, make_site):
    class ReviewAdmin(ModelAdmin):
        search_fields = ("note",)

    class ReverseAutocompleteProductAdmin(ModelAdmin):
        autocomplete_fields = ("reviews",)

    class ReverseRawIdProductAdmin(ModelAdmin):
        raw_id_fields = ("reviews",)

    autocomplete_site = make_site(Product, ReverseAutocompleteProductAdmin)
    autocomplete_site.register(ProductReview, ReviewAdmin)
    raw_id_site = make_site(Product, ReverseRawIdProductAdmin)

    autocomplete_errors = autocomplete_site.get_model_admin(Product).check()
    raw_id_errors = raw_id_site.get_model_admin(Product).check()

    assert {error.id for error in autocomplete_errors} == {"django_ninja_admin.E025"}
    assert {error.id for error in raw_id_errors} == {"django_ninja_admin.E025"}


def test_admin_checks_require_registered_searchable_autocomplete_targets(db, make_site):
    class ProductAutocompleteAdmin(ModelAdmin):
        autocomplete_fields = ("category",)

    unregistered_site = make_site(Product, ProductAutocompleteAdmin)

    class UnsearchableCategoryAdmin(ModelAdmin):
        pass

    unsearchable_site = make_site(Product, ProductAutocompleteAdmin)
    unsearchable_site.register(Category, UnsearchableCategoryAdmin)

    class SearchableCategoryAdmin(ModelAdmin):
        search_fields = ("name",)

    valid_site = make_site(Product, ProductAutocompleteAdmin)
    valid_site.register(Category, SearchableCategoryAdmin)

    unregistered_errors = unregistered_site.get_model_admin(Product).check()
    unsearchable_errors = unsearchable_site.get_model_admin(Product).check()
    valid_errors = valid_site.get_model_admin(Product).check()

    assert {error.id for error in unregistered_errors} == {"django_ninja_admin.E026"}
    assert {error.id for error in unsearchable_errors} == {"django_ninja_admin.E027"}
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E026", "django_ninja_admin.E027"})


def test_admin_checks_validate_prepopulated_fields(db, make_site):
    class ValidPrepopulatedProductAdmin(ModelAdmin):
        prepopulated_fields = {"description": ("name",)}

    class BadShapeProductAdmin(ModelAdmin):
        prepopulated_fields = [("description", ("name",))]

    class BadTargetProductAdmin(ModelAdmin):
        prepopulated_fields = {
            123: ("name",),
            "missing": ("name",),
            "category": ("name",),
            "created_at": ("name",),
        }

    class BadSourceProductAdmin(ModelAdmin):
        prepopulated_fields = {
            "description": "name",
            "name": (123, "missing"),
        }

    valid_site = make_site(Product, ValidPrepopulatedProductAdmin)
    bad_shape_site = make_site(Product, BadShapeProductAdmin)
    bad_target_site = make_site(Product, BadTargetProductAdmin)
    bad_source_site = make_site(Product, BadSourceProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_target_ids = {error.id for error in bad_target_site.get_model_admin(Product).check()}
    bad_source_ids = {error.id for error in bad_source_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E050",
            "django_ninja_admin.E051",
            "django_ninja_admin.E052",
            "django_ninja_admin.E053",
            "django_ninja_admin.E054",
        }
    )
    assert bad_shape_ids == {"django_ninja_admin.E050"}
    assert bad_target_ids == {"django_ninja_admin.E051", "django_ninja_admin.E052"}
    assert bad_source_ids == {"django_ninja_admin.E053", "django_ninja_admin.E054"}


def test_admin_checks_reject_list_editable_fields_missing_from_generated_form(db, make_site):
    class MissingFromFieldsProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        fields = ("name", "category", "price")

    class ExcludedProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        exclude = ("stock_status",)

    class MissingFromFieldsetsProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        fieldsets = ((None, {"fields": ("name", "category", "price")}),)

    fields_site = make_site(Product, MissingFromFieldsProductAdmin)
    exclude_site = make_site(Product, ExcludedProductAdmin)
    fieldsets_site = make_site(Product, MissingFromFieldsetsProductAdmin)

    fields_errors = _check_site(fields_site)
    exclude_errors = _check_site(exclude_site)
    fieldsets_errors = _check_site(fieldsets_site)

    assert "django_ninja_admin.E044" in {error.id for error in fields_errors}
    assert "django_ninja_admin.E044" in {error.id for error in exclude_errors}
    assert "django_ninja_admin.E044" in {error.id for error in fieldsets_errors}


def test_admin_checks_reject_first_list_editable_without_explicit_display_link(db, make_site):
    class BadFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_editable = ("stock_status",)

    class ValidFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_display_links = ("name",)
        list_editable = ("stock_status",)

    bad_site = make_site(Product, BadFirstEditableProductAdmin)
    valid_site = make_site(Product, ValidFirstEditableProductAdmin)

    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}

    assert bad_ids == {"django_ninja_admin.E066"}
    assert valid_ids.isdisjoint({"django_ninja_admin.E007", "django_ninja_admin.E066"})


def test_admin_checks_reject_duplicate_list_editable_fields(db, make_site):
    class DuplicateEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = ("price", "price")

    admin_site = make_site(Product, DuplicateEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E093"}


def test_admin_checks_reject_non_string_list_editable_fields(db, make_site):
    class BadEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = (123,)

    admin_site = make_site(Product, BadEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E094"}


def test_admin_checks_reject_duplicate_list_display_links(db, make_site):
    class DuplicateLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name", "name")

    admin_site = make_site(Product, DuplicateLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E079"}


def test_admin_checks_reject_non_string_list_display_links(db, make_site):
    class BadLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = (123,)

    admin_site = make_site(Product, BadLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E095"}


def test_admin_checks_validate_fields_and_exclude_items(db, make_site):
    class RowFieldsProductAdmin(ModelAdmin):
        fields = (("name", "price"), "category")

    class BadFieldsProductAdmin(ModelAdmin):
        fields = ("name", 123)

    class DuplicateFieldsProductAdmin(ModelAdmin):
        fields = ("name", ("price", "name"))

    class BadExcludeProductAdmin(ModelAdmin):
        exclude = ("missing", 123)

    class DuplicateExcludeProductAdmin(ModelAdmin):
        exclude = ("name", "name")

    row_fields_site = make_site(Product, RowFieldsProductAdmin)
    fields_site = make_site(Product, BadFieldsProductAdmin)
    duplicate_fields_site = make_site(Product, DuplicateFieldsProductAdmin)
    exclude_site = make_site(Product, BadExcludeProductAdmin)
    duplicate_exclude_site = make_site(Product, DuplicateExcludeProductAdmin)

    row_fields_errors = _check_site(row_fields_site)
    fields_errors = _check_site(fields_site)
    duplicate_fields_errors = _check_site(duplicate_fields_site)
    exclude_errors = _check_site(exclude_site)
    duplicate_exclude_errors = _check_site(duplicate_exclude_site)

    assert row_fields_errors == []
    assert list(row_fields_site.get_model_admin(Product).get_form_class(None).base_fields) == [
        "name",
        "price",
        "category",
    ]
    assert {error.id for error in fields_errors} == {"django_ninja_admin.E048"}
    assert {error.id for error in duplicate_fields_errors} == {"django_ninja_admin.E065"}
    assert {error.id for error in exclude_errors} == {"django_ninja_admin.E048", "django_ninja_admin.E049"}
    assert {error.id for error in duplicate_exclude_errors} == {"django_ninja_admin.E080"}


def test_admin_checks_reject_duplicate_readonly_fields(db, make_site):
    def readonly_summary(obj):
        return obj.name

    class ValidReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", readonly_summary)

    class DuplicateNameReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", "name")

    class DuplicateCallableReadonlyProductAdmin(ModelAdmin):
        readonly_fields = (readonly_summary, readonly_summary)

    valid_site = make_site(Product, ValidReadonlyProductAdmin)
    duplicate_name_site = make_site(Product, DuplicateNameReadonlyProductAdmin)
    duplicate_callable_site = make_site(Product, DuplicateCallableReadonlyProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    duplicate_name_ids = {error.id for error in duplicate_name_site.get_model_admin(Product).check()}
    duplicate_callable_ids = {error.id for error in duplicate_callable_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E092" not in valid_ids
    assert duplicate_name_ids == {"django_ninja_admin.E092"}
    assert duplicate_callable_ids == {"django_ninja_admin.E092"}


def test_admin_checks_validate_fieldsets_shape_and_duplicates(db, make_site):
    class ValidFieldsetsProductAdmin(ModelAdmin):
        fieldsets = (
            (None, {"fields": (("name", "price"), "category")}),
            ("Advanced", {"fields": ("description",)}),
        )

    class MissingFieldsOptionProductAdmin(ModelAdmin):
        fieldsets = ((None, {"classes": ("collapse",)}),)

    class StringFieldsProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": "name"}),)

    class BadFieldItemProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("name", 123)}),)

    class DuplicateFieldProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("name", ("price", "name"))}),)

    valid_site = make_site(Product, ValidFieldsetsProductAdmin)
    missing_site = make_site(Product, MissingFieldsOptionProductAdmin)
    string_site = make_site(Product, StringFieldsProductAdmin)
    bad_item_site = make_site(Product, BadFieldItemProductAdmin)
    duplicate_site = make_site(Product, DuplicateFieldProductAdmin)

    assert _check_site(valid_site) == []
    assert list(valid_site.get_model_admin(Product).get_form_class(None).base_fields) == [
        "name",
        "price",
        "category",
        "description",
    ]
    assert {error.id for error in _check_site(missing_site)} == {"django_ninja_admin.E013"}
    assert {error.id for error in _check_site(string_site)} == {"django_ninja_admin.E013"}
    assert {error.id for error in _check_site(bad_item_site)} == {"django_ninja_admin.E013"}
    assert {error.id for error in _check_site(duplicate_site)} == {"django_ninja_admin.E064"}


def test_admin_checks_validate_radio_fields_shape(db, make_site):
    class BadRadioShapeAdmin(ModelAdmin):
        radio_fields = ("stock_status",)

    admin_site = make_site(Product, BadRadioShapeAdmin)

    errors = _check_site(admin_site)

    assert {error.id for error in errors} == {"django_ninja_admin.E034"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_widget_modes(db, make_site):
    class Article(models.Model):
        title = models.CharField(max_length=100)
        tags = models.ManyToManyField("ArticleTag", through="ArticleTagging")

        class Meta:
            app_label = "testapp"

    class ArticleTag(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "testapp"

    class ArticleTagging(models.Model):
        article = models.ForeignKey(Article, on_delete=models.CASCADE)
        tag = models.ForeignKey(ArticleTag, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class HorizontalArticleAdmin(ModelAdmin):
        filter_horizontal = ("tags",)

    class VerticalArticleAdmin(ModelAdmin):
        filter_vertical = ("tags",)

    horizontal_site = make_site(Article, HorizontalArticleAdmin)
    vertical_site = make_site(Article, VerticalArticleAdmin)

    horizontal_errors = horizontal_site.get_model_admin(Article).check()
    vertical_errors = vertical_site.get_model_admin(Article).check()

    assert {error.id for error in horizontal_errors} == {"django_ninja_admin.E047"}
    assert {error.id for error in vertical_errors} == {"django_ninja_admin.E047"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_form_layouts(db, make_site):
    class ArticleTag(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class Article(models.Model):
        title = models.CharField(max_length=20)
        tags = models.ManyToManyField(ArticleTag, through="ArticleTagging")

        class Meta:
            app_label = "testapp"

    class ArticleTagging(models.Model):
        article = models.ForeignKey(Article, on_delete=models.CASCADE)
        tag = models.ForeignKey(ArticleTag, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class FieldsArticleAdmin(ModelAdmin):
        fields = ("title", "tags")

    class FieldsetsArticleAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("title", "tags")}),)

    fields_site = make_site(Article, FieldsArticleAdmin)
    fieldsets_site = make_site(Article, FieldsetsArticleAdmin)

    fields_errors = fields_site.get_model_admin(Article).check()
    fieldsets_errors = fieldsets_site.get_model_admin(Article).check()

    assert {error.id for error in fields_errors} == {"django_ninja_admin.E078"}
    assert {error.id for error in fieldsets_errors} == {"django_ninja_admin.E078"}


def test_admin_checks_validate_schema_field_overrides(db, make_site):
    class ValidSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None), "score": (int,)}

    class BadMappingSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = [("custom_note", str)]

    class BadKeySchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {123: str}

    class BadTupleSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None, "extra")}

    valid_site = make_site(Product, ValidSchemaOverrideProductAdmin)
    bad_mapping_site = make_site(Product, BadMappingSchemaOverrideProductAdmin)
    bad_key_site = make_site(Product, BadKeySchemaOverrideProductAdmin)
    bad_tuple_site = make_site(Product, BadTupleSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E098", "django_ninja_admin.E099", "django_ninja_admin.E100"})
    assert bad_mapping_ids == {"django_ninja_admin.E098"}
    assert bad_key_ids == {"django_ninja_admin.E099"}
    assert bad_tuple_ids == {"django_ninja_admin.E100"}


def test_admin_checks_validate_form_schema_field_overrides(db, make_site):
    class ValidFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": dict[str, int], "score": (int,)}

    class BadMappingFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = [("metadata", dict[str, int])]

    class BadKeyFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {123: str}

    class BadTupleFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": (dict[str, int], None, "extra")}

    valid_site = make_site(Product, ValidFormSchemaOverrideProductAdmin)
    bad_mapping_site = make_site(Product, BadMappingFormSchemaOverrideProductAdmin)
    bad_key_site = make_site(Product, BadKeyFormSchemaOverrideProductAdmin)
    bad_tuple_site = make_site(Product, BadTupleFormSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E101", "django_ninja_admin.E102", "django_ninja_admin.E103"})
    assert bad_mapping_ids == {"django_ninja_admin.E101"}
    assert bad_key_ids == {"django_ninja_admin.E102"}
    assert bad_tuple_ids == {"django_ninja_admin.E103"}
