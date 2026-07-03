import pytest
from django import forms
from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured
from django.core.paginator import Paginator
from django.db import models
from django.forms.models import BaseInlineFormSet
from django.test import RequestFactory

from django_ninja_admin import (
    VERTICAL,
    EmptyFieldListFilter,
    ModelAdmin,
    ShowFacets,
    SimpleListFilter,
    TabularInline,
    action,
)
from django_ninja_admin.filters import build_filter_spec
from tests.testapp.models import Product, ProductImage, Tag


def _check_site(admin_site):
    return admin_site.check(app_configs=[django_apps.get_app_config("testapp")])


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
