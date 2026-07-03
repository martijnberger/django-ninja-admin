from django import forms
from django.forms.models import BaseInlineFormSet
from django.test import RequestFactory

from django_ninja_admin import ModelAdmin, TabularInline, action
from tests.testapp.models import Product, ProductImage


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
