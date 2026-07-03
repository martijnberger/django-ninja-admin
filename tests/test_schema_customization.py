from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from django.db import models
from django.test.utils import isolate_apps
from pydantic import AnyUrl, IPvAnyAddress
from pydantic import Field as PydanticField

from django_ninja_admin import ModelAdmin, NinjaAdminSite, display


@isolate_apps("tests.testapp")
def test_many_to_many_schemas_preserve_string_target_field_constraints(db):
    class ArticleLabel(models.Model):
        code = models.SlugField(max_length=12, primary_key=True)
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class Article(models.Model):
        title = models.CharField(max_length=30)
        labels = models.ManyToManyField(ArticleLabel, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Article)
    model_admin = admin_site.get_model_admin(Article)

    output_schema = model_admin.get_output_schema().model_json_schema()
    write_schema = model_admin.get_write_schema(None).model_json_schema()

    assert output_schema["properties"]["labels"]["items"] == {
        "maxLength": 12,
        "pattern": r"^[-a-zA-Z0-9_]+\z",
        "type": "string",
    }
    labels_options = write_schema["properties"]["labels"]["anyOf"]
    labels_array_schema = next(option for option in labels_options if option.get("type") == "array")
    assert labels_array_schema["items"] == {
        "maxLength": 12,
        "pattern": r"^[-a-zA-Z0-9_]+\z",
        "type": "string",
    }


@isolate_apps("tests.testapp")
def test_schema_field_overrides_are_included_and_serialize_admin_methods(db):
    class OverrideProduct(models.Model):
        name = models.CharField(max_length=20)
        stock_status = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class ProductAdminWithOverride(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None)}

        @display(description="Custom note")
        def custom_note(self, obj):
            return f"{obj.name}:{obj.stock_status}"

    admin_site = NinjaAdminSite(include_auth=False)
    model_admin = ProductAdminWithOverride(OverrideProduct, admin_site)
    product = OverrideProduct(id=1, name="Alpha", stock_status="in_stock")

    assert "custom_note" in model_admin.get_output_schema().model_fields
    assert model_admin.serialize_object(product)["custom_note"] == "Alpha:in_stock"


