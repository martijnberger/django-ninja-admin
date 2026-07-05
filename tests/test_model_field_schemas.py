import math
from decimal import Decimal

import pytest
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
    StepValueValidator,
)
from django.db import models
from django.test import RequestFactory
from django.test.utils import isolate_apps
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import NinjaAdminSite


@isolate_apps("tests.testapp")
def test_image_field_has_typed_schema_and_image_metadata(db):
    class GalleryImage(models.Model):
        image = models.ImageField(
            upload_to="photos",
            width_field="width",
            height_field="height",
            blank=True,
        )
        width = models.PositiveIntegerField(null=True, blank=True)
        height = models.PositiveIntegerField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(GalleryImage)
    model_admin = admin_site.get_model_admin(GalleryImage)
    request = RequestFactory().get("/")
    obj = GalleryImage(id=1, image="photos/sample.png", width=640, height=480)

    output_schema = model_admin.get_output_schema().model_json_schema()
    image_schema = output_schema["properties"]["image"]["anyOf"]
    assert any(option.get("$ref", "").endswith("ImageFieldValue") for option in image_schema)
    assert output_schema["$defs"]["ImageFieldValue"]["properties"]["width"]["anyOf"][0]["type"] == "integer"

    image_field = next(
        field for field in model_admin.get_form_fields_description(request, obj) if field["name"] == "image"
    )
    assert image_field["type"] == "ImageField"
    assert image_field["attrs"]["image"] is True
    assert image_field["attrs"]["accepted_content_types"] == ["image/*"]
    assert image_field["attrs"]["upload_to"] == "photos"
    assert image_field["attrs"]["width_field"] == "width"
    assert image_field["attrs"]["height_field"] == "height"
    assert image_field["attrs"]["current_file"] == {
        "name": "photos/sample.png",
        "url": "/media/photos/sample.png",
        "width": None,
        "height": None,
    }

    assert model_admin.serialize_object(obj, request)["image"] == {
        "name": "photos/sample.png",
        "url": "/media/photos/sample.png",
        "width": None,
        "height": None,
    }


