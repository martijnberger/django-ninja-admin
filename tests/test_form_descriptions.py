from decimal import Decimal

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import models
from django.test import RequestFactory
from django.test.utils import isolate_apps

from django_ninja_admin import ModelAdmin, NinjaAdminSite, display, site
from tests.testapp.models import Product, Tag

RENDERED_FIELD_ATTR_KEYS = {
    "aria_describedby",
    "auto_id",
    "bound_subwidgets",
    "clear_checkbox_id",
    "clear_checkbox_name",
    "css_classes",
    "form_prefix",
    "hidden_initial_id",
    "hidden_initial_name",
    "hidden_initial_widget",
    "html_initial_id",
    "html_initial_name",
    "html_name",
    "id_for_label",
    "option_template_name",
    "rendered_attrs",
    "rendered_optgroups",
    "rendered_subwidgets",
    "show_hidden_initial",
    "template_name",
}


def assert_no_rendered_field_attrs(attrs):
    assert RENDERED_FIELD_ATTR_KEYS.isdisjoint(attrs)


def test_add_form_description_uses_changeform_initial_data(admin_client, sample):
    tag_ids = list(sample.tags.order_by("name").values_list("pk", flat=True))
    response = admin_client.get(
        "/admin-api/testapp/product/form",
        {
            "name": "Seed product",
            "category": sample.category_id,
            "tags": ",".join(str(tag_id) for tag_id in tag_ids),
            "price": "4.50",
            "stock_status": "out_of_stock",
        },
    )

    assert response.status_code == 200
    fields_by_name = {field["name"]: field for field in response.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["value"] == "Seed product"
    assert fields_by_name["category"]["attrs"]["value"] == str(sample.category_id)
    assert fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert set(fields_by_name["tags"]["attrs"]["value"]) == {str(tag_id) for tag_id in tag_ids}
    assert {option["text"] for option in fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Compact",
        "Featured",
    }
    assert fields_by_name["price"]["attrs"]["value"] == "4.50"
    assert fields_by_name["stock_status"]["attrs"]["value"] == "out_of_stock"

    class InitialProductAdmin(ModelAdmin):
        def get_changeform_initial_data(self, request):
            return {
                "name": "Hooked initial",
                "category": sample.category_id,
                "tags": tag_ids,
            }

    user = get_user_model().objects.create_user("initial-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form?name=Ignored")
    request.user = user
    model_admin = InitialProductAdmin(Product, NinjaAdminSite(include_auth=False))

    hooked_form = model_admin.get_form_description(request)["form"]
    hooked_fields_by_name = {field["name"]: field for field in hooked_form["fields"]}

    assert hooked_fields_by_name["name"]["attrs"]["value"] == "Hooked initial"
    assert hooked_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert {option["text"] for option in hooked_fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Compact",
        "Featured",
    }


def test_readonly_display_fields_include_values_and_display_metadata(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def callable_summary(obj):
        return f"{obj.name}:{obj.stock_status}"

    @display(description="", empty_value="")
    def blank_summary(obj):
        return None

    callable_summary.short_description = "Callable summary"
    monkeypatch.setattr(
        product_admin,
        "readonly_fields",
        ("upper_name", "has_description", "subtitle", callable_summary, blank_summary),
    )

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    assert "callable_summary" in response.json()["form"]["readonly_fields"]
    assert "django_ninja_admin.E012" not in {error.id for error in product_admin.check()}
    fields_by_name = {field["name"]: field for field in response.json()["form"]["fields"]}
    assert fields_by_name["upper_name"]["attrs"]["label"] == "Upper name"
    assert fields_by_name["upper_name"]["attrs"]["value"] == "ALPHA"
    assert fields_by_name["upper_name"]["attrs"]["read_only"] is True
    assert fields_by_name["upper_name"]["attrs"]["ordering_field"] == "name"
    assert fields_by_name["has_description"]["attrs"]["label"] == "Has description"
    assert fields_by_name["has_description"]["attrs"]["value"] is True
    assert fields_by_name["has_description"]["attrs"]["boolean"] is True
    assert fields_by_name["has_description"]["attrs"]["ordering_field"] is None
    assert fields_by_name["subtitle"]["attrs"]["label"] == "Subtitle"
    assert fields_by_name["subtitle"]["attrs"]["value"] == "Nice camera"
    assert fields_by_name["subtitle"]["attrs"]["empty_value_display"] == "No subtitle"
    assert fields_by_name["callable_summary"]["attrs"]["label"] == "Callable summary"
    assert fields_by_name["callable_summary"]["attrs"]["value"] == "Alpha:in_stock"
    assert fields_by_name["callable_summary"]["attrs"]["read_only"] is True
    assert fields_by_name["blank_summary"]["attrs"]["label"] == ""
    assert fields_by_name["blank_summary"]["attrs"]["empty_value_display"] == ""
    assert fields_by_name["blank_summary"]["attrs"]["value"] == ""
    assert fields_by_name["blank_summary"]["attrs"]["read_only"] is True

    empty_product = Product.objects.get(name="Beta")
    empty_response = admin_client.get(f"/admin-api/testapp/product/{empty_product.pk}/form")
    empty_fields_by_name = {field["name"]: field for field in empty_response.json()["form"]["fields"]}
    assert empty_fields_by_name["subtitle"]["attrs"]["value"] == "No subtitle"


def test_explicit_form_layouts_accept_callable_readonly_field_names(db, sample):
    def callable_summary(obj):
        return f"{obj.name}:{obj.stock_status}"

    callable_summary.short_description = "Callable summary"

    class ReadonlyLayoutProductAdmin(ModelAdmin):
        readonly_fields = ("upper_name", callable_summary)
        fieldsets = (
            (
                "Main",
                {
                    "fields": (("name", "upper_name"), "callable_summary"),
                    "classes": ("wide", "collapse"),
                    "description": "Primary product fields.",
                },
            ),
        )

        @display(description="Upper name")
        def upper_name(self, obj):
            return obj.name.upper()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ReadonlyLayoutProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    user = get_user_model().objects.create_user("readonly-layout-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    request.user = user

    assert "django_ninja_admin.E014" not in {error.id for error in model_admin.check()}
    assert list(model_admin.get_form_class(request, sample, change=True).base_fields) == ["name"]

    form = model_admin.get_form_description(request, sample)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert "fieldsets" not in form
    assert form["fieldset_layout"] == [
        {
            "name": "Main",
            "classes": ["wide", "collapse"],
            "description": "Primary product fields.",
            "fields": ["name", "upper_name", "callable_summary"],
            "rows": [{"fields": ["name", "upper_name"]}, {"fields": ["callable_summary"]}],
        }
    ]
    assert fields_by_name["callable_summary"]["attrs"]["label"] == "Callable summary"
    assert fields_by_name["callable_summary"]["attrs"]["value"] == "Alpha:in_stock"
    assert fields_by_name["upper_name"]["attrs"]["value"] == "ALPHA"


def test_form_description_marks_raw_id_and_filter_vertical_widget_modes(db, sample):
    user = get_user_model().objects.create_user("widget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    request.user = user
    Tag.objects.create(name="Available")

    class RawWidgetProductAdmin(ModelAdmin):
        raw_id_fields = ("category",)
        filter_vertical = ("tags",)

    model_admin = RawWidgetProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request, sample)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert fields_by_name["category"]["attrs"]["admin_widget"] == "raw_id"
    assert fields_by_name["category"]["attrs"]["raw_id"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "category",
        "related_model": "testapp.category",
        "related_app_label": "testapp",
        "related_model_name": "category",
        "related_object_name": "Category",
        "related_verbose_name": "category",
        "related_verbose_name_plural": "categorys",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
        "multiple": False,
        "url": "/admin-api/testapp/category",
        "query": {"_to_field": "id"},
    }
    assert fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_vertical"
    assert fields_by_name["tags"]["attrs"]["filtered_select"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "tags",
        "direction": "vertical",
        "is_stacked": True,
        "verbose_name": "tags",
        "selected_count": 2,
        "available_count": 3,
        "unselected_count": 1,
        "related_model": "testapp.tag",
        "related_app_label": "testapp",
        "related_model_name": "tag",
        "related_object_name": "Tag",
        "related_verbose_name": "tag",
        "related_verbose_name_plural": "tags",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
        "url": "/admin-api/testapp/tag",
        "query": {"_to_field": "id"},
    }
    assert {option["text"] for option in fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }


@isolate_apps("tests.testapp")
def test_form_description_omits_non_form_manual_through_many_to_many_from_default_layout(db):
    class Label(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class Article(models.Model):
        title = models.CharField(max_length=20)
        labels = models.ManyToManyField(Label, through="ArticleLabel", blank=True)

        class Meta:
            app_label = "testapp"

    class ArticleLabel(models.Model):
        article = models.ForeignKey(Article, on_delete=models.CASCADE)
        label = models.ForeignKey(Label, on_delete=models.CASCADE)
        note = models.CharField(max_length=20, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Article)
    model_admin = admin_site.get_model_admin(Article)
    request = RequestFactory().get("/manual-through-admin/testapp/article/form")
    request.user = AnonymousUser()

    form = model_admin.get_form_description(request)["form"]
    write_schema = model_admin.get_write_schema(request)

    assert [field["name"] for field in form["fields"]] == ["title"]
    assert form["fieldset_layout"] == [
        {
            "name": None,
            "classes": [],
            "description": None,
            "fields": ["title"],
            "rows": [{"fields": ["title"]}],
        }
    ]
    assert list(write_schema.model_fields) == ["title"]
    assert "labels" not in write_schema.model_json_schema()["properties"]


def test_form_description_exposes_multiwidget_metadata(db):
    user = get_user_model().objects.create_user("multiwidget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form")
    request.user = user

    class SplitWidgetProductForm(forms.ModelForm):
        release_window = forms.SplitDateTimeField(
            required=False,
            input_date_formats=["%Y-%m-%d"],
            input_time_formats=["%H:%M"],
            widget=forms.SplitDateTimeWidget(
                date_attrs={"data-part": "date"},
                time_attrs={"data-part": "time"},
                date_format="%Y-%m-%d",
                time_format="%H:%M",
            ),
        )
        product_code = forms.RegexField(required=False, regex=r"^[A-Z]{3}$")

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class SplitWidgetProductAdmin(ModelAdmin):
        form_class = SplitWidgetProductForm

    model_admin = SplitWidgetProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    field = next(item for item in form["fields"] if item["name"] == "release_window")
    code_field = next(item for item in form["fields"] if item["name"] == "product_code")
    attrs = field["attrs"]

    assert attrs["widget"] == "SplitDateTimeWidget"
    assert_no_rendered_field_attrs(attrs)
    assert attrs["use_fieldset"] is True
    assert attrs["supports_microseconds"] is False
    assert attrs["input_formats"] == [
        {"index": 0, "input_formats": ["%Y-%m-%d"]},
        {"index": 1, "input_formats": ["%H:%M"]},
    ]
    assert attrs["subwidgets"] == [
        {
            "name_suffix": "_0",
            "widget": "DateInput",
            "widget_attrs": {"data-part": "date"},
            "is_hidden": False,
            "is_localized": False,
            "multiple": False,
            "input_type": "text",
            "format": "%Y-%m-%d",
            "needs_multipart_form": False,
            "supports_microseconds": False,
        },
        {
            "name_suffix": "_1",
            "widget": "TimeInput",
            "widget_attrs": {"data-part": "time"},
            "is_hidden": False,
            "is_localized": False,
            "multiple": False,
            "input_type": "text",
            "format": "%H:%M",
            "needs_multipart_form": False,
            "supports_microseconds": False,
        },
    ]
    assert any(detail.get("pattern") == "^[A-Z]{3}$" for detail in code_field["attrs"]["validator_details"])


def test_form_description_exposes_select_date_widget_metadata(db):
    user = get_user_model().objects.create_user("selectdate-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form?release_date=2024-02-03")
    request.user = user

    class SelectDateProductForm(forms.ModelForm):
        release_date = forms.DateField(
            required=False,
            widget=forms.SelectDateWidget(
                years=[2024, 2025],
                months={1: "Jan", 2: "Feb"},
                empty_label=("Year", "Month", "Day"),
                attrs={"data-date": "release"},
            ),
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class SelectDateProductAdmin(ModelAdmin):
        form_class = SelectDateProductForm

    model_admin = SelectDateProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    attrs = next(field["attrs"] for field in form["fields"] if field["name"] == "release_date")

    assert attrs["widget"] == "SelectDateWidget"
    assert_no_rendered_field_attrs(attrs)
    assert attrs["input_type"] == "select"
    assert attrs["use_fieldset"] is True
    assert attrs["widget_attrs"] == {"data-date": "release"}
    assert attrs["value"] == "2024-02-03"
    assert attrs["select_date"] == {
        "order": ["month", "day", "year"],
        "years": [2024, 2025],
        "months": [{"value": 1, "label": "Jan"}, {"value": 2, "label": "Feb"}],
        "days": list(range(1, 32)),
        "empty_choices": {
            "year": {"value": "", "label": "Year"},
            "month": {"value": "", "label": "Month"},
            "day": {"value": "", "label": "Day"},
        },
        "selected": {"year": 2024, "month": 2, "day": 3},
    }


def test_form_description_exposes_filepath_field_metadata(db, tmp_path):
    fixture_file = tmp_path / "choice.txt"
    fixture_file.write_text("ok")
    skipped_file = tmp_path / "skipped.md"
    skipped_file.write_text("no")
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "deep.txt"
    nested_file.write_text("nested")

    class FilePathProductForm(forms.ModelForm):
        file_path = forms.FilePathField(
            path=str(tmp_path),
            match=r".*\.txt$",
            recursive=True,
            allow_files=True,
            allow_folders=False,
            required=False,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class FilePathProductAdmin(ModelAdmin):
        form_class = FilePathProductForm

    model_admin = FilePathProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    field = next(item for item in model_admin.get_form_fields_description(request) if item["name"] == "file_path")

    attrs = field["attrs"]
    choice_values = [value for value, _label in attrs["choices"]]
    assert field["type"] == "FilePathField"
    assert attrs["path"] == str(tmp_path)
    assert attrs["match"] == r".*\.txt$"
    assert attrs["recursive"] is True
    assert attrs["allow_files"] is True
    assert attrs["allow_folders"] is False
    assert str(fixture_file) in choice_values
    assert str(nested_file) in choice_values
    assert str(skipped_file) not in choice_values


def test_form_description_exposes_combo_field_metadata(db):
    class ComboProductForm(forms.ModelForm):
        combo_code = forms.ComboField(
            fields=[
                forms.CharField(max_length=5),
                forms.RegexField(regex=r"^[A-Z]+$"),
            ],
            required=False,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class ComboProductAdmin(ModelAdmin):
        form_class = ComboProductForm

    model_admin = ComboProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    field = next(item for item in model_admin.get_form_fields_description(request) if item["name"] == "combo_code")

    attrs = field["attrs"]
    assert field["type"] == "ComboField"
    assert [item["type"] for item in attrs["combo_fields"]] == ["CharField", "RegexField"]
    assert attrs["combo_fields"][0]["index"] == 0
    assert attrs["combo_fields"][0]["attrs"]["max_length"] == 5
    assert attrs["combo_fields"][1]["index"] == 1
    assert any(detail.get("pattern") == "^[A-Z]+$" for detail in attrs["combo_fields"][1]["attrs"]["validator_details"])


def test_form_description_exposes_numeric_step_metadata(db):
    class StepProductForm(forms.ModelForm):
        stepped_count = forms.IntegerField(required=False, step_size=2)
        offset_count = forms.IntegerField(required=False, min_value=1, step_size=2)
        stepped_price = forms.DecimalField(required=False, step_size=Decimal("0.25"), max_digits=4, decimal_places=2)

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class StepProductAdmin(ModelAdmin):
        form_class = StepProductForm

    model_admin = StepProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    fields_by_name = {item["name"]: item for item in model_admin.get_form_fields_description(request)}

    assert fields_by_name["stepped_count"]["attrs"]["step_size"] == 2
    assert "step_offset" not in fields_by_name["stepped_count"]["attrs"]
    assert fields_by_name["offset_count"]["attrs"]["step_size"] == 2
    assert fields_by_name["offset_count"]["attrs"]["step_offset"] == 1
    assert fields_by_name["stepped_price"]["attrs"]["step_size"] == "0.25"


@pytest.mark.parametrize(
    ("limit_choices_to", "expected"),
    [
        ({"name__startswith": "Cam"}, {"name__startswith": "Cam"}),
        (lambda: {"name__startswith": "Cam"}, {"name__startswith": "Cam"}),
        (
            models.Q(name__startswith="Cam"),
            {
                "connector": "AND",
                "negated": False,
                "children": [{"lookup": "name__startswith", "value": "Cam"}],
            },
        ),
    ],
    ids=["dict", "callable", "q"],
)
def test_form_description_exposes_relation_limit_choices_to(db, sample, monkeypatch, limit_choices_to, expected):
    user = get_user_model().objects.create_user("limit-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form")
    request.user = user
    category_field = Product._meta.get_field("category")
    monkeypatch.setattr(category_field.remote_field, "limit_choices_to", limit_choices_to)

    model_admin = ModelAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert fields_by_name["category"]["attrs"]["limit_choices_to"] == expected