@isolate_apps("tests.testapp")
def test_output_exclude_omits_model_fields_from_schema_examples_and_serialization(db):
    class OutputCategory(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class OutputAccount(models.Model):
        name = models.CharField(max_length=20)
        secret_token = models.CharField(max_length=50)
        category = models.ForeignKey(OutputCategory, on_delete=models.CASCADE)
        labels = models.ManyToManyField(OutputCategory, related_name="labeled_accounts", blank=True)

        class Meta:
            app_label = "testapp"

    class OutputAccountAdmin(ModelAdmin):
        output_exclude = ("secret_token", "category", "labels")

    model_admin = OutputAccountAdmin(OutputAccount, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_output_schema().model_json_schema()

    assert {"secret_token", "category_id", "category_label", "labels"}.isdisjoint(schema["properties"])
    assert {"secret_token", "category_id", "category_label", "labels"}.isdisjoint(schema["examples"][0])

    account = OutputAccount(
        id=5,
        name="Visible",
        secret_token="hidden",
        category=OutputCategory(id=7, name="Internal"),
    )

    assert model_admin.serialize_object(account) == {"id": 5, "name": "Visible"}


@isolate_apps("tests.testapp")
def test_non_auth_password_fields_are_included_in_generated_schemas(db):
    class Credential(models.Model):
        username = models.CharField(max_length=50)
        password = models.CharField(max_length=50)

        class Meta:
            app_label = "testapp"

    model_admin = ModelAdmin(Credential, NinjaAdminSite(auth=None, include_auth=False))

    assert "password" in model_admin.get_output_schema().model_fields
    assert "password" in model_admin.get_write_schema(None).model_fields


@isolate_apps("tests.testapp")
def test_schema_field_override_examples_validate_common_pydantic_types(db):
    class OverrideExample(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class ProductAdminWithTypedOverrideExamples(ModelAdmin):
        schema_field_overrides = {
            "tracking_id": UUID,
            "published_on": date,
            "published_at": datetime,
            "publish_time": time,
            "duration": timedelta,
            "homepage": AnyUrl,
            "host": IPvAnyAddress,
            "annotated_tracking_id": Annotated[UUID, "metadata"],
            "scores": dict[str, int],
            "tracking_ids": list[UUID],
            "published_slots": tuple[date, time],
            "durations": tuple[timedelta, ...],
            "flags": set[int],
            "nested_scores": dict[str, list[int]],
            "bounded_count": Annotated[int, PydanticField(ge=2, le=5)],
            "exclusive_ratio": Annotated[float, PydanticField(gt=1.5, lt=3.5)],
            "maximum_price": Annotated[Decimal, PydanticField(le=Decimal("5.00"))],
            "short_code": Annotated[str, PydanticField(min_length=3, max_length=5)],
            "score_list": Annotated[list[int], PydanticField(min_length=2)],
        }

    model_admin = ProductAdminWithTypedOverrideExamples(OverrideExample, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_output_schema()
    example = schema.model_json_schema()["examples"][0]

    assert example["tracking_id"] == "00000000-0000-4000-8000-000000000000"
    assert example["published_on"] == "2026-07-02"
    assert example["published_at"] == "2026-07-02T12:00:00+00:00"
    assert example["publish_time"] == "12:00:00"
    assert example["duration"] == "01:00:00"
    assert example["homepage"] == "https://example.com/"
    assert example["host"] == "192.0.2.1"
    assert example["annotated_tracking_id"] == "00000000-0000-4000-8000-000000000000"
    assert example["scores"] == {"example": 1}
    assert example["tracking_ids"] == ["00000000-0000-4000-8000-000000000000"]
    assert example["published_slots"] == ["2026-07-02", "12:00:00"]
    assert example["durations"] == ["01:00:00"]
    assert example["flags"] == [1]
    assert example["nested_scores"] == {"example": [1]}
    assert example["bounded_count"] == 2
    assert example["exclusive_ratio"] == 2.5
    assert example["maximum_price"] == "5.00"
    assert example["short_code"] == "xxx"
    assert example["score_list"] == [1, 1]
    schema.model_validate(example)


@isolate_apps("tests.testapp")
def test_ninja_registered_model_field_types_drive_admin_schema_inference(db):
    from ninja.orm import register_field
    from ninja.orm.fields import TYPES

    class AdminRegisteredCodeField(models.Field):
        def get_internal_type(self):
            return "AdminRegisteredCodeField"

        def db_type(self, connection):
            return "integer"

    sentinel = object()
    previous_type = TYPES.get("AdminRegisteredCodeField", sentinel)
    register_field("AdminRegisteredCodeField", int)

    try:

        class CustomCategory(models.Model):
            code = AdminRegisteredCodeField(primary_key=True)
            name = models.CharField(max_length=20)

            class Meta:
                app_label = "testapp"

        class CustomProduct(models.Model):
            name = models.CharField(max_length=20)
            category = models.ForeignKey(CustomCategory, on_delete=models.CASCADE)

            class Meta:
                app_label = "testapp"

        class CustomCollection(models.Model):
            name = models.CharField(max_length=20)
            categories = models.ManyToManyField(CustomCategory, related_name="custom_collections", blank=True)

            class Meta:
                app_label = "testapp"

        admin_site = NinjaAdminSite(auth=None, include_auth=False)
        admin_site.register(CustomCategory)
        admin_site.register(CustomProduct)
        admin_site.register(CustomCollection)
        category_admin = admin_site.get_model_admin(CustomCategory)
        product_admin = admin_site.get_model_admin(CustomProduct)
        collection_admin = admin_site.get_model_admin(CustomCollection)

        assert category_admin.get_pydantic_type_for_model_field(CustomCategory._meta.pk) is int
        assert (
            product_admin.get_pydantic_type_for_model_field(CustomProduct._meta.get_field("category").target_field)
            is int
        )

        category_schema = category_admin.get_output_schema().model_json_schema()
        product_output_schema = product_admin.get_output_schema().model_json_schema()
        product_write_schema = product_admin.get_write_schema(None).model_json_schema()
        collection_output_schema = collection_admin.get_output_schema().model_json_schema()

        assert category_schema["properties"]["code"]["type"] == "integer"
        assert product_output_schema["properties"]["category_id"]["type"] == "integer"
        assert collection_output_schema["properties"]["categories"]["items"]["type"] == "integer"
        assert product_write_schema["properties"]["category"]["type"] == "integer"
        assert category_schema["examples"][0]["code"] == 1
        assert product_output_schema["examples"][0]["category_id"] == 1
        assert collection_output_schema["examples"][0]["categories"] == [1]
        category_admin.get_output_schema().model_validate(category_schema["examples"][0])
        product_admin.get_output_schema().model_validate(product_output_schema["examples"][0])
        collection_admin.get_output_schema().model_validate(collection_output_schema["examples"][0])

        category = CustomCategory(code=7, name="Custom")
        product = CustomProduct(id=1, name="Example", category=category)
        assert category_admin.serialize_object(category)["code"] == 7
        assert product_admin.serialize_object(product)["category_id"] == 7
    finally:
        if previous_type is sentinel:
            TYPES.pop("AdminRegisteredCodeField", None)
        else:
            TYPES["AdminRegisteredCodeField"] = previous_type