@isolate_apps("tests.testapp")
def test_email_and_url_model_fields_have_formatted_output_schemas(db):
    class Contact(models.Model):
        email = models.EmailField()
        website = models.URLField()
        backup_url = models.URLField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Contact)
    model_admin = admin_site.get_model_admin(Contact)

    output_schema = model_admin.get_output_schema().model_json_schema()

    assert output_schema["properties"]["email"] == {
        "format": "email",
        "maxLength": 254,
        "title": "Email",
        "type": "string",
    }
    assert output_schema["properties"]["website"] == {
        "format": "uri",
        "maxLength": 200,
        "title": "Website",
        "type": "string",
    }
    assert output_schema["properties"]["backup_url"] == {
        "anyOf": [{"format": "uri", "maxLength": 200, "type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Backup Url",
    }
    assert model_admin.serialize_object(
        Contact(
            id=1,
            email="user@example.com",
            website="https://example.com/",
            backup_url=None,
        )
    ) == {
        "id": 1,
        "email": "user@example.com",
        "website": "https://example.com/",
        "backup_url": None,
    }


@isolate_apps("tests.testapp")
def test_ip_address_model_fields_have_native_output_and_relation_schemas(db):
    class Host(models.Model):
        address = models.GenericIPAddressField(primary_key=True)
        optional_address = models.GenericIPAddressField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    class HostLink(models.Model):
        host = models.ForeignKey(Host, to_field="address", on_delete=models.CASCADE)
        hosts = models.ManyToManyField(Host, related_name="host_links", blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Host)
    admin_site.register(HostLink)
    host_admin = admin_site.get_model_admin(Host)
    link_admin = admin_site.get_model_admin(HostLink)

    host_schema = host_admin.get_output_schema()
    host_output_schema = host_schema.model_json_schema()
    link_output_schema = link_admin.get_output_schema().model_json_schema()
    link_write_schema = link_admin.get_write_schema(None)
    link_write_json_schema = link_write_schema.model_json_schema()

    assert host_output_schema["properties"]["address"] == {
        "format": "ipvanyaddress",
        "title": "Address",
        "type": "string",
    }
    assert host_output_schema["properties"]["optional_address"] == {
        "anyOf": [{"format": "ipvanyaddress", "type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Optional Address",
    }
    assert link_write_json_schema["properties"]["host"] == {
        "format": "ipvanyaddress",
        "title": "Host",
        "type": "string",
    }
    assert link_output_schema["properties"]["host_id"] == {
        "format": "ipvanyaddress",
        "title": "Host Id",
        "type": "string",
    }
    assert link_output_schema["properties"]["hosts"]["items"] == {
        "format": "ipvanyaddress",
        "type": "string",
    }

    host_schema.model_validate({"address": "2001:db8::1", "optional_address": None})
    link_write_schema.model_validate({"host": "192.0.2.10", "hosts": ["2001:db8::1"]})
    with pytest.raises(PydanticValidationError):
        host_schema.model_validate({"address": "not-an-ip", "optional_address": None})
    with pytest.raises(PydanticValidationError):
        link_write_schema.model_validate({"host": "not-an-ip", "hosts": ["2001:db8::1"]})
    assert host_admin.serialize_object(Host(address="2001:db8::1", optional_address=None)) == {
        "address": "2001:db8::1",
        "optional_address": None,
    }


@isolate_apps("tests.testapp")
def test_json_model_fields_have_explicit_output_and_write_schemas(db):
    class JsonRecord(models.Model):
        payload = models.JSONField(default=dict)
        optional_payload = models.JSONField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(JsonRecord)
    model_admin = admin_site.get_model_admin(JsonRecord)

    output_schema = model_admin.get_output_schema()
    output_json_schema = output_schema.model_json_schema()
    write_schema = model_admin.get_write_schema(None)
    write_json_schema = write_schema.model_json_schema()
    json_value_schema = {
        "anyOf": [
            {"additionalProperties": {"$ref": "#/$defs/FieldMetadataValue"}, "type": "object"},
            {"items": {"$ref": "#/$defs/FieldMetadataValue"}, "type": "array"},
            {"type": "string"},
            {"type": "integer"},
            {"$ref": "#/$defs/FiniteJsonFloat"},
            {"type": "boolean"},
            {"type": "null"},
        ],
    }

    assert output_json_schema["$defs"]["FiniteJsonFloat"] == {"type": "number"}
    assert output_json_schema["$defs"]["FieldMetadataValue"] == json_value_schema
    assert write_json_schema["$defs"]["FiniteJsonFloat"] == {"type": "number"}
    assert write_json_schema["$defs"]["FieldMetadataValue"] == json_value_schema
    assert output_json_schema["properties"]["payload"] == {"$ref": "#/$defs/FieldMetadataValue"}
    assert output_json_schema["properties"]["optional_payload"] == {
        "anyOf": [{"$ref": "#/$defs/FieldMetadataValue"}, {"type": "null"}],
        "default": None,
    }
    assert write_json_schema["properties"]["payload"] == {"$ref": "#/$defs/FieldMetadataValue"}
    assert write_json_schema["properties"]["optional_payload"] == {
        "anyOf": [{"$ref": "#/$defs/FieldMetadataValue"}, {"type": "null"}],
        "default": None,
    }

    output_schema.model_validate({"id": 1, "payload": {"nested": [1, "two"]}, "optional_payload": None})
    output_schema.model_validate({"id": 1, "payload": ["nested", 1], "optional_payload": True})
    write_schema.model_validate({"payload": {"nested": [1, "two"]}, "optional_payload": "value"})
    with pytest.raises(PydanticValidationError):
        output_schema.model_validate({"id": 1, "payload": object(), "optional_payload": None})
    with pytest.raises(PydanticValidationError):
        output_schema.model_validate({"id": 1, "payload": {"score": math.nan}, "optional_payload": None})
    with pytest.raises(PydanticValidationError):
        write_schema.model_validate({"payload": object(), "optional_payload": None})
    with pytest.raises(PydanticValidationError):
        write_schema.model_validate({"payload": {"score": math.inf}, "optional_payload": None})
    assert model_admin.serialize_object(JsonRecord(id=1, payload={"nested": [1, "two"]}, optional_payload=None)) == {
        "id": 1,
        "payload": {"nested": [1, "two"]},
        "optional_payload": None,
    }


@isolate_apps("tests.testapp")
def test_many_to_many_output_examples_use_related_target_field_values(db):
    class Label(models.Model):
        code = models.CharField(max_length=12, primary_key=True)

        class Meta:
            app_label = "testapp"

    class UuidLabel(models.Model):
        id = models.UUIDField(primary_key=True)

        class Meta:
            app_label = "testapp"

    class Article(models.Model):
        title = models.CharField(max_length=20)
        labels = models.ManyToManyField(Label, blank=True)
        uuid_labels = models.ManyToManyField(UuidLabel, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(Article)
    model_admin = admin_site.get_model_admin(Article)

    output_schema = model_admin.get_output_schema()
    output_json_schema = output_schema.model_json_schema()
    output_example = output_json_schema["examples"][0]

    assert output_json_schema["properties"]["labels"]["items"] == {
        "maxLength": 12,
        "type": "string",
    }
    assert output_json_schema["properties"]["uuid_labels"]["items"] == {
        "format": "uuid",
        "type": "string",
    }
    assert output_example["labels"] == ["example"]
    assert output_example["uuid_labels"] == ["00000000-0000-4000-8000-000000000000"]
    output_schema.model_validate(output_example)


@isolate_apps("tests.testapp")
def test_binary_model_fields_serialize_as_base64_output_strings(db):
    class BinaryAttachment(models.Model):
        payload = models.BinaryField()
        optional_payload = models.BinaryField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(BinaryAttachment)
    model_admin = admin_site.get_model_admin(BinaryAttachment)

    output_schema = model_admin.get_output_schema().model_json_schema()

    assert output_schema["properties"]["payload"] == {
        "contentEncoding": "base64",
        "contentMediaType": "application/octet-stream",
        "title": "Payload",
        "type": "string",
    }
    assert output_schema["properties"]["optional_payload"] == {
        "anyOf": [
            {
                "contentEncoding": "base64",
                "contentMediaType": "application/octet-stream",
                "type": "string",
            },
            {"type": "null"},
        ],
        "default": None,
        "title": "Optional Payload",
    }
    assert model_admin.serialize_object(BinaryAttachment(id=1, payload=b"\xff\x00", optional_payload=None)) == {
        "id": 1,
        "payload": "/wA=",
        "optional_payload": None,
    }


@isolate_apps("tests.testapp")
def test_regex_validated_model_fields_have_pattern_output_schemas(db):
    class InventoryCode(models.Model):
        slug = models.SlugField(max_length=12)
        sku = models.CharField(max_length=16, validators=[RegexValidator(r"^SKU-[0-9]+$")])
        optional_slug = models.SlugField(max_length=12, null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(InventoryCode)
    model_admin = admin_site.get_model_admin(InventoryCode)

    output_schema = model_admin.get_output_schema().model_json_schema()

    assert output_schema["properties"]["slug"] == {
        "maxLength": 12,
        "pattern": r"^[-a-zA-Z0-9_]+\z",
        "title": "Slug",
        "type": "string",
    }
    assert output_schema["properties"]["sku"] == {
        "maxLength": 16,
        "pattern": r"^SKU-[0-9]+$",
        "title": "Sku",
        "type": "string",
    }
    assert output_schema["properties"]["optional_slug"] == {
        "anyOf": [{"maxLength": 12, "pattern": r"^[-a-zA-Z0-9_]+\z", "type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Optional Slug",
    }
    assert model_admin.serialize_object(InventoryCode(id=1, slug="stock-1", sku="SKU-100", optional_slug=None)) == {
        "id": 1,
        "slug": "stock-1",
        "sku": "SKU-100",
        "optional_slug": None,
    }


@isolate_apps("tests.testapp")
def test_string_length_model_validators_drive_output_and_relation_schemas(db):
    class LengthCode(models.Model):
        code = models.CharField(
            max_length=20,
            primary_key=True,
            validators=[MinLengthValidator(4), MaxLengthValidator(12)],
        )
        optional_code = models.CharField(
            max_length=20,
            validators=[MinLengthValidator(3)],
            null=True,
            blank=True,
        )

        class Meta:
            app_label = "testapp"

    class LengthCodeLink(models.Model):
        code = models.ForeignKey(LengthCode, to_field="code", on_delete=models.CASCADE)
        codes = models.ManyToManyField(LengthCode, related_name="code_links", blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(LengthCode)
    admin_site.register(LengthCodeLink)
    code_admin = admin_site.get_model_admin(LengthCode)
    link_admin = admin_site.get_model_admin(LengthCodeLink)

    code_output_schema = code_admin.get_output_schema().model_json_schema()
    link_output_schema = link_admin.get_output_schema().model_json_schema()
    link_write_schema = link_admin.get_write_schema(None).model_json_schema()

    assert code_output_schema["properties"]["code"] == {
        "maxLength": 12,
        "minLength": 4,
        "title": "Code",
        "type": "string",
    }
    assert code_output_schema["properties"]["optional_code"] == {
        "anyOf": [{"maxLength": 20, "minLength": 3, "type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Optional Code",
    }
    assert link_write_schema["properties"]["code"] == {
        "maxLength": 12,
        "minLength": 4,
        "title": "Code",
        "type": "string",
    }
    assert link_output_schema["properties"]["code_id"] == {
        "maxLength": 12,
        "minLength": 4,
        "title": "Code Id",
        "type": "string",
    }
    assert link_output_schema["properties"]["codes"]["items"] == {
        "maxLength": 12,
        "minLength": 4,
        "type": "string",
    }
    assert code_admin.serialize_object(LengthCode(code="ABCD", optional_code=None)) == {
        "code": "ABCD",
        "optional_code": None,
    }


@isolate_apps("tests.testapp")
def test_numeric_model_validators_use_strictest_output_and_relation_bounds(db):
    class BoundedCode(models.Model):
        code = models.IntegerField(
            primary_key=True,
            validators=[
                MinValueValidator(5),
                MinValueValidator(2),
                MaxValueValidator(8),
                MaxValueValidator(12),
            ],
        )
        ratio = models.FloatField(
            validators=[
                MinValueValidator(0.75),
                MinValueValidator(0.25),
                MaxValueValidator(2.5),
                MaxValueValidator(3.0),
            ],
        )
        price = models.DecimalField(
            max_digits=6,
            decimal_places=2,
            validators=[
                MinValueValidator(Decimal("2.50")),
                MinValueValidator(Decimal("1.00")),
                MaxValueValidator(Decimal("8.75")),
                MaxValueValidator(Decimal("9.99")),
            ],
        )
        nullable_count = models.IntegerField(
            null=True,
            blank=True,
            validators=[
                MinValueValidator(4),
                MinValueValidator(1),
                MaxValueValidator(7),
                MaxValueValidator(9),
            ],
        )

        class Meta:
            app_label = "testapp"

    class BoundedCodeLink(models.Model):
        code = models.ForeignKey(BoundedCode, to_field="code", on_delete=models.CASCADE)
        codes = models.ManyToManyField(BoundedCode, related_name="bounded_links", blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(BoundedCode)
    admin_site.register(BoundedCodeLink)
    code_admin = admin_site.get_model_admin(BoundedCode)
    link_admin = admin_site.get_model_admin(BoundedCodeLink)

    code_schema = code_admin.get_output_schema()
    code_output_schema = code_schema.model_json_schema()
    link_output_schema = link_admin.get_output_schema().model_json_schema()
    link_write_schema = link_admin.get_write_schema(None).model_json_schema()

    assert code_output_schema["properties"]["code"] == {
        "maximum": 8,
        "minimum": 5,
        "title": "Code",
        "type": "integer",
    }
    assert link_write_schema["properties"]["code"] == {
        "maximum": 8,
        "minimum": 5,
        "title": "Code",
        "type": "integer",
    }
    assert link_output_schema["properties"]["code_id"] == {
        "maximum": 8,
        "minimum": 5,
        "title": "Code Id",
        "type": "integer",
    }
    assert link_output_schema["properties"]["codes"]["items"] == {
        "maximum": 8,
        "minimum": 5,
        "type": "integer",
    }
    assert code_output_schema["properties"]["ratio"] == {
        "maximum": 2.5,
        "minimum": 0.75,
        "title": "Ratio",
        "type": "number",
    }
    price_number_schema = next(
        option for option in code_output_schema["properties"]["price"]["anyOf"] if option.get("type") == "number"
    )
    assert price_number_schema["maximum"] == 8.75
    assert price_number_schema["minimum"] == 2.5
    nullable_count_integer = next(
        option
        for option in code_output_schema["properties"]["nullable_count"]["anyOf"]
        if option.get("type") == "integer"
    )
    assert nullable_count_integer["maximum"] == 7
    assert nullable_count_integer["minimum"] == 4

    code_schema.model_validate({"code": 5, "ratio": 0.75, "price": Decimal("2.50"), "nullable_count": None})
    with pytest.raises(PydanticValidationError):
        code_schema.model_validate({"code": 2, "ratio": 0.75, "price": Decimal("2.50"), "nullable_count": None})
    with pytest.raises(PydanticValidationError):
        code_schema.model_validate({"code": 5, "ratio": 3.0, "price": Decimal("2.50"), "nullable_count": None})
    with pytest.raises(PydanticValidationError):
        code_schema.model_validate({"code": 5, "ratio": 0.75, "price": Decimal("9.99"), "nullable_count": None})


@isolate_apps("tests.testapp")
def test_step_value_model_validators_drive_output_and_relation_schemas(db):
    class StepCode(models.Model):
        code = models.IntegerField(primary_key=True, validators=[StepValueValidator(5)])

        class Meta:
            app_label = "testapp"

    class StepCodeLink(models.Model):
        code = models.ForeignKey(StepCode, to_field="code", on_delete=models.CASCADE)
        codes = models.ManyToManyField(StepCode, related_name="step_links", blank=True)
        quantity = models.IntegerField(validators=[StepValueValidator(5)])
        nullable_quantity = models.IntegerField(null=True, blank=True, validators=[StepValueValidator(2)])
        ratio = models.FloatField(validators=[StepValueValidator(0.25)])
        price = models.DecimalField(max_digits=8, decimal_places=2, validators=[StepValueValidator(Decimal("0.05"))])
        offset_quantity = models.IntegerField(validators=[StepValueValidator(5, offset=1)])

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(StepCode)
    admin_site.register(StepCodeLink)
    code_admin = admin_site.get_model_admin(StepCode)
    link_admin = admin_site.get_model_admin(StepCodeLink)

    code_output_schema = code_admin.get_output_schema().model_json_schema()
    link_output_schema = link_admin.get_output_schema().model_json_schema()
    link_write_schema = link_admin.get_write_schema(None).model_json_schema()

    assert code_output_schema["properties"]["code"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "multipleOf": 5,
        "title": "Code",
        "type": "integer",
    }
    assert link_write_schema["properties"]["code"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "multipleOf": 5,
        "title": "Code",
        "type": "integer",
    }
    assert link_output_schema["properties"]["code_id"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "multipleOf": 5,
        "title": "Code Id",
        "type": "integer",
    }
    assert link_output_schema["properties"]["codes"]["items"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "multipleOf": 5,
        "type": "integer",
    }
    quantity_schema = link_output_schema["properties"]["quantity"]
    assert quantity_schema["type"] == "integer"
    assert quantity_schema["multipleOf"] == 5
    nullable_quantity_options = link_output_schema["properties"]["nullable_quantity"]["anyOf"]
    nullable_quantity_integer = next(option for option in nullable_quantity_options if option.get("type") == "integer")
    assert nullable_quantity_integer["multipleOf"] == 2
    assert {"type": "null"} in nullable_quantity_options
    assert link_output_schema["properties"]["ratio"] == {
        "multipleOf": 0.25,
        "title": "Ratio",
        "type": "number",
    }
    price_number_schema = next(
        option for option in link_output_schema["properties"]["price"]["anyOf"] if option.get("type") == "number"
    )
    assert price_number_schema["multipleOf"] == 0.05
    assert "multipleOf" not in link_output_schema["properties"]["offset_quantity"]
    assert code_admin.serialize_object(StepCode(code=10)) == {"code": 10}
