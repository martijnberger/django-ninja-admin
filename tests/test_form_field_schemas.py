from datetime import date, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django import forms
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
)
from django.test import RequestFactory
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import ModelAdmin, NinjaAdminSite, TabularInline
from tests.testapp.models import Product, ProductImage

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


def test_write_schema_uses_richer_pydantic_types_for_form_fields(sample, tmp_path):
    fixture_file = tmp_path / "choice.txt"
    fixture_file.write_text("ok")

    class RichPayloadProductForm(forms.ModelForm):
        metadata = forms.JSONField(required=False)
        tracking_id = forms.UUIDField(required=False)
        host = forms.GenericIPAddressField(required=False)
        contact_email = forms.EmailField(required=False)
        homepage = forms.URLField(required=False)
        file_path = forms.FilePathField(path=str(tmp_path), match=r".*\.txt$", required=False)
        combo_code = forms.ComboField(
            fields=[
                forms.CharField(max_length=5),
                forms.RegexField(regex=r"^[A-Z]+$"),
            ],
            required=False,
        )
        custom_date = forms.DateField(required=False, input_formats=["%d/%m/%Y"])
        custom_time = forms.TimeField(required=False, input_formats=["%H.%M"])
        custom_datetime = forms.DateTimeField(required=False, input_formats=["%d/%m/%Y %H.%M"])
        duration = forms.DurationField(required=False)
        review_required = forms.NullBooleanField(required=False)
        optional_reference = forms.CharField(required=False, empty_value=None)
        release_window = forms.SplitDateTimeField(
            required=False,
            input_date_formats=["%Y-%m-%d"],
            input_time_formats=["%H:%M"],
        )
        bounded_name = forms.CharField(required=False, min_length=3, max_length=8)
        validator_bounded_name = forms.CharField(
            required=False,
            max_length=30,
            validators=[MinLengthValidator(3), MaxLengthValidator(8)],
        )
        validator_combo_code = forms.ComboField(
            fields=[
                forms.CharField(
                    max_length=20,
                    validators=[MinLengthValidator(4), MaxLengthValidator(10)],
                )
            ],
            required=False,
        )
        bounded_count = forms.IntegerField(required=False, min_value=2, max_value=5)
        validator_bounded_count = forms.IntegerField(
            required=False,
            validators=[MinValueValidator(2), MaxValueValidator(5)],
        )
        validator_bounded_ratio = forms.FloatField(
            required=False,
            validators=[MinValueValidator(0.5), MaxValueValidator(2.5)],
        )
        mixed_bound_count = forms.IntegerField(
            required=False,
            min_value=4,
            max_value=8,
            validators=[MinValueValidator(2), MaxValueValidator(10)],
        )
        stepped_count = forms.IntegerField(required=False, step_size=2)
        offset_count = forms.IntegerField(required=False, min_value=1, step_size=2)
        bounded_price = forms.DecimalField(
            required=False,
            min_value=Decimal("1.00"),
            max_value=Decimal("9.99"),
            max_digits=4,
            decimal_places=2,
        )
        validator_bounded_price = forms.DecimalField(
            required=False,
            max_digits=5,
            decimal_places=2,
            validators=[MinValueValidator(Decimal("1.00")), MaxValueValidator(Decimal("9.99"))],
        )
        stepped_price = forms.DecimalField(required=False, step_size=Decimal("0.25"), max_digits=4, decimal_places=2)
        product_code = forms.CharField(
            required=False,
            min_length=3,
            max_length=3,
            validators=[RegexValidator(r"^[A-Z]{3}$")],
        )
        tracked_label = forms.CharField(required=False, show_hidden_initial=True)
        unstripped_code = forms.CharField(
            required=False,
            validators=[RegexValidator(r"^[A-Z]{3}$")],
            strip=False,
        )
        sku = forms.CharField(required=False, validators=[RegexValidator(r"^SKU-[0-9]+$")])
        slug = forms.SlugField(required=False)

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class RichPayloadProductAdmin(ModelAdmin):
        form_class = RichPayloadProductForm

    model_admin = RichPayloadProductAdmin(Product, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_write_schema(None)
    tracking_id = "550e8400-e29b-41d4-a716-446655440000"

    validated = schema.model_validate(
        {
            "name": "Typed payload",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": "in_stock",
            "metadata": {"nested": [1, "two"]},
            "tracking_id": tracking_id,
            "host": "2001:db8::1",
            "contact_email": "buyer@example.com",
            "homepage": "https://example.com/products",
            "file_path": str(fixture_file),
            "combo_code": "ABCDE",
            "custom_date": "01/07/2026",
            "custom_time": "09.30",
            "custom_datetime": "01/07/2026 09.30",
            "duration": "1 02:03:04",
            "review_required": "unknown",
            "optional_reference": "REF-1",
            "release_window": ["2026-07-01", "09:30"],
            "bounded_name": "Camera",
            "validator_bounded_name": "Camera",
            "validator_combo_code": "CODE",
            "bounded_count": 3,
            "validator_bounded_count": 3,
            "validator_bounded_ratio": 1.5,
            "mixed_bound_count": 5,
            "stepped_count": 4,
            "offset_count": 3,
            "bounded_price": "4.50",
            "validator_bounded_price": "4.50",
            "stepped_price": "1.25",
            "product_code": " ABC ",
            "tracked_label": "Camera label",
            "unstripped_code": "XYZ",
            "sku": "SKU-123",
            "slug": "camera-case",
        }
    )

    assert validated.metadata == {"nested": [1, "two"]}
    assert validated.tracking_id.hex == "550e8400e29b41d4a716446655440000"
    assert str(validated.host) == "2001:db8::1"
    assert validated.contact_email == "buyer@example.com"
    assert str(validated.homepage) == "https://example.com/products"
    assert validated.file_path == str(fixture_file)
    assert validated.combo_code == "ABCDE"
    assert validated.custom_date == date(2026, 7, 1)
    assert validated.custom_time == time(9, 30)
    assert validated.custom_datetime.year == 2026
    assert validated.custom_datetime.month == 7
    assert validated.custom_datetime.day == 1
    assert validated.custom_datetime.hour == 9
    assert validated.custom_datetime.minute == 30
    assert validated.custom_datetime.tzinfo is not None
    assert validated.duration == timedelta(days=1, hours=2, minutes=3, seconds=4)
    assert validated.review_required is None
    assert validated.optional_reference == "REF-1"
    assert validated.release_window == (date(2026, 7, 1), time(9, 30))
    assert validated.bounded_name == "Camera"
    assert validated.validator_bounded_name == "Camera"
    assert validated.validator_combo_code == "CODE"
    assert validated.bounded_count == 3
    assert validated.validator_bounded_count == 3
    assert validated.validator_bounded_ratio == 1.5
    assert validated.mixed_bound_count == 5
    assert validated.stepped_count == 4
    assert validated.offset_count == 3
    assert validated.bounded_price == Decimal("4.50")
    assert validated.validator_bounded_price == Decimal("4.50")
    assert validated.stepped_price == Decimal("1.25")
    assert validated.product_code == "ABC"
    assert validated.tracked_label == "Camera label"
    assert validated.unstripped_code == "XYZ"
    assert validated.sku == "SKU-123"
    assert validated.slug == "camera-case"

    json_schema = schema.model_json_schema()["properties"]
    assert json_schema["bounded_name"]["anyOf"][0]["maxLength"] == 8
    assert json_schema["bounded_name"]["anyOf"][0]["minLength"] == 3
    assert json_schema["validator_bounded_name"]["anyOf"][0]["maxLength"] == 8
    assert json_schema["validator_bounded_name"]["anyOf"][0]["minLength"] == 3
    assert json_schema["validator_combo_code"]["anyOf"][0]["maxLength"] == 10
    assert json_schema["validator_combo_code"]["anyOf"][0]["minLength"] == 4
    assert json_schema["bounded_count"]["anyOf"][0]["maximum"] == 5
    assert json_schema["bounded_count"]["anyOf"][0]["minimum"] == 2
    assert json_schema["validator_bounded_count"]["anyOf"][0]["maximum"] == 5
    assert json_schema["validator_bounded_count"]["anyOf"][0]["minimum"] == 2
    assert json_schema["validator_bounded_ratio"]["anyOf"][0]["type"] == "number"
    assert json_schema["validator_bounded_ratio"]["anyOf"][0]["maximum"] == 2.5
    assert json_schema["validator_bounded_ratio"]["anyOf"][0]["minimum"] == 0.5
    assert json_schema["mixed_bound_count"]["anyOf"][0]["maximum"] == 8
    assert json_schema["mixed_bound_count"]["anyOf"][0]["minimum"] == 4
    assert json_schema["stepped_count"]["anyOf"][0]["multipleOf"] == 2
    assert json_schema["offset_count"]["anyOf"][0]["minimum"] == 1
    assert "multipleOf" not in json_schema["offset_count"]["anyOf"][0]
    assert json_schema["contact_email"]["anyOf"][0]["format"] == "email"
    assert json_schema["homepage"]["anyOf"][0]["format"] == "uri"
    assert json_schema["file_path"]["anyOf"][0]["const"] == str(fixture_file)
    assert json_schema["combo_code"]["anyOf"][0]["maxLength"] == 5
    assert json_schema["combo_code"]["anyOf"][0]["pattern"] == "^[A-Z]+$"
    assert json_schema["custom_date"]["anyOf"][0]["format"] == "date"
    assert json_schema["custom_time"]["anyOf"][0]["format"] == "time"
    assert json_schema["custom_datetime"]["anyOf"][0]["format"] == "date-time"
    assert {option["type"] for option in json_schema["review_required"]["anyOf"]} == {"boolean", "null"}
    assert json_schema["release_window"]["anyOf"][0]["prefixItems"] == [
        {"format": "date", "type": "string"},
        {"format": "time", "type": "string"},
    ]
    assert json_schema["bounded_price"]["anyOf"][0]["maximum"] == 9.99
    assert json_schema["bounded_price"]["anyOf"][0]["minimum"] == 1.0
    assert json_schema["bounded_price"]["anyOf"][1]["pattern"]
    assert json_schema["validator_bounded_price"]["anyOf"][0]["maximum"] == 9.99
    assert json_schema["validator_bounded_price"]["anyOf"][0]["minimum"] == 1.0
    assert json_schema["validator_bounded_price"]["anyOf"][1]["pattern"]
    assert json_schema["stepped_price"]["anyOf"][0]["multipleOf"] == 0.25
    assert json_schema["product_code"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"
    assert json_schema["unstripped_code"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"
    assert json_schema["sku"]["anyOf"][0]["pattern"] == "^SKU-[0-9]+$"
    assert json_schema["slug"]["anyOf"][0]["pattern"].endswith(r"\z")

    fields_by_name = {
        field["name"]: field for field in model_admin.get_form_fields_description(RequestFactory().get("/"))
    }
    assert fields_by_name["review_required"]["type"] == "NullBooleanField"
    assert fields_by_name["review_required"]["attrs"]["null_boolean"] is True
    assert fields_by_name["review_required"]["attrs"]["widget"] == "NullBooleanSelect"
    name_attrs = fields_by_name["name"]["attrs"]
    assert_no_rendered_field_attrs(name_attrs)
    assert fields_by_name["optional_reference"]["attrs"]["empty_value"] is None
    assert fields_by_name["product_code"]["attrs"]["strip"] is True
    assert fields_by_name["validator_bounded_name"]["attrs"]["min_length"] == 3
    assert fields_by_name["validator_bounded_name"]["attrs"]["max_length"] == 8
    assert fields_by_name["validator_combo_code"]["attrs"]["combo_fields"][0]["attrs"]["min_length"] == 4
    assert fields_by_name["validator_combo_code"]["attrs"]["combo_fields"][0]["attrs"]["max_length"] == 10
    assert fields_by_name["validator_bounded_count"]["attrs"]["min_value"] == 2
    assert fields_by_name["validator_bounded_count"]["attrs"]["max_value"] == 5
    assert fields_by_name["validator_bounded_ratio"]["attrs"]["min_value"] == 0.5
    assert fields_by_name["validator_bounded_ratio"]["attrs"]["max_value"] == 2.5
    assert fields_by_name["mixed_bound_count"]["attrs"]["min_value"] == 4
    assert fields_by_name["mixed_bound_count"]["attrs"]["max_value"] == 8
    assert fields_by_name["validator_bounded_price"]["attrs"]["min_value"] == "1.00"
    assert fields_by_name["validator_bounded_price"]["attrs"]["max_value"] == "9.99"
    tracked_label_attrs = fields_by_name["tracked_label"]["attrs"]
    assert_no_rendered_field_attrs(tracked_label_attrs)
    assert fields_by_name["unstripped_code"]["attrs"]["strip"] is False

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "review_required": "maybe",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "unstripped_code": "XYZ",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "validator_bounded_name": "toolong-name",
                "validator_combo_code": "ABC",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "validator_bounded_count": 6,
                "validator_bounded_ratio": 3.0,
                "validator_bounded_price": "10.00",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": "not-a-uuid",
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "custom_date": "2026-07-01",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "stepped_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "offset_count": 4,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "combo_code": "abc",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "stepped_price": "1.30",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "file_path": str(tmp_path / "missing.txt"),
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "release_window": ["2026-07-01", "not-a-time"],
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "contact_email": "not-an-email",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "homepage": "not-a-url",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "not-an-ip",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "not-a-duration",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "No",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 6,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "123.45",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "abc",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "not a slug",
            }
        )


def test_form_schema_field_overrides_drive_parent_bulk_and_inline_schemas(sample):
    class OverridePayloadProductForm(forms.ModelForm):
        metadata = forms.CharField()

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status", "metadata")

    class OverridePayloadImageForm(forms.ModelForm):
        details = forms.CharField()

        class Meta:
            model = ProductImage
            fields = ("title", "details")

    class OverridePayloadInline(TabularInline):
        model = ProductImage
        form_class = OverridePayloadImageForm
        form_schema_field_overrides = {"details": dict[str, int]}

    class OverridePayloadProductAdmin(ModelAdmin):
        form_class = OverridePayloadProductForm
        list_display = ("name", "stock_status")
        list_editable = ("stock_status",)
        form_schema_field_overrides = {"metadata": dict[str, int], "stock_status": bool}
        inlines = [OverridePayloadInline]

    admin_site = NinjaAdminSite(include_auth=False)
    model_admin = OverridePayloadProductAdmin(Product, admin_site)
    create_schema = model_admin.get_write_schema(None)
    validated = create_schema.model_validate(
        {
            "name": "Override payload",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": True,
            "metadata": {"priority": 3},
        }
    )

    assert validated.stock_status is True
    assert validated.metadata == {"priority": 3}
    create_properties = create_schema.model_json_schema()["properties"]
    assert create_properties["stock_status"]["type"] == "boolean"
    assert create_properties["metadata"]["additionalProperties"]["type"] == "integer"
    assert create_schema.model_json_schema()["examples"][0]["metadata"] == {"example": 1}
    assert create_schema.model_json_schema()["examples"][0]["stock_status"] is True
    create_schema.model_validate(create_schema.model_json_schema()["examples"][0])

    with pytest.raises(PydanticValidationError):
        create_schema.model_validate(
            {
                "name": "Override payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {"priority": "high"},
            }
        )

    bulk_schema = model_admin.get_bulk_payload_schema(None)
    bulk_payload = bulk_schema.model_validate({"data": [{"pk": sample.pk, "stock_status": False}]})
    assert bulk_payload.data[0].stock_status is False
    bulk_row_schema = bulk_schema.model_fields["data"].annotation.__args__[0]
    assert bulk_row_schema.model_json_schema()["examples"][0]["stock_status"] is True
    bulk_row_schema.model_validate(bulk_row_schema.model_json_schema()["examples"][0])
    bulk_schema.model_validate(bulk_schema.model_json_schema()["examples"][0])
    with pytest.raises(PydanticValidationError):
        bulk_schema.model_validate({"data": [{"pk": sample.pk, "stock_status": "in_stock"}]})

    inline = model_admin.get_inline_instances(None, check_permissions=False)[0]
    inline_row_schema = inline.get_inline_row_schema(None)
    inline_row = inline_row_schema.model_validate({"title": "Front", "details": {"priority": 1}})
    assert inline_row.details == {"priority": 1}
    inline_properties = inline_row_schema.model_json_schema()["properties"]
    assert inline_properties["details"]["additionalProperties"]["type"] == "integer"
    assert inline_row_schema.model_json_schema()["examples"][0]["details"] == {"example": 1}
    inline_row_schema.model_validate(inline_row_schema.model_json_schema()["examples"][0])
    with pytest.raises(PydanticValidationError):
        inline_row_schema.model_validate({"title": "Front", "details": {"priority": "high"}})

    create_route_example = admin_site._mutation_payload_example(model_admin, change=False, partial=False)
    assert create_route_example["data"]["metadata"] == {"example": 1}
    assert create_route_example["data"]["stock_status"] is True
    create_schema.model_validate(create_route_example["data"])
    inline_add_example = create_route_example["inlines"]["testapp.productimage"]["add"][0]
    assert inline_add_example["details"] == {"example": 1}
    inline_row_schema.model_validate(inline_add_example)

    bulk_route_example = admin_site._bulk_payload_example(model_admin)
    assert bulk_route_example["data"][0]["stock_status"] is True
    bulk_schema.model_validate(bulk_route_example)

    request = RequestFactory().get("/")
    fields_by_name = {field["name"]: field for field in model_admin.get_form_fields_description(request)}
    assert (
        fields_by_name["metadata"]["attrs"]["input_schema_override"]["schema"]["additionalProperties"]["type"]
        == "integer"
    )
    assert fields_by_name["stock_status"]["attrs"]["input_schema_override"]["schema"]["type"] == "boolean"
    assert "input_schema_override" not in fields_by_name["name"]["attrs"]

    changelist_fields_by_name = {
        field["name"]: field for field in model_admin.get_changelist_form_fields_description(request)
    }
    assert changelist_fields_by_name["stock_status"]["attrs"]["input_schema_override"]["schema"]["type"] == "boolean"

    inline_fields_by_name = {field["name"]: field for field in inline.get_form_fields_description(request, None)}
    assert (
        inline_fields_by_name["details"]["attrs"]["input_schema_override"]["schema"]["additionalProperties"]["type"]
        == "integer"
    )


def test_write_schema_uses_choice_types_for_multiple_choice_fields(sample):
    uuid_choice = "550e8400-e29b-41d4-a716-446655440000"
    other_uuid_choice = "550e8400-e29b-41d4-a716-446655440001"

    class MultiChoiceProductForm(forms.ModelForm):
        status_override = forms.ChoiceField(
            required=False,
            choices=(("draft", "Draft"), ("live", "Live")),
        )
        grouped_status = forms.ChoiceField(
            required=False,
            choices=(
                ("Publishing", (("draft", "Draft"), ("live", "Live"))),
                ("Archive", (("archived", "Archived"),)),
            ),
        )
        decimal_status = forms.ChoiceField(
            required=False,
            choices=((Decimal("1.25"), "One"), (Decimal("2.50"), "Two")),
        )
        uuid_status = forms.ChoiceField(
            required=False,
            choices=((UUID(uuid_choice), "One"), (UUID(other_uuid_choice), "Two")),
        )
        numeric_flags = forms.MultipleChoiceField(
            required=False,
            choices=((1, "One"), (2, "Two")),
        )
        decimal_flags = forms.MultipleChoiceField(
            required=False,
            choices=((Decimal("1.25"), "One"), (Decimal("2.50"), "Two")),
        )
        mixed_flags = forms.MultipleChoiceField(
            required=False,
            choices=((1, "One"), ("two", "Two")),
        )
        typed_number = forms.TypedChoiceField(
            required=False,
            choices=(("1", "One"), ("2", "Two")),
            coerce=int,
        )
        typed_numbers = forms.TypedMultipleChoiceField(
            required=False,
            choices=(("1", "One"), ("2", "Two")),
            coerce=int,
        )
        typed_decimal = forms.TypedChoiceField(
            required=False,
            choices=(("1.25", "One"), ("2.50", "Two")),
            coerce=Decimal,
        )
        typed_floats = forms.TypedMultipleChoiceField(
            required=False,
            choices=(("1.5", "One"), ("2.5", "Two")),
            coerce=float,
        )
        typed_uuid = forms.TypedChoiceField(
            required=False,
            choices=((uuid_choice, "One"), (other_uuid_choice, "Two")),
            coerce=UUID,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class MultiChoiceProductAdmin(ModelAdmin):
        form_class = MultiChoiceProductForm

    model_admin = MultiChoiceProductAdmin(Product, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_write_schema(None)

    validated = schema.model_validate(
        {
            "name": "Typed choices",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": "in_stock",
            "status_override": "draft",
            "grouped_status": "archived",
            "decimal_status": "1.25",
            "uuid_status": uuid_choice,
            "numeric_flags": [1, 2],
            "decimal_flags": ["1.25", "2.50"],
            "mixed_flags": [1, "two"],
            "typed_number": "1",
            "typed_numbers": ["1", "2"],
            "typed_decimal": "1.25",
            "typed_floats": ["1.5", "2.5"],
            "typed_uuid": uuid_choice,
        }
    )

    json_schema = schema.model_json_schema()["properties"]
    assert json_schema["status_override"]["anyOf"][0]["enum"] == ["draft", "live"]
    assert json_schema["grouped_status"]["anyOf"][0]["enum"] == ["draft", "live", "archived"]
    assert json_schema["decimal_status"]["anyOf"][0]["enum"] == ["1.25", "2.50"]
    assert json_schema["uuid_status"]["anyOf"][0]["enum"] == [uuid_choice, other_uuid_choice]
    assert json_schema["numeric_flags"]["anyOf"][0]["items"]["enum"] == [1, 2]
    assert json_schema["decimal_flags"]["anyOf"][0]["items"]["enum"] == ["1.25", "2.50"]
    assert json_schema["mixed_flags"]["anyOf"][0]["items"]["enum"] == [1, "two"]
    assert json_schema["typed_number"]["anyOf"][0]["enum"] == [1, 2]
    assert json_schema["typed_numbers"]["anyOf"][0]["items"]["enum"] == [1, 2]
    assert json_schema["typed_decimal"]["anyOf"][0]["enum"] == ["1.25", "2.50"]
    assert json_schema["typed_floats"]["anyOf"][0]["items"]["enum"] == [1.5, 2.5]
    assert json_schema["typed_uuid"]["anyOf"][0]["enum"] == [uuid_choice, other_uuid_choice]

    fields_by_name = {
        field["name"]: field for field in model_admin.get_form_fields_description(RequestFactory().get("/"))
    }
    assert fields_by_name["status_override"]["attrs"]["choices"] == [("draft", "Draft"), ("live", "Live")]
    assert fields_by_name["status_override"]["attrs"]["choice_options"] == [
        {"value": "draft", "raw_value": "draft", "label": "Draft"},
        {"value": "live", "raw_value": "live", "label": "Live"},
    ]
    assert "choice_groups" not in fields_by_name["status_override"]["attrs"]
    assert fields_by_name["grouped_status"]["attrs"]["choices"] == [
        ("draft", "Draft"),
        ("live", "Live"),
        ("archived", "Archived"),
    ]
    assert fields_by_name["grouped_status"]["attrs"]["choice_groups"] == [
        {
            "label": "Publishing",
            "options": [
                {"value": "draft", "raw_value": "draft", "label": "Draft"},
                {"value": "live", "raw_value": "live", "label": "Live"},
            ],
        },
        {
            "label": "Archive",
            "options": [{"value": "archived", "raw_value": "archived", "label": "Archived"}],
        },
    ]
    assert_no_rendered_field_attrs(fields_by_name["grouped_status"]["attrs"])
    assert fields_by_name["numeric_flags"]["attrs"]["choices"] == [("1", "One"), ("2", "Two")]
    assert fields_by_name["numeric_flags"]["attrs"]["choice_options"] == [
        {"value": "1", "raw_value": 1, "label": "One"},
        {"value": "2", "raw_value": 2, "label": "Two"},
    ]
    assert fields_by_name["typed_decimal"]["attrs"]["choice_options"] == [
        {"value": "1.25", "raw_value": "1.25", "coerced_value": "1.25", "label": "One"},
        {"value": "2.50", "raw_value": "2.50", "coerced_value": "2.50", "label": "Two"},
    ]
    assert fields_by_name["typed_decimal"]["attrs"]["choice_coerce"] == "Decimal"
    assert fields_by_name["typed_number"]["attrs"]["choice_options"] == [
        {"value": "1", "raw_value": "1", "coerced_value": 1, "label": "One"},
        {"value": "2", "raw_value": "2", "coerced_value": 2, "label": "Two"},
    ]
    assert fields_by_name["typed_number"]["attrs"]["choice_coerce"] == "int"
    assert fields_by_name["typed_floats"]["attrs"]["choice_options"] == [
        {"value": "1.5", "raw_value": "1.5", "coerced_value": 1.5, "label": "One"},
        {"value": "2.5", "raw_value": "2.5", "coerced_value": 2.5, "label": "Two"},
    ]
    assert fields_by_name["typed_floats"]["attrs"]["choice_coerce"] == "float"
    assert fields_by_name["typed_uuid"]["attrs"]["choice_options"] == [
        {"value": uuid_choice, "raw_value": uuid_choice, "coerced_value": uuid_choice, "label": "One"},
        {
            "value": other_uuid_choice,
            "raw_value": other_uuid_choice,
            "coerced_value": other_uuid_choice,
            "label": "Two",
        },
    ]
    assert fields_by_name["typed_uuid"]["attrs"]["choice_coerce"] == "UUID"
    assert fields_by_name["decimal_status"]["attrs"]["choice_options"] == [
        {"value": "1.25", "raw_value": "1.25", "label": "One"},
        {"value": "2.50", "raw_value": "2.50", "label": "Two"},
    ]
    assert fields_by_name["uuid_status"]["attrs"]["choice_options"] == [
        {"value": uuid_choice, "raw_value": uuid_choice, "label": "One"},
        {"value": other_uuid_choice, "raw_value": other_uuid_choice, "label": "Two"},
    ]

    assert validated.status_override == "draft"
    assert validated.grouped_status == "archived"
    assert validated.decimal_status == "1.25"
    assert validated.uuid_status == uuid_choice
    assert validated.numeric_flags == [1, 2]
    assert validated.decimal_flags == ["1.25", "2.50"]
    assert validated.mixed_flags == [1, "two"]
    assert validated.typed_number == 1
    assert validated.typed_numbers == [1, 2]
    assert validated.typed_decimal == Decimal("1.25")
    assert validated.typed_floats == [1.5, 2.5]
    assert validated.typed_uuid == UUID(uuid_choice)

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": ["one"],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "deleted",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "3",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["3"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "archived",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [3],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": ["three"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "one",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["one"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_decimal": "3.75",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_floats": ["3.5"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_uuid": "550e8400-e29b-41d4-a716-446655440099",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "decimal_status": "3.75",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "uuid_status": "550e8400-e29b-41d4-a716-446655440099",
            }
        )
