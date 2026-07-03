import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Annotated
from uuid import UUID

import pytest
from django import forms
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
    StepValueValidator,
)
from django.db import connection, models
from django.forms.models import BaseInlineFormSet
from django.http import QueryDict
from django.test import Client, RequestFactory, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import CaptureQueriesContext, isolate_apps
from django.utils import timezone
from ninja import Status
from ninja.security import SessionAuthIsStaff
from PIL import Image
from pydantic import AnyUrl, IPvAnyAddress
from pydantic import Field as PydanticField
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import (
    VERTICAL,
    AllValuesFieldListFilter,
    EmptyFieldListFilter,
    ModelAdmin,
    NinjaAdminSite,
    RelatedOnlyFieldListFilter,
    ShowFacets,
    SimpleListFilter,
    TabularInline,
    action,
    display,
    register,
    site,
)
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.exceptions import AlreadyRegistered, NotRegistered
from django_ninja_admin.filters import build_filter_spec
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import (
    Category,
    CategoryLimitedLink,
    CategorySlugLink,
    Product,
    ProductImage,
    ProductReview,
    Tag,
)


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_user("admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(db):
    user_count = 0

    def make_client(*permission_codenames):
        nonlocal user_count
        user_count += 1
        user = get_user_model().objects.create_user(f"staff-{user_count}", password="pw", is_staff=True)
        user.user_permissions.set(Permission.objects.filter(codename__in=permission_codenames))
        client = Client()
        client.force_login(user)
        return client

    return make_client


@pytest.fixture
def sample(db):
    category = Category.objects.create(name="Cameras")
    featured = Tag.objects.create(name="Featured")
    compact = Tag.objects.create(name="Compact")
    product = Product.objects.create(
        name="Alpha",
        category=category,
        price="12.50",
        description="Nice camera",
        manual="manuals/alpha.pdf",
    )
    product.tags.set([featured, compact])
    Product.objects.create(name="Beta", category=category, price="3.00", stock_status="out_of_stock")
    ProductImage.objects.create(product=product, title="Front")
    return product


def test_apps_context_docs_and_schema(admin_client, sample):
    assert admin_client.get("/admin-api/apps").status_code == 200
    assert admin_client.get("/admin-api/apps/testapp").json()["app_label"] == "testapp"
    assert admin_client.get("/admin-api/context").json()["has_permission"] is True
    assert admin_client.get("/admin-api/docs").status_code == 200
    schema = admin_client.get("/admin-api/openapi.json")
    assert schema.status_code == 200
    schema_body = schema.json()
    assert "/admin-api/testapp/product" in schema_body["paths"]
    components = schema_body["components"]["schemas"]
    assert schema_body["paths"]["/admin-api/testapp/product"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ProductAdminCreatePayload"}
    create_examples = schema_body["paths"]["/admin-api/testapp/product"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert create_examples["create"]["value"]["data"] == {
        "name": "example",
        "category": 1,
        "price": "9.99",
        "stock_status": "in_stock",
    }
    assert create_examples["create"]["value"]["inlines"] == {"testapp.productimage": {"add": [{"title": "example"}]}}
    multipart_schema = schema_body["paths"]["/admin-api/testapp/product/multipart"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]
    assert multipart_schema["properties"]["data"]["contentMediaType"] == "application/json"
    assert multipart_schema["properties"]["inlines"]["contentMediaType"] == "application/json"
    assert multipart_schema["properties"]["manual"] == {"type": "string", "format": "binary"}
    assert multipart_schema["properties"]["photo"] == {"type": "string", "format": "binary"}
    assert multipart_schema["required"] == ["data"]
    assert {
        "ProductAdminCreateData",
        "ProductAdminCreatePayload",
        "ProductAdminMutationData",
        "ProductAdminMutationResponse",
        "ProductAdminPartialUpdateData",
        "ProductAdminPartialUpdatePayload",
        "ProductAdminBulkPayload",
        "ProductAdminBulkRow",
        "ProductAdminBulkResponse",
        "CellMetadata",
        "ListEditingRow",
        "InlineDescription",
        "InlineFormsetRowMetadata",
        "ProductAdminInlinePayload",
        "ProductImageInlineOperations",
        "ProductImageInlineAddRow",
        "ProductImageInlineChangeRow",
        "ProductAdminActionPayload",
        "FileFieldValue",
        "ImageFieldValue",
    } <= set(components)
    assert components["ProductAdminOut"]["properties"]["id"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "title": "Id",
        "type": "integer",
    }
    assert "id" in components["ProductAdminOut"]["required"]
    price_string_schema = components["ProductAdminOut"]["properties"]["price"]
    assert price_string_schema["type"] == "string"
    assert r"\d{0,6}" in price_string_schema["pattern"]
    assert r"\d{0,2}" in price_string_schema["pattern"]
    assert "price" in components["ProductAdminOut"]["required"]
    assert components["ProductAdminOut"]["properties"]["manual"] == {
        "anyOf": [{"$ref": "#/components/schemas/FileFieldValue"}, {"type": "null"}]
    }
    assert components["ProductAdminOut"]["properties"]["photo"] == {
        "anyOf": [{"$ref": "#/components/schemas/ImageFieldValue"}, {"type": "null"}]
    }
    photo_width_options = components["ProductAdminOut"]["properties"]["photo_width"]["anyOf"]
    photo_width_integer_schema = next(option for option in photo_width_options if option.get("type") == "integer")
    assert photo_width_integer_schema["minimum"] == 0
    assert photo_width_integer_schema["maximum"] == 9223372036854775807
    assert {"type": "null"} in photo_width_options
    assert components["ProductAdminOut"]["properties"]["stock_status"] == {
        "default": "in_stock",
        "enum": ["in_stock", "out_of_stock"],
        "title": "Stock Status",
        "type": "string",
    }
    assert components["ProductAdminOut"]["properties"]["condition"] == {
        "anyOf": [{"enum": ["new", "used"], "type": "string"}, {"type": "null"}],
        "title": "Condition",
    }
    assert components["ProductAdminOut"]["properties"]["description"] == {
        "title": "Description",
        "type": "string",
    }
    assert "description" in components["ProductAdminOut"]["required"]
    assert components["ProductAdminOut"]["properties"]["tags"] == {
        "default": [],
        "items": {
            "maximum": 9223372036854775807,
            "minimum": -9223372036854775808,
            "type": "integer",
        },
        "title": "Tags",
        "type": "array",
    }
    output_example = components["ProductAdminOut"]["examples"][0]
    assert output_example["id"] == 1
    assert output_example["name"] == "example"
    assert output_example["category_id"] == 1
    assert output_example["manual"] == {"name": "manual/example.dat", "url": "/media/manual/example.dat"}
    assert output_example["photo"]["width"] == 640
    assert output_example["tags"] == [1]
    assert components["ProductAdminCreateData"]["examples"][0] == {
        "name": "example",
        "category": 1,
        "price": "9.99",
        "stock_status": "in_stock",
    }
    assert components["ProductAdminCreatePayload"]["examples"][0] == {
        "data": {
            "name": "example",
            "category": 1,
            "price": "9.99",
            "stock_status": "in_stock",
        },
        "inlines": {"testapp.productimage": {"add": [{"title": "example"}]}},
    }
    partial_payload_example = components["ProductAdminPartialUpdatePayload"]["examples"][0]
    assert partial_payload_example["data"] == {"name": "example"}
    assert partial_payload_example["inlines"]["testapp.productimage"]["change"] == [{"pk": 1, "title": "example"}]
    assert partial_payload_example["inlines"]["testapp.productimage"]["delete"] == [2]
    mutation_response_schema = components["ProductAdminMutationResponse"]
    assert mutation_response_schema["required"] == ["data"]
    assert mutation_response_schema["properties"]["data"] == {"$ref": "#/components/schemas/ProductAdminMutationData"}
    assert (
        components["ProductAdminMutationData"]["properties"]["name"]
        == components["ProductAdminOut"]["properties"]["name"]
    )
    assert components["ProductAdminMutationData"].get("additionalProperties") is True
    mutation_response_example = components["ProductAdminMutationResponse"]["examples"][0]
    assert mutation_response_example["data"]["name"] == "example"
    assert mutation_response_example["data"]["photo"]["height"] == 480
    assert mutation_response_example["inlines"] is None
    assert schema_body["paths"]["/admin-api/testapp/product"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminMutationResponse"}
    assert "202" not in schema_body["paths"]["/admin-api/testapp/product"]["post"]["responses"]
    assert schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["patch"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminMutationResponse"}
    assert "202" not in schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["patch"]["responses"]
    assert "202" not in schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["delete"]["responses"]
    assert set(components["ProductAdminCreateData"]["required"]) == {"name", "category", "price", "stock_status"}
    assert "required" not in components["ProductAdminPartialUpdateData"]
    assert components["ProductAdminCreateData"]["properties"]["category"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "title": "Category",
        "type": "integer",
    }
    assert components["ProductAdminCreateData"]["properties"]["stock_status"]["type"] == "string"
    assert components["ProductAdminPartialUpdateData"]["properties"]["manual"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "title": "Manual",
    }
    assert components["ProductAdminPartialUpdateData"]["properties"]["photo"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "title": "Photo",
    }
    tags_options = components["ProductAdminCreateData"]["properties"]["tags"]["anyOf"]
    tags_schema = next(option for option in tags_options if option.get("type") == "array")
    assert tags_schema["items"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "type": "integer",
    }
    price_options = components["ProductAdminCreateData"]["properties"]["price"]["anyOf"]
    assert any(option.get("type") == "number" for option in price_options)
    assert components["ProductAdminBulkRow"]["required"] == ["pk"]
    assert components["ProductAdminBulkRow"]["additionalProperties"] is False
    assert components["ProductAdminBulkRow"]["examples"][0] == {"pk": 1, "stock_status": "in_stock"}
    assert components["ProductAdminBulkPayload"]["examples"][0] == {"data": [{"pk": 1, "stock_status": "in_stock"}]}
    bulk_response_schema = components["ProductAdminBulkResponse"]
    assert bulk_response_schema["required"] == ["data"]
    assert bulk_response_schema["properties"]["data"]["additionalProperties"] == {
        "$ref": "#/components/schemas/ProductAdminOut"
    }
    assert components["ProductAdminBulkResponse"]["examples"][0]["data"]["1"]["name"] == "example"
    assert schema_body["paths"]["/admin-api/testapp/product/bulk"]["put"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminBulkResponse"}
    assert "testapp.productimage" in components["ProductAdminInlinePayload"]["properties"]
    assert components["ProductAdminInlinePayload"]["additionalProperties"] is False
    assert components["ProductImageInlineOperations"]["additionalProperties"] is False
    assert components["ProductImageInlineAddRow"]["required"] == ["title"]
    assert components["ProductImageInlineAddRow"]["additionalProperties"] is False
    assert components["ProductImageInlineAddRow"]["examples"][0] == {"title": "example"}
    assert components["ProductImageInlineChangeRow"]["required"] == ["pk"]
    assert components["ProductImageInlineChangeRow"]["additionalProperties"] is False
    assert components["ProductImageInlineChangeRow"]["examples"][0] == {"pk": 1, "title": "example"}
    assert components["ProductImageInlineOperations"]["examples"][0] == {
        "add": [{"title": "example"}],
        "change": [{"pk": 1, "title": "example"}],
        "delete": [2],
    }
    assert components["ProductAdminInlinePayload"]["examples"][0] == {
        "testapp.productimage": {
            "add": [{"title": "example"}],
            "change": [{"pk": 1, "title": "example"}],
            "delete": [2],
        }
    }
    action_payload_schema = components["ProductAdminActionPayload"]
    assert action_payload_schema["discriminator"] == {
        "propertyName": "action",
        "mapping": {
            "delete_selected": "#/components/schemas/ProductAdminDeleteSelectedActionPayload",
            "mark_out_of_stock": "#/components/schemas/ProductAdminMarkOutOfStockActionPayload",
            "report_names": "#/components/schemas/ProductAdminReportNamesActionPayload",
            "set_stock_status": "#/components/schemas/ProductAdminSetStockStatusActionPayload",
        },
    }
    assert {schema["$ref"] for schema in action_payload_schema["oneOf"]} == set(
        action_payload_schema["discriminator"]["mapping"].values()
    )
    set_status_payload = components["ProductAdminSetStockStatusActionPayload"]
    assert set_status_payload["properties"]["action"]["const"] == "set_stock_status"
    assert set_status_payload["properties"]["data"] == {"$ref": "#/components/schemas/StockStatusActionData"}
    assert set(set_status_payload["required"]) == {"action", "data"}
    action_responses = schema_body["paths"]["/admin-api/testapp/product/actions"]["post"]["responses"]
    action_response_schema = action_responses["200"]["content"]["application/json"]["schema"]
    assert {"$ref": "#/components/schemas/ActionResponse"} in action_response_schema["anyOf"]
    assert {"$ref": "#/components/schemas/ReportNamesActionResult"} in action_response_schema["anyOf"]
    assert {"$ref": "#/components/schemas/StockStatusActionResult"} in action_response_schema["anyOf"]
    assert action_responses["202"]["content"]["application/json"]["schema"] == action_response_schema
    assert "content" not in action_responses["204"]
    action_example = schema_body["paths"]["/admin-api/testapp/product/actions"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]["action"]["value"]
    assert action_example == {
        "action": "set_stock_status",
        "selected_ids": [1],
        "select_across": False,
        "data": {"status": "in_stock"},
    }
    bulk_example = schema_body["paths"]["/admin-api/testapp/product/bulk"]["put"]["requestBody"]["content"][
        "application/json"
    ]["examples"]["bulk_update"]["value"]
    assert bulk_example == {"data": [{"pk": 1, "stock_status": "in_stock"}]}
    patch_example = schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["patch"]["requestBody"]["content"][
        "application/json"
    ]["examples"]["partial_update"]["value"]
    assert patch_example["data"] == {"name": "example"}
    assert patch_example["inlines"] == {
        "testapp.productimage": {"change": [{"pk": 1, "title": "example"}], "delete": [2]}
    }


def test_site_routes_return_typed_auth_errors(db):
    response = Client().get("/admin-api/apps")

    assert response.status_code in {401, 403}
    body = response.json()
    assert set(body) == {"errors"}
    assert body["errors"][0]["param"] == "non_field_errors"


def test_docs_and_openapi_require_site_auth(db):
    client = Client()

    for path in ("/admin-api/docs", "/admin-api/openapi.json"):
        response = client.get(path)

        assert response.status_code == 401
        body = response.json()
        ErrorResponse.model_validate(body)
        assert body["errors"] == [{"message": "Authentication required.", "param": "non_field_errors"}]


@override_settings(
    MIDDLEWARE=[
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
    ]
)
def test_session_bootstrap_login_csrf_mutation_and_logout(db, sample):
    user = get_user_model().objects.create_user("bootstrap-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client = Client(enforce_csrf_checks=True)

    csrf_response = client.get("/admin-api/csrf")
    assert csrf_response.status_code == 200
    csrf_token = csrf_response.json()["csrf_token"]
    assert csrf_token
    assert client.get("/admin-api/apps").status_code == 401

    bad_login = client.post(
        "/admin-api/login",
        data={"username": "bootstrap-admin", "password": "wrong"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert bad_login.status_code == 400
    ErrorResponse.model_validate(bad_login.json())
    assert bad_login.json()["errors"] == [{"message": "Invalid username or password.", "param": "username"}]

    login_response = client.post(
        "/admin-api/login",
        data={"username": "bootstrap-admin", "password": "pw"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200
    login_body = login_response.json()
    assert login_body["is_authenticated"] is True
    assert login_body["is_staff"] is True
    assert login_body["has_permission"] is True
    assert login_body["csrf_token"]

    mutation = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"description": "Bootstrapped session"}},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_body["csrf_token"],
    )
    assert mutation.status_code == 200
    sample.refresh_from_db()
    assert sample.description == "Bootstrapped session"

    logout_response = client.post(
        "/admin-api/logout",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=login_body["csrf_token"],
    )
    assert logout_response.status_code == 200
    assert logout_response.json()["is_authenticated"] is False
    assert client.get("/admin-api/apps").status_code == 401


def test_error_response_openapi_schema_is_semantic_and_stable(admin_client, sample):
    schema = admin_client.get("/admin-api/openapi.json").json()
    components = schema["components"]["schemas"]

    assert components["ErrorItem"] == {
        "properties": {
            "message": {"$ref": "#/components/schemas/ErrorMessage"},
            "param": {
                "default": "non_field_errors",
                "title": "Param",
                "type": "string",
            },
        },
        "required": ["message"],
        "title": "ErrorItem",
        "type": "object",
    }
    assert components["ErrorMessage"] == {
        "anyOf": [
            {"type": "string"},
            {"items": {"type": "string"}, "type": "array"},
        ]
    }
    assert components["DeletedObject"] == {
        "anyOf": [
            {"type": "string"},
            {"items": {"$ref": "#/components/schemas/DeletedObject"}, "type": "array"},
        ]
    }
    assert components["ErrorResponse"]["required"] == ["errors"]
    assert components["ErrorResponse"]["properties"] == {
        "errors": {
            "items": {"$ref": "#/components/schemas/ErrorItem"},
            "title": "Errors",
            "type": "array",
        },
        "deleted_objects": {
            "anyOf": [
                {"items": {"$ref": "#/components/schemas/DeletedObject"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Deleted Objects",
        },
        "protected": {
            "anyOf": [
                {"items": {"type": "string"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Protected",
        },
        "perms_needed": {
            "anyOf": [
                {"items": {"type": "string"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Perms Needed",
        },
        "model_count": {
            "anyOf": [
                {"additionalProperties": {"type": "integer"}, "type": "object"},
                {"type": "null"},
            ],
            "title": "Model Count",
        },
    }

    for path, method, status in [
        ("/admin-api/apps", "get", "401"),
        ("/admin-api/testapp/product", "post", "422"),
        ("/admin-api/testapp/product", "get", "403"),
        ("/admin-api/testapp/product/{object_id}", "get", "404"),
        ("/admin-api/testapp/product/{object_id}", "delete", "409"),
    ]:
        assert _response_schema_ref(schema["paths"][path][method], status) == "#/components/schemas/ErrorResponse"
    ErrorResponse.model_validate(
        {
            "errors": [{"message": ["This field is required."], "param": "name"}],
            "deleted_objects": ["Alpha", ["Front", ["Nested child"]]],
        }
    )
    with pytest.raises(PydanticValidationError):
        ErrorResponse.model_validate({"errors": [{"message": {"detail": "Nope"}, "param": "name"}]})


def test_error_response_runtime_shapes_are_consistent(admin_client, staff_client, sample):
    def assert_error_body(response, status):
        assert response.status_code == status
        body = response.json()
        ErrorResponse.model_validate(body)
        assert isinstance(body["errors"], list)
        assert body["errors"]
        assert {"message", "param"} <= set(body["errors"][0])
        return body

    auth_body = assert_error_body(Client().get("/admin-api/apps"), 401)
    assert auth_body["errors"][0]["param"] == "non_field_errors"

    denied_body = assert_error_body(staff_client().get("/admin-api/testapp/product"), 403)
    assert denied_body["errors"][0] == {"message": "Permission denied.", "param": "non_field_errors"}

    missing_body = assert_error_body(admin_client.get("/admin-api/testapp/product/999999"), 404)
    assert missing_body["errors"][0] == {"message": "Not found.", "param": "non_field_errors"}

    invalid_body = assert_error_body(
        admin_client.post(
            "/admin-api/testapp/product/actions",
            data={"action": "not_a_real_action", "selected_ids": [sample.pk]},
            content_type="application/json",
        ),
        422,
    )
    assert invalid_body["errors"][0]["param"] == "action"

    form_body = assert_error_body(
        admin_client.post(
            "/admin-api/testapp/product",
            data={
                "data": {
                    "name": "Bad category",
                    "category": 999999,
                    "price": "9.00",
                    "stock_status": "in_stock",
                }
            },
            content_type="application/json",
        ),
        400,
    )
    assert form_body["errors"][0]["param"] == "category"

    inline_body = assert_error_body(
        admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}",
            data={
                "data": {},
                "inlines": {"testapp.productimage": {"change": [{"pk": 999999, "title": "Ghost"}]}},
            },
            content_type="application/json",
        ),
        400,
    )
    assert inline_body["errors"][0] == {
        "message": "Unknown inline object.",
        "param": "inlines.testapp.productimage.change.0.pk",
    }

    bulk_body = assert_error_body(
        admin_client.put(
            "/admin-api/testapp/product/bulk",
            data={"data": [{"pk": 999999, "stock_status": "in_stock"}]},
            content_type="application/json",
        ),
        400,
    )
    assert bulk_body["errors"][0] == {"message": "Object not found.", "param": "data.0.pk"}

    ProductReview.objects.create(product=sample, note="Pinned review")
    protected_body = assert_error_body(admin_client.delete(f"/admin-api/testapp/product/{sample.pk}"), 409)
    assert_sample_deleted_objects_tree(protected_body)
    assert protected_body["protected"] == ["Pinned review"]
    assert protected_body["model_count"] == {
        "testapp.product": 1,
        "testapp.product_tags": 2,
        "testapp.productimage": 1,
    }


def assert_sample_deleted_objects_tree(body):
    assert body["deleted_objects"][0] == "Alpha"
    assert "Front" in body["deleted_objects"][1]
    assert any(item.startswith("Product_tags object") for item in body["deleted_objects"][1])


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


def test_permissions_route_reports_site_permission(admin_client):
    staff_response = admin_client.get("/admin-api/permissions")

    assert staff_response.status_code == 200
    body = staff_response.json()
    permission_state_keys = ("is_authenticated", "is_active", "is_staff", "is_superuser", "has_permission")
    assert {key: body[key] for key in permission_state_keys} == {
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "has_permission": True,
    }
    assert isinstance(body["models"], list)
    model_keys = {(model["app_label"], model["model_name"]) for model in body["models"]}
    assert {("testapp", "category"), ("testapp", "product"), ("testapp", "tag")} <= model_keys
    product_permissions = next(model["perms"] for model in body["models"] if model["model_name"] == "product")
    assert product_permissions == {
        "has_add_permission": True,
        "has_change_permission": True,
        "has_delete_permission": True,
        "has_view_permission": True,
    }


def test_permissions_route_uses_custom_model_permission_hooks(admin_client, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "has_add_permission", lambda request: False)
    monkeypatch.setattr(product_admin, "has_delete_permission", lambda request, obj=None: False)

    response = admin_client.get("/admin-api/permissions")

    assert response.status_code == 200
    product = next(model for model in response.json()["models"] if model["model_name"] == "product")
    assert product["perms"] == {
        "has_add_permission": False,
        "has_change_permission": True,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_permissions_route_supports_auth_none_sites():
    public_response = Client().get("/public-permissions-admin/permissions")

    assert public_response.status_code == 200
    assert public_response.json() == {
        "is_authenticated": False,
        "is_active": False,
        "is_staff": False,
        "is_superuser": False,
        "has_permission": False,
        "models": [],
    }

    schema = Client().get("/public-permissions-admin/openapi.json").json()
    operation = schema["paths"]["/public-permissions-admin/permissions"]["get"]
    assert "security" not in operation
    assert "401" not in operation["responses"]
    assert "403" not in operation["responses"]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_include_auth_uses_safe_user_and_group_admins(db):
    client = Client()
    user = get_user_model().objects.create_user("auth-safe", password="hashed", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client.force_login(user)

    user_form = client.get("/auth-models-admin/auth/user/form")
    assert user_form.status_code == 200
    user_field_names = {field["name"] for field in user_form.json()["form"]["fields"]}
    assert {"password", "is_superuser", "user_permissions", "groups"}.isdisjoint(user_field_names)

    group_form = client.get("/auth-models-admin/auth/group/form")
    assert group_form.status_code == 200
    group_field_names = {field["name"] for field in group_form.json()["form"]["fields"]}
    assert "permissions" not in group_field_names

    response = client.patch(
        f"/auth-models-admin/auth/user/{user.pk}",
        data={
            "data": {
                "password": "plain",
                "is_superuser": True,
                "user_permissions": [Permission.objects.first().pk],
                "groups": [],
            }
        },
        content_type="application/json",
    )

    assert response.status_code == 422
    assert {
        "data.password",
        "data.is_superuser",
        "data.user_permissions",
        "data.groups",
    }.issubset({error["param"] for error in response.json()["errors"]})
    user.refresh_from_db()
    assert user.check_password("hashed")
    assert user.is_superuser is False


def test_openapi_model_route_contracts_are_semantic_and_stable(admin_client, sample):
    schema = admin_client.get("/admin-api/openapi.json").json()
    paths = schema["paths"]
    components = schema["components"]["schemas"]

    expected_site_operations = {
        ("/admin-api/apps", "get"): "admin_list_apps",
        ("/admin-api/apps/{app_label}", "get"): "admin_get_app",
        ("/admin-api/context", "get"): "admin_context",
        ("/admin-api/permissions", "get"): "admin_permissions",
        ("/admin-api/history", "get"): "admin_history",
        ("/admin-api/autocomplete", "get"): "admin_autocomplete",
        ("/admin-api/view-on-site/{content_type_id}/{object_id}", "get"): "admin_view_on_site",
    }
    for (path, method), operation_id in expected_site_operations.items():
        operation = paths[path][method]
        assert operation["operationId"] == operation_id
        assert operation["tags"] == ["admin"]
        assert operation["security"] == [{"SessionAuthIsStaff": []}]

    expected_operations = {
        ("/admin-api/testapp/product", "get"): ("testapp_product_list", ["testapp.product"]),
        ("/admin-api/testapp/product", "post"): ("testapp_product_create", ["testapp.product"]),
        ("/admin-api/testapp/product/form", "get"): ("testapp_product_add_form", ["testapp.product"]),
        ("/admin-api/testapp/product/actions", "post"): ("testapp_product_action", ["testapp.product"]),
        ("/admin-api/testapp/product/bulk", "put"): ("testapp_product_bulk_update", ["testapp.product"]),
        ("/admin-api/testapp/product/{object_id}", "get"): ("testapp_product_detail", ["testapp.product"]),
        ("/admin-api/testapp/product/{object_id}", "patch"): ("testapp_product_partial_update", ["testapp.product"]),
        ("/admin-api/testapp/product/{object_id}", "put"): ("testapp_product_update", ["testapp.product"]),
        ("/admin-api/testapp/product/{object_id}", "delete"): ("testapp_product_delete", ["testapp.product"]),
        ("/admin-api/testapp/product/{object_id}/form", "get"): ("testapp_product_change_form", ["testapp.product"]),
    }
    for (path, method), (operation_id, tags) in expected_operations.items():
        operation = paths[path][method]
        assert operation["operationId"] == operation_id
        assert operation["tags"] == tags
        assert operation["security"] == [{"SessionAuthIsStaff": []}]

    list_operation = paths["/admin-api/testapp/product"]["get"]
    assert "Django-style field lookup filters" in list_operation["description"]
    assert [parameter["name"] for parameter in list_operation["parameters"]] == [
        "q",
        "o",
        "p",
        "page",
        "pp",
        "all",
        "_facets",
        "_to_field",
    ]
    assert {parameter["name"]: parameter["in"] for parameter in list_operation["parameters"]} == {
        "q": "query",
        "o": "query",
        "p": "query",
        "page": "query",
        "pp": "query",
        "all": "query",
        "_facets": "query",
        "_to_field": "query",
    }

    assert _request_schema_ref(paths["/admin-api/testapp/product"]["post"]) == (
        "#/components/schemas/ProductAdminCreatePayload"
    )
    assert (
        _request_schema_ref(paths["/admin-api/testapp/product/{object_id}"]["patch"])
        == "#/components/schemas/ProductAdminPartialUpdatePayload"
    )
    assert (
        _request_schema_ref(paths["/admin-api/testapp/product/{object_id}"]["put"])
        == "#/components/schemas/ProductAdminUpdatePayload"
    )
    assert (
        _request_schema_ref(paths["/admin-api/testapp/product/actions"]["post"])
        == "#/components/schemas/ProductAdminActionPayload"
    )
    assert (
        _request_schema_ref(paths["/admin-api/testapp/product/bulk"]["put"])
        == "#/components/schemas/ProductAdminBulkPayload"
    )

    assert _response_schema_ref(paths["/admin-api/testapp/product"]["get"], "200") == (
        "#/components/schemas/ChangelistResponse"
    )
    assert _response_schema_ref(paths["/admin-api/testapp/product/form"]["get"], "200") == (
        "#/components/schemas/FormResponse"
    )
    assert _response_schema_ref(paths["/admin-api/testapp/product/{object_id}"]["get"], "200") == (
        "#/components/schemas/ProductAdminOut"
    )
    assert _response_schema_ref(paths["/admin-api/testapp/product/{object_id}/form"]["get"], "200") == (
        "#/components/schemas/FormResponse"
    )
    assert _response_schema_ref(paths["/admin-api/apps/{app_label}"]["get"], "200") == (
        "#/components/schemas/AppSummary"
    )
    apps_schema = paths["/admin-api/apps"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert apps_schema["type"] == "array"
    assert apps_schema["items"] == {"$ref": "#/components/schemas/AppSummary"}
    app_example = components["AppSummary"]["examples"][0]
    assert app_example["app_label"] == "shop"
    assert app_example["models"][0]["perms"]["has_view_permission"] is True
    assert _response_schema_ref(paths["/admin-api/context"]["get"], "200") == "#/components/schemas/SiteContext"
    context_example = components["SiteContext"]["examples"][0]
    assert context_example["available_apps"][0]["models"][0]["model_name"] == "product"
    assert _response_schema_ref(paths["/admin-api/permissions"]["get"], "200") == (
        "#/components/schemas/PermissionsResponse"
    )
    permissions_example = components["PermissionsResponse"]["examples"][0]
    assert permissions_example == {
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "has_permission": True,
        "models": [
            {
                "name": "Products",
                "object_name": "Product",
                "app_label": "shop",
                "model_name": "product",
                "perms": {
                    "has_add_permission": True,
                    "has_change_permission": True,
                    "has_delete_permission": False,
                    "has_view_permission": True,
                },
            }
        ],
    }
    assert components["PermissionsResponse"]["properties"]["models"]["items"] == {
        "$ref": "#/components/schemas/ModelSummary"
    }
    assert _response_schema_ref(paths["/admin-api/history"]["get"], "200") == "#/components/schemas/HistoryResponse"
    assert components["HistoryItem"]["properties"]["action_time"]["format"] == "date-time"
    assert components["HistoryItem"]["properties"]["change_message_text"]["type"] == "string"
    assert components["HistoryItem"]["properties"]["model"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert components["HistoryItem"]["properties"]["detail_url"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert components["HistoryResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    history_example = components["HistoryResponse"]["examples"][0]
    assert history_example["pagination"]["per_page"] == 20
    assert history_example["pagination"]["more"] is False
    assert history_example["results"][0]["change_form_url"] == "/admin-api/shop/product/1/form"
    assert history_example["results"][0]["change_message_text"] == "Changed Name."
    assert _response_schema_ref(paths["/admin-api/autocomplete"]["get"], "200") == (
        "#/components/schemas/AutocompleteResponse"
    )
    assert components["AutocompleteResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    autocomplete_example = components["AutocompleteResponse"]["examples"][0]
    assert autocomplete_example["results"] == [{"id": "1", "text": "Cameras"}]
    assert autocomplete_example["pagination"]["more"] is False
    assert components["ChangelistConfig"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    assert _response_schema_ref(paths["/admin-api/view-on-site/{content_type_id}/{object_id}"]["get"], "200") == (
        "#/components/schemas/ViewOnSiteResponse"
    )
    assert components["ViewOnSiteResponse"]["examples"][0] == {"url": "https://example.com/products/1/"}
    assert components["Row"]["properties"]["cell_metadata"]["additionalProperties"] == {
        "$ref": "#/components/schemas/CellMetadata"
    }
    cell_metadata_props = components["CellMetadata"]["properties"]
    assert cell_metadata_props["display_value"]["title"] == "Display Value"
    assert cell_metadata_props["empty"]["type"] == "boolean"
    assert cell_metadata_props["editable"]["type"] == "boolean"
    changelist_response_props = components["ChangelistResponse"]["properties"]
    assert changelist_response_props["list_editing_formset_prefix"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_management_form"]["items"] == {
        "$ref": "#/components/schemas/FieldDescription"
    }
    assert changelist_response_props["list_editing_total_form_count"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_initial_form_count"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_formset"]["items"]["items"] == {
        "$ref": "#/components/schemas/FieldDescription"
    }
    assert changelist_response_props["list_editing_rows"]["items"] == {"$ref": "#/components/schemas/ListEditingRow"}
    list_editing_row_props = components["ListEditingRow"]["properties"]
    assert list_editing_row_props["form_prefix"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert list_editing_row_props["empty_permitted"]["type"] == "boolean"

    form_response_props = components["FormResponse"]["properties"]
    assert form_response_props["inlines"]["items"] == {"$ref": "#/components/schemas/InlineDescription"}
    form_description_props = components["FormDescription"]["properties"]
    assert "fieldsets" not in form_description_props
    assert form_description_props["fieldset_layout"]["items"] == {"$ref": "#/components/schemas/FieldsetDescription"}
    fieldset_description_props = components["FieldsetDescription"]["properties"]
    assert fieldset_description_props["name"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert fieldset_description_props["classes"]["items"] == {"type": "string"}
    assert fieldset_description_props["rows"]["items"] == {"$ref": "#/components/schemas/FieldsetRow"}
    assert components["FieldsetRow"]["properties"]["fields"]["items"] == {"type": "string"}
    inline_response_props = components["InlineDescription"]["properties"]
    assert "fieldsets" not in inline_response_props
    assert inline_response_props["fieldset_layout"]["items"] == {"$ref": "#/components/schemas/FieldsetDescription"}
    assert inline_response_props["management_form"]["items"] == {"$ref": "#/components/schemas/FieldDescription"}
    assert inline_response_props["empty_form"]["items"] == {"$ref": "#/components/schemas/FieldDescription"}
    assert inline_response_props["formset_row_metadata"]["items"] == {
        "$ref": "#/components/schemas/InlineFormsetRowMetadata"
    }
    inline_row_metadata_props = components["InlineFormsetRowMetadata"]["properties"]
    assert inline_row_metadata_props["prefix"]["type"] == "string"
    assert inline_row_metadata_props["is_initial"]["type"] == "boolean"
    assert inline_row_metadata_props["empty_permitted"]["type"] == "boolean"
    assert inline_row_metadata_props["object_id"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    field_attrs_schema = components["FieldDescription"]["properties"]["attrs"]
    assert field_attrs_schema["$ref"] == "#/components/schemas/FieldAttributes"
    assert field_attrs_schema["description"] == "Semantic form/admin metadata for frontend renderers."
    field_attrs_example = field_attrs_schema["examples"][0]
    assert field_attrs_example["ordering_field"] == "name"
    assert field_attrs_example["admin_widget"] == "autocomplete"
    assert field_attrs_example["autocomplete"]["related_model"] == "shop.category"
    assert "html_name" not in field_attrs_example
    assert "rendered_attrs" not in field_attrs_example
    assert "rendered_subwidgets" not in field_attrs_example
    field_attrs_component = components["FieldAttributes"]
    assert field_attrs_component["additionalProperties"] is False
    field_attrs_props = field_attrs_component["properties"]
    assert RENDERED_FIELD_ATTR_KEYS.isdisjoint(field_attrs_props)
    assert field_attrs_props["required"]["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert field_attrs_props["ordering_field"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert field_attrs_props["max_length"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert {"$ref": "#/components/schemas/FileFieldValue"} in field_attrs_props["current_file"]["anyOf"]
    assert {"$ref": "#/components/schemas/ImageFieldValue"} in field_attrs_props["current_file"]["anyOf"]
    selected_options_schema = field_attrs_props["selected_options"]["anyOf"][0]
    assert selected_options_schema["items"] == {"$ref": "#/components/schemas/SelectedOption"}
    assert components["SelectedOption"]["required"] == ["id", "text"]
    error_examples = components["ErrorResponse"]["examples"]
    assert error_examples[0] == {"errors": [{"param": "name", "message": ["This field is required."]}]}
    assert error_examples[1]["errors"] == [{"param": "non_field_errors", "message": "Permission denied."}]
    assert error_examples[2]["deleted_objects"] == ["Nice camera"]
    assert error_examples[2]["protected"] == ["Protected review: Nice camera"]
    assert error_examples[2]["perms_needed"] == ["Can delete product review"]
    assert error_examples[2]["model_count"] == {"product reviews": 1}

    for path, method, statuses in [
        ("/admin-api/apps", "get", {"401", "403"}),
        ("/admin-api/apps/{app_label}", "get", {"401", "403", "404"}),
        ("/admin-api/context", "get", {"401", "403"}),
        ("/admin-api/permissions", "get", {"401", "403"}),
        ("/admin-api/history", "get", {"400", "401", "403", "404", "422"}),
        ("/admin-api/autocomplete", "get", {"401", "403", "404", "409", "422"}),
        ("/admin-api/view-on-site/{content_type_id}/{object_id}", "get", {"401", "403", "404", "409", "422"}),
    ]:
        operation = paths[path][method]
        assert statuses <= set(operation["responses"])
        for status in statuses:
            assert _response_schema_ref(operation, status) == "#/components/schemas/ErrorResponse"

    for path, method, statuses in [
        ("/admin-api/testapp/product", "get", {"400", "401", "403", "404"}),
        ("/admin-api/testapp/product", "post", {"400", "401", "403", "422"}),
        ("/admin-api/testapp/product/form", "get", {"401", "403"}),
        ("/admin-api/testapp/product/actions", "post", {"400", "401", "403", "409", "422"}),
        ("/admin-api/testapp/product/bulk", "put", {"400", "401", "403", "422"}),
        ("/admin-api/testapp/product/{object_id}", "get", {"400", "401", "403", "404"}),
        ("/admin-api/testapp/product/{object_id}", "patch", {"400", "401", "403", "404", "422"}),
        ("/admin-api/testapp/product/{object_id}", "put", {"400", "401", "403", "404", "422"}),
        ("/admin-api/testapp/product/{object_id}", "delete", {"400", "401", "403", "404", "409"}),
        ("/admin-api/testapp/product/{object_id}/form", "get", {"400", "401", "403", "404"}),
    ]:
        operation = paths[path][method]
        assert statuses <= set(operation["responses"])
        for status in statuses:
            assert _response_schema_ref(operation, status) == "#/components/schemas/ErrorResponse"
    delete_responses = paths["/admin-api/testapp/product/{object_id}"]["delete"]["responses"]
    assert "200" not in delete_responses
    assert "202" not in delete_responses
    assert "content" not in delete_responses["204"]


def _request_schema_ref(operation):
    return operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def _uploaded_png(name="photo.png", *, size=(2, 3), color=(255, 0, 0)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def test_admin_checks_accept_valid_test_admins(db):
    errors = site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert errors == []


def test_site_registration_contracts_and_decorator(db):
    admin_site = NinjaAdminSite(include_auth=False)

    admin_site.register(Category, list_display=("name",))
    assert admin_site.is_registered(Category) is True
    assert admin_site.get_model_admin(Category).list_display == ("name",)

    with pytest.raises(AlreadyRegistered):
        admin_site.register(Category)

    admin_site.unregister(Category)
    assert admin_site.is_registered(Category) is False

    with pytest.raises(NotRegistered):
        admin_site.unregister(Category)

    class AbstractThing(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            abstract = True
            app_label = "testapp"

    with pytest.raises(ImproperlyConfigured):
        admin_site.register(AbstractThing)

    @register(Tag, site=admin_site)
    class RegisteredTagAdmin(ModelAdmin):
        list_display = ("name",)

    assert isinstance(admin_site.get_model_admin(Tag), RegisteredTagAdmin)


@isolate_apps("tests.testapp")
@override_settings(TESTAPP_SWAPPED_MODEL="testapp.ReplacementThing")
def test_site_registration_skips_swapped_models(db):
    class SwappedThing(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"
            swappable = "TESTAPP_SWAPPED_MODEL"

    admin_site = NinjaAdminSite(include_auth=False)

    admin_site.register(SwappedThing)

    assert SwappedThing._meta.swapped == "testapp.ReplacementThing"
    assert admin_site.is_registered(SwappedThing) is False
    with pytest.raises(NotRegistered):
        admin_site.get_model_admin(SwappedThing)


def test_site_action_changes_invalidate_openapi_schema(db):
    admin_site = NinjaAdminSite(include_auth=False, name="action_cache")
    admin_site.register(Product, ModelAdmin)

    def action_mapping():
        schema = admin_site.api.get_openapi_schema(path_prefix="/action-cache")
        return schema["components"]["schemas"]["ProductAdminActionPayload"]["discriminator"]["mapping"]

    before_mapping = action_mapping()
    assert "cache_probe" not in before_mapping

    def cache_probe(model_admin, request, queryset):
        return {"count": queryset.count()}

    cache_probe.short_description = "Cache probe"

    admin_site.add_action(cache_probe)

    after_add_mapping = action_mapping()
    assert "cache_probe" in after_add_mapping
    assert after_add_mapping["cache_probe"] == "#/components/schemas/ProductAdminCacheProbeActionPayload"

    admin_site.disable_action("cache_probe")

    after_disable_mapping = action_mapping()
    assert "cache_probe" not in after_disable_mapping


def test_autodiscover_rolls_back_partial_admin_imports(monkeypatch):
    from django_ninja_admin.utils import module_loading

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Category)
    admin_site._api = object()

    class BrokenAppConfig:
        name = "broken_app"
        module = object()

    def broken_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    def import_broken_admin(module_name):
        assert module_name == "broken_app.admin"
        admin_site.register(Product)
        admin_site.add_action(broken_action)
        raise RuntimeError("broken admin module")

    monkeypatch.setattr(module_loading.apps, "get_app_configs", lambda: [BrokenAppConfig()])
    monkeypatch.setattr(module_loading, "import_module", import_broken_admin)
    monkeypatch.setattr(module_loading, "module_has_submodule", lambda module, module_name: True)

    with pytest.raises(RuntimeError, match="broken admin module"):
        module_loading.autodiscover_modules("admin", register_to=admin_site)

    assert admin_site.is_registered(Category) is True
    assert admin_site.is_registered(Product) is False
    assert "broken_action" not in dict(admin_site.actions)
    assert "broken_action" not in admin_site._global_actions
    assert admin_site._api is None


def test_admin_checks_report_invalid_model_admin_configuration(db):
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

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadProductAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])
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


def test_inline_admin_supports_custom_formset_classes(db):
    class CustomInlineFormSet(BaseInlineFormSet):
        pass

    class ValidInline(TabularInline):
        model = ProductImage
        formset = CustomInlineFormSet

    class BadInline(TabularInline):
        model = ProductImage
        formset = forms.Form

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    inline = valid_site.get_model_admin(Product).get_inline_instances(None, check_permissions=False)[0]
    formset_class = inline.get_formset(RequestFactory().get("/"))
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert issubclass(formset_class, CustomInlineFormSet)
    assert "django_ninja_admin.E076" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E076"}


def test_admin_checks_reject_inline_excluding_parent_foreign_key(db):
    class ValidInline(TabularInline):
        model = ProductImage
        exclude = ("title",)

    class BadInline(TabularInline):
        model = ProductImage
        exclude = ("product",)

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_errors = bad_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E077" not in valid_ids
    assert {error.id for error in bad_errors} == {"django_ninja_admin.E077"}
    assert "parent foreign key field 'product'" in bad_errors[0].msg


def test_admin_checks_reject_reverse_relation_in_list_display(db):
    class ReverseRelationProductAdmin(ModelAdmin):
        list_display = ("name", "reviews")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ReverseRelationProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E043"}
    assert "many-to-many or reverse field" in errors[0].msg


def test_admin_checks_allow_single_valued_relation_path_in_list_display(db):
    class RelationPathProductAdmin(ModelAdmin):
        list_display = ("name", "category__name")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelationPathProductAdmin)

    error_ids = {error.id for error in admin_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E003", "django_ninja_admin.E004", "django_ninja_admin.E043"})


def test_admin_checks_validate_action_permission_hooks(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidActionProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadActionProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E064" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E064"}


def test_admin_checks_reject_non_sequence_actions_option(db):
    class BadActionsShapeProductAdmin(ModelAdmin):
        actions = "delete_selected"

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadActionsShapeProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E082"}


def test_admin_checks_report_form_widget_option_conflicts(db):
    class ConflictProductAdmin(ModelAdmin):
        autocomplete_fields = ("category",)
        raw_id_fields = ("category",)
        filter_horizontal = ("tags",)
        filter_vertical = ("tags",)
        radio_fields = {"category": 999, "price": VERTICAL}

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ConflictProductAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])
    error_ids = {error.id for error in errors}

    assert {
        "django_ninja_admin.E037",
        "django_ninja_admin.E038",
        "django_ninja_admin.E039",
        "django_ninja_admin.E040",
        "django_ninja_admin.E041",
        "django_ninja_admin.E042",
    } <= error_ids


def test_admin_checks_validate_list_select_related(db):
    class ValidProductAdmin(ModelAdmin):
        list_select_related = ("category",)

    class BadTypeProductAdmin(ModelAdmin):
        list_select_related = "category"

    class BadPathProductAdmin(ModelAdmin):
        list_select_related = ("tags", "price", "missing")

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidProductAdmin)
    valid_errors = valid_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E045", "django_ninja_admin.E046"})

    bad_type_site = NinjaAdminSite(include_auth=False)
    bad_type_site.register(Product, BadTypeProductAdmin)
    bad_type_errors = bad_type_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_type_errors} == {"django_ninja_admin.E045"}

    bad_path_site = NinjaAdminSite(include_auth=False)
    bad_path_site.register(Product, BadPathProductAdmin)
    bad_path_errors = bad_path_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_path_errors} == {"django_ninja_admin.E046"}
    assert len(bad_path_errors) == 3


def test_admin_checks_validate_list_prefetch_related(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidProductAdmin)
    valid_errors = valid_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E118", "django_ninja_admin.E119"})

    bad_type_site = NinjaAdminSite(include_auth=False)
    bad_type_site.register(Product, BadTypeProductAdmin)
    bad_type_errors = bad_type_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_type_errors} == {"django_ninja_admin.E118"}
    assert len(bad_type_errors) == 1

    bad_path_site = NinjaAdminSite(include_auth=False)
    bad_path_site.register(Product, BadPathProductAdmin)
    bad_path_errors = bad_path_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_path_errors} == {"django_ninja_admin.E119"}
    assert len(bad_path_errors) == 3


def test_admin_checks_validate_sortable_by(db):
    class ValidSortableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        sortable_by = ("name",)

    class BadShapeProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = "name"

    class BadItemsProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = (123, "price")

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSortableProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_items_site = NinjaAdminSite(include_auth=False)
    bad_items_site.register(Product, BadItemsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_items_ids = {error.id for error in bad_items_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E055", "django_ninja_admin.E056", "django_ninja_admin.E057"})
    assert bad_shape_ids == {"django_ninja_admin.E055"}
    assert bad_items_ids == {"django_ninja_admin.E056", "django_ninja_admin.E057"}


def test_admin_checks_validate_pagination_options(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPaginationProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadPaginationProductAdmin)
    bad_boolean_site = NinjaAdminSite(include_auth=False)
    bad_boolean_site.register(Product, BadBooleanPaginationProductAdmin)
    bad_range_site = NinjaAdminSite(include_auth=False)
    bad_range_site.register(Product, BadRangePaginationProductAdmin)

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


def test_admin_checks_validate_paginator_class(db):
    class CustomPaginator(Paginator):
        pass

    class ValidPaginatorProductAdmin(ModelAdmin):
        paginator = CustomPaginator

    class BadPaginatorProductAdmin(ModelAdmin):
        paginator = object()

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPaginatorProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadPaginatorProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E090" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E090"}


def test_admin_checks_validate_boolean_options(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, CallableViewOnSiteProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadBooleanOptionsProductAdmin)

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


def test_admin_checks_reject_mixed_random_ordering(db):
    class RandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?",)

    class MixedRandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?", "name")

    random_site = NinjaAdminSite(include_auth=False)
    random_site.register(Product, RandomOrderingProductAdmin)
    mixed_site = NinjaAdminSite(include_auth=False)
    mixed_site.register(Product, MixedRandomOrderingProductAdmin)

    random_ids = {error.id for error in random_site.get_model_admin(Product).check()}
    mixed_errors = mixed_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E072" not in random_ids
    assert {error.id for error in mixed_errors} == {"django_ninja_admin.E072"}
    assert mixed_errors[0].hint == 'Either remove the "?", or remove the other fields.'


def test_admin_checks_validate_show_facets_option(db):
    class ValidFacetsProductAdmin(ModelAdmin):
        show_facets = ShowFacets.ALWAYS

    class BadFacetsProductAdmin(ModelAdmin):
        show_facets = "ALWAYS"

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFacetsProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadFacetsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E088" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E088"}


def test_admin_checks_validate_search_help_text_option(db):
    class ValidSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = "Search by product name."

    class BadSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = 123

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSearchHelpTextProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadSearchHelpTextProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E089" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E089"}


def test_admin_checks_validate_empty_value_display_option(db):
    class ValidEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = "No value"

    class BadEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = 123

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidEmptyValueProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadEmptyValueProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E097" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E097"}


def test_admin_checks_allow_relation_path_date_hierarchy(db):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"

    class BadDateHierarchyProductAdmin(ModelAdmin):
        date_hierarchy = 123

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(ProductImage, RelatedDateHierarchyImageAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadDateHierarchyProductAdmin)

    error_ids = {error.id for error in admin_site.get_model_admin(ProductImage).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E028", "django_ninja_admin.E029"})
    assert bad_ids == {"django_ninja_admin.E096"}


def test_admin_checks_allow_expression_ordering(db):
    class ExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("name").asc(),)

    class MissingExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("missing").desc(),)

    expression_site = NinjaAdminSite(include_auth=False)
    expression_site.register(Product, ExpressionOrderingProductAdmin)
    missing_site = NinjaAdminSite(include_auth=False)
    missing_site.register(Product, MissingExpressionOrderingProductAdmin)

    expression_ids = {error.id for error in expression_site.get_model_admin(Product).check()}
    missing_ids = {error.id for error in missing_site.get_model_admin(Product).check()}

    assert expression_ids.isdisjoint({"django_ninja_admin.E020", "django_ninja_admin.E021"})
    assert missing_ids == {"django_ninja_admin.E021"}


def test_admin_checks_validate_field_based_list_filter_classes(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFieldFilterProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadTupleShapeProductAdmin)
    bad_filter_site = NinjaAdminSite(include_auth=False)
    bad_filter_site.register(Product, BadTupleFilterProductAdmin)

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


def test_admin_checks_validate_form_class(db):
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

    class ValidInlineFormProductAdmin(ModelAdmin):
        inlines = [ValidFormInline]

    class PlainInlineFormProductAdmin(ModelAdmin):
        inlines = [PlainFormInline]

    class WrongModelInlineFormProductAdmin(ModelAdmin):
        inlines = [WrongModelFormInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFormProductAdmin)
    plain_site = NinjaAdminSite(include_auth=False)
    plain_site.register(Product, PlainFormProductAdmin)
    wrong_model_site = NinjaAdminSite(include_auth=False)
    wrong_model_site.register(Product, WrongModelFormProductAdmin)
    valid_inline_site = NinjaAdminSite(include_auth=False)
    valid_inline_site.register(Product, ValidInlineFormProductAdmin)
    plain_inline_site = NinjaAdminSite(include_auth=False)
    plain_inline_site.register(Product, PlainInlineFormProductAdmin)
    wrong_model_inline_site = NinjaAdminSite(include_auth=False)
    wrong_model_inline_site.register(Product, WrongModelInlineFormProductAdmin)

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


def test_admin_checks_validate_formfield_overrides(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidOverrideProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_field_key_site = NinjaAdminSite(include_auth=False)
    bad_field_key_site.register(Product, BadFieldKeyProductAdmin)
    bad_override_value_site = NinjaAdminSite(include_auth=False)
    bad_override_value_site.register(Product, BadOverrideValueProductAdmin)
    bad_override_key_site = NinjaAdminSite(include_auth=False)
    bad_override_key_site.register(Product, BadOverrideKeyProductAdmin)

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


def test_admin_checks_reject_reverse_relation_widget_fields(db):
    class ReviewAdmin(ModelAdmin):
        search_fields = ("note",)

    class ReverseAutocompleteProductAdmin(ModelAdmin):
        autocomplete_fields = ("reviews",)

    class ReverseRawIdProductAdmin(ModelAdmin):
        raw_id_fields = ("reviews",)

    autocomplete_site = NinjaAdminSite(include_auth=False)
    autocomplete_site.register(Product, ReverseAutocompleteProductAdmin)
    autocomplete_site.register(ProductReview, ReviewAdmin)
    raw_id_site = NinjaAdminSite(include_auth=False)
    raw_id_site.register(Product, ReverseRawIdProductAdmin)

    autocomplete_errors = autocomplete_site.get_model_admin(Product).check()
    raw_id_errors = raw_id_site.get_model_admin(Product).check()

    assert {error.id for error in autocomplete_errors} == {"django_ninja_admin.E025"}
    assert {error.id for error in raw_id_errors} == {"django_ninja_admin.E025"}


def test_admin_checks_require_registered_searchable_autocomplete_targets(db):
    class ProductAutocompleteAdmin(ModelAdmin):
        autocomplete_fields = ("category",)

    unregistered_site = NinjaAdminSite(include_auth=False)
    unregistered_site.register(Product, ProductAutocompleteAdmin)

    class UnsearchableCategoryAdmin(ModelAdmin):
        pass

    unsearchable_site = NinjaAdminSite(include_auth=False)
    unsearchable_site.register(Product, ProductAutocompleteAdmin)
    unsearchable_site.register(Category, UnsearchableCategoryAdmin)

    class SearchableCategoryAdmin(ModelAdmin):
        search_fields = ("name",)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ProductAutocompleteAdmin)
    valid_site.register(Category, SearchableCategoryAdmin)

    unregistered_errors = unregistered_site.get_model_admin(Product).check()
    unsearchable_errors = unsearchable_site.get_model_admin(Product).check()
    valid_errors = valid_site.get_model_admin(Product).check()

    assert {error.id for error in unregistered_errors} == {"django_ninja_admin.E026"}
    assert {error.id for error in unsearchable_errors} == {"django_ninja_admin.E027"}
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E026", "django_ninja_admin.E027"})


def test_admin_checks_validate_prepopulated_fields(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPrepopulatedProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_target_site = NinjaAdminSite(include_auth=False)
    bad_target_site.register(Product, BadTargetProductAdmin)
    bad_source_site = NinjaAdminSite(include_auth=False)
    bad_source_site.register(Product, BadSourceProductAdmin)

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


def test_admin_checks_reject_list_editable_fields_missing_from_generated_form(db):
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

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, MissingFromFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, ExcludedProductAdmin)
    fieldsets_site = NinjaAdminSite(include_auth=False)
    fieldsets_site.register(Product, MissingFromFieldsetsProductAdmin)

    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])
    fieldsets_errors = fieldsets_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert "django_ninja_admin.E044" in {error.id for error in fields_errors}
    assert "django_ninja_admin.E044" in {error.id for error in exclude_errors}
    assert "django_ninja_admin.E044" in {error.id for error in fieldsets_errors}


def test_admin_checks_reject_first_list_editable_without_explicit_display_link(db):
    class BadFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_editable = ("stock_status",)

    class ValidFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_display_links = ("name",)
        list_editable = ("stock_status",)

    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadFirstEditableProductAdmin)
    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFirstEditableProductAdmin)

    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}

    assert bad_ids == {"django_ninja_admin.E066"}
    assert valid_ids.isdisjoint({"django_ninja_admin.E007", "django_ninja_admin.E066"})


def test_admin_checks_reject_duplicate_list_editable_fields(db):
    class DuplicateEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = ("price", "price")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, DuplicateEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E093"}


def test_admin_checks_reject_non_string_list_editable_fields(db):
    class BadEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = (123,)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E094"}


def test_admin_checks_reject_duplicate_list_display_links(db):
    class DuplicateLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name", "name")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, DuplicateLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E079"}


def test_admin_checks_reject_non_string_list_display_links(db):
    class BadLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = (123,)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E095"}


def test_admin_checks_validate_fields_and_exclude_items(db):
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

    row_fields_site = NinjaAdminSite(include_auth=False)
    row_fields_site.register(Product, RowFieldsProductAdmin)
    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, BadFieldsProductAdmin)
    duplicate_fields_site = NinjaAdminSite(include_auth=False)
    duplicate_fields_site.register(Product, DuplicateFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, BadExcludeProductAdmin)
    duplicate_exclude_site = NinjaAdminSite(include_auth=False)
    duplicate_exclude_site.register(Product, DuplicateExcludeProductAdmin)

    row_fields_errors = row_fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    duplicate_fields_errors = duplicate_fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])
    duplicate_exclude_errors = duplicate_exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])

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


def test_admin_checks_reject_duplicate_readonly_fields(db):
    def readonly_summary(obj):
        return obj.name

    class ValidReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", readonly_summary)

    class DuplicateNameReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", "name")

    class DuplicateCallableReadonlyProductAdmin(ModelAdmin):
        readonly_fields = (readonly_summary, readonly_summary)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidReadonlyProductAdmin)
    duplicate_name_site = NinjaAdminSite(include_auth=False)
    duplicate_name_site.register(Product, DuplicateNameReadonlyProductAdmin)
    duplicate_callable_site = NinjaAdminSite(include_auth=False)
    duplicate_callable_site.register(Product, DuplicateCallableReadonlyProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    duplicate_name_ids = {error.id for error in duplicate_name_site.get_model_admin(Product).check()}
    duplicate_callable_ids = {error.id for error in duplicate_callable_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E092" not in valid_ids
    assert duplicate_name_ids == {"django_ninja_admin.E092"}
    assert duplicate_callable_ids == {"django_ninja_admin.E092"}


def test_admin_checks_validate_fieldsets_shape_and_duplicates(db):
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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFieldsetsProductAdmin)
    missing_site = NinjaAdminSite(include_auth=False)
    missing_site.register(Product, MissingFieldsOptionProductAdmin)
    string_site = NinjaAdminSite(include_auth=False)
    string_site.register(Product, StringFieldsProductAdmin)
    bad_item_site = NinjaAdminSite(include_auth=False)
    bad_item_site.register(Product, BadFieldItemProductAdmin)
    duplicate_site = NinjaAdminSite(include_auth=False)
    duplicate_site.register(Product, DuplicateFieldProductAdmin)

    assert valid_site.check(app_configs=[django_apps.get_app_config("testapp")]) == []
    assert list(valid_site.get_model_admin(Product).get_form_class(None).base_fields) == [
        "name",
        "price",
        "category",
        "description",
    ]
    assert {error.id for error in missing_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in string_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in bad_item_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in duplicate_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E064"
    }


def test_admin_checks_validate_radio_fields_shape(db):
    class BadRadioShapeAdmin(ModelAdmin):
        radio_fields = ("stock_status",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadRadioShapeAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert {error.id for error in errors} == {"django_ninja_admin.E034"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_widget_modes(db):
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

    horizontal_site = NinjaAdminSite(include_auth=False)
    horizontal_site.register(Article, HorizontalArticleAdmin)
    vertical_site = NinjaAdminSite(include_auth=False)
    vertical_site.register(Article, VerticalArticleAdmin)

    horizontal_errors = horizontal_site.get_model_admin(Article).check()
    vertical_errors = vertical_site.get_model_admin(Article).check()

    assert {error.id for error in horizontal_errors} == {"django_ninja_admin.E047"}
    assert {error.id for error in vertical_errors} == {"django_ninja_admin.E047"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_form_layouts(db):
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

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Article, FieldsArticleAdmin)
    fieldsets_site = NinjaAdminSite(include_auth=False)
    fieldsets_site.register(Article, FieldsetsArticleAdmin)

    fields_errors = fields_site.get_model_admin(Article).check()
    fieldsets_errors = fieldsets_site.get_model_admin(Article).check()

    assert {error.id for error in fields_errors} == {"django_ninja_admin.E078"}
    assert {error.id for error in fieldsets_errors} == {"django_ninja_admin.E078"}


def test_changelist_search_filter_and_detail(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["result_count"] == 1
    assert body["config"]["search_term"] == "Alpha"
    assert body["config"]["has_search"] is True
    assert body["config"]["clear_search_query_string"] == "?"
    assert body["rows"][0]["cells"]["name"] == "Alpha"

    filtered = admin_client.get("/admin-api/testapp/product?stock_status=out_of_stock")
    assert filtered.json()["config"]["result_count"] == 1

    exact_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert exact_filtered.status_code == 200
    assert exact_filtered.json()["rows"][0]["cells"]["name"] == "Beta"

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Alpha"
    assert detail.json()["category_label"] == "Cameras"
    assert detail.json()["manual"] == {
        "name": "manuals/alpha.pdf",
        "url": "/media/manuals/alpha.pdf",
    }
    assert set(detail.json()["tags"]) == set(sample.tags.values_list("pk", flat=True))


def test_changelist_filters_ordering_pagination_and_show_all(admin_client, sample):
    initial = admin_client.get("/admin-api/testapp/product")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert {item["parameter_name"] for item in initial_body["config"]["filters"]} == {
        "stock_status__exact",
        "price_band",
    }
    assert initial_body["config"]["has_filters"] is True
    assert initial_body["config"]["has_active_filters"] is False
    assert initial_body["config"]["clear_all_filters_query_string"] is None
    assert initial_body["config"]["facets_optional"] is True
    assert initial_body["config"]["add_facets_query_string"] == "?_facets=1"
    assert initial_body["config"]["remove_facets_query_string"] is None
    assert initial_body["config"]["ordering"] == ["name", "-pk"]
    initial_name_column = next(column for column in initial_body["columns"] if column["field"] == "name")
    assert initial_name_column["sorted"] is True
    assert initial_name_column["ascending"] is True
    assert initial_name_column["sort_priority"] == 1
    assert initial_name_column["ascending_query_string"] == "?o=1"
    assert initial_name_column["descending_query_string"] == "?o=-1"
    assert initial_name_column["remove_sorting_query_string"] is None

    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=accessories, price="6.00", description="Stable")

    related_filtered = admin_client.get(f"/admin-api/testapp/product?category__id__exact={sample.category_id}")
    assert related_filtered.status_code == 200
    assert related_filtered.json()["config"]["result_count"] == 2
    assert "category__id__exact" in {item["parameter_name"] for item in related_filtered.json()["config"]["filters"]}

    simple_filtered = admin_client.get("/admin-api/testapp/product?price_band=cheap")
    assert simple_filtered.status_code == 200
    assert [row["cells"]["name"] for row in simple_filtered.json()["rows"]] == ["Beta", "Tripod"]

    choice_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert choice_filtered.json()["config"]["has_active_filters"] is True
    assert choice_filtered.json()["config"]["clear_all_filters_query_string"] == "?"
    assert choice_filtered.json()["config"]["add_facets_query_string"] == "?stock_status__exact=out_of_stock&_facets=1"
    stock_filter = next(
        item for item in choice_filtered.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert any(choice["selected"] and choice["display"] == "Out of Stock" for choice in stock_filter["choices"])
    assert any("stock_status__exact=in_stock" in choice["query_string"] for choice in stock_filter["choices"])

    price_ordered = admin_client.get("/admin-api/testapp/product?o=3")
    assert [row["cells"]["name"] for row in price_ordered.json()["rows"]] == ["Beta", "Tripod", "Alpha"]

    display_ordered = admin_client.get("/admin-api/testapp/product?o=-5")
    assert [row["cells"]["name"] for row in display_ordered.json()["rows"]] == ["Tripod", "Beta", "Alpha"]

    paginated = admin_client.get("/admin-api/testapp/product?pp=1&page=2")
    assert paginated.status_code == 200
    paginated_body = paginated.json()
    assert paginated_body["config"]["page"] == 2
    assert paginated_body["config"]["page_count"] == 3
    assert paginated_body["config"]["pagination"] == {
        "count": 3,
        "num_pages": 3,
        "page": 2,
        "per_page": 1,
        "has_next": True,
        "has_previous": True,
        "more": True,
    }
    assert paginated_body["config"]["has_next"] is True
    assert paginated_body["config"]["has_previous"] is True
    assert paginated_body["config"]["multi_page"] is True
    assert paginated_body["config"]["pagination_required"] is True
    assert paginated_body["config"]["page_range"] == [1, 2, 3]
    assert paginated_body["config"]["page_choices"] == [
        {"display": "1", "page": 1, "selected": False, "query_string": "?pp=1"},
        {"display": "2", "page": 2, "selected": True, "query_string": "?pp=1&p=2"},
        {"display": "3", "page": 3, "selected": False, "query_string": "?pp=1&p=3"},
    ]
    assert len(paginated_body["rows"]) == 1
    assert paginated_body["config"]["page_result_count"] == 1
    assert paginated_body["config"]["result_start_index"] == 2
    assert paginated_body["config"]["result_end_index"] == 2
    assert paginated_body["rows"][0]["index"] == 0
    assert paginated_body["rows"][0]["result_index"] == 2
    assert paginated_body["config"]["first_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["previous_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["next_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["last_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["show_all_query_string"] == "?pp=1&all=1"
    assert paginated_body["config"]["clear_show_all_query_string"] is None

    generated_query_strings = []
    for filter_description in paginated_body["config"]["filters"]:
        generated_query_strings.extend(choice["query_string"] for choice in filter_description["choices"])
    generated_query_strings.extend(
        column["ascending_query_string"] for column in paginated_body["columns"] if column["ascending_query_string"]
    )
    generated_query_strings.extend(
        choice["query_string"] for choice in paginated_body["config"]["date_hierarchy"]["choices"]
    )
    generated_query_strings.append(paginated_body["config"]["date_hierarchy"]["clear_query_string"])
    for query_string in generated_query_strings:
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params
        assert "p" not in params
    for query_string in (
        paginated_body["config"]["first_page_query_string"],
        paginated_body["config"]["previous_page_query_string"],
        paginated_body["config"]["next_page_query_string"],
        paginated_body["config"]["last_page_query_string"],
        paginated_body["config"]["show_all_query_string"],
        *(choice["query_string"] for choice in paginated_body["config"]["page_choices"] if choice["query_string"]),
    ):
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params

    prefixed_filter = admin_client.get("/admin-api/testapp/product?price__gte=1&pp=1&page=2&o=3")
    assert prefixed_filter.status_code == 200
    prefixed_body = prefixed_filter.json()
    prefixed_price_column = next(column for column in prefixed_body["columns"] if column["field"] == "price")
    assert prefixed_body["config"]["previous_page_query_string"] == "?price__gte=1&pp=1&o=3"
    assert prefixed_body["config"]["next_page_query_string"] == "?price__gte=1&pp=1&o=3&p=3"
    assert prefixed_body["config"]["show_all_query_string"] == "?price__gte=1&pp=1&o=3&all=1"
    assert prefixed_body["config"]["has_active_filters"] is True
    assert prefixed_body["config"]["clear_all_filters_query_string"] == "?pp=1&o=3"
    assert prefixed_body["config"]["search_term"] == ""
    assert prefixed_body["config"]["has_search"] is False
    assert prefixed_body["config"]["clear_search_query_string"] is None
    assert prefixed_price_column["descending_query_string"] == "?price__gte=1&pp=1&o=-3"
    assert prefixed_price_column["remove_sorting_query_string"] == "?price__gte=1&pp=1"
    prefixed_stock_filter = next(
        item for item in prefixed_body["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    prefixed_stock_choice = next(
        choice for choice in prefixed_stock_filter["choices"] if choice["display"] == "In Stock"
    )
    assert prefixed_stock_choice["query_string"] == "?price__gte=1&pp=1&o=3&stock_status__exact=in_stock"

    searched_with_state = admin_client.get("/admin-api/testapp/product?price__gte=1&q=a&pp=1&page=2&o=3")
    assert searched_with_state.status_code == 200
    assert searched_with_state.json()["config"]["search_term"] == "a"
    assert searched_with_state.json()["config"]["has_search"] is True
    assert searched_with_state.json()["config"]["clear_search_query_string"] == "?price__gte=1&pp=1&o=3"

    last_page = admin_client.get("/admin-api/testapp/product?pp=1&page=last")
    assert last_page.status_code == 200
    assert last_page.json()["config"]["page"] == 3
    assert last_page.json()["rows"][0]["cells"]["name"] == "Tripod"

    show_all = admin_client.get("/admin-api/testapp/product?all=1")
    assert show_all.status_code == 200
    show_all_body = show_all.json()
    assert len(show_all_body["rows"]) == show_all_body["config"]["result_count"]
    assert show_all_body["config"]["full_count"] == 3
    assert show_all_body["config"]["page_result_count"] == 3
    assert show_all_body["config"]["result_start_index"] == 1
    assert show_all_body["config"]["result_end_index"] == 3
    assert show_all_body["config"]["show_all"] is True
    assert show_all_body["config"]["can_show_all"] is True
    assert show_all_body["config"]["pagination_required"] is False
    assert show_all_body["config"]["page_range"] == []
    assert show_all_body["config"]["page_choices"] == []
    assert show_all_body["config"]["first_page_query_string"] is None
    assert show_all_body["config"]["previous_page_query_string"] is None
    assert show_all_body["config"]["next_page_query_string"] is None
    assert show_all_body["config"]["last_page_query_string"] is None
    assert show_all_body["config"]["show_all_query_string"] is None
    assert show_all_body["config"]["clear_show_all_query_string"] == "?"
    assert show_all_body["config"]["list_display_links"] == ["name"]
    assert show_all_body["config"]["actions_on_top"] is True
    assert show_all_body["config"]["actions_on_bottom"] is False
    assert show_all_body["config"]["actions_selection_counter"] is True
    assert show_all_body["config"]["show_full_result_count"] is True
    assert show_all_body["config"]["show_admin_actions"] is True
    assert show_all_body["columns"][0]["display_link"] is True
    assert show_all_body["columns"][2]["sortable"] is True
    assert show_all_body["config"]["search_fields"] == ["name", "description", "category__name"]
    price_column = next(column for column in show_all_body["columns"] if column["field"] == "price")
    assert price_column["ascending_query_string"] == "?all=1&o=3"
    assert price_column["descending_query_string"] == "?all=1&o=-3"
    assert price_column["remove_sorting_query_string"] == "?all=1"
    columns_by_field = {column["field"]: column for column in show_all_body["columns"]}
    assert columns_by_field["has_description"]["boolean"] is True
    assert columns_by_field["tagline"]["empty_value_display"] == "No description"
    assert columns_by_field["is_expensive"]["header_name"] == "Expensive"
    assert columns_by_field["is_expensive"]["boolean"] is True
    assert columns_by_field["subtitle"]["header_name"] == "Subtitle"
    assert columns_by_field["subtitle"]["empty_value_display"] == "No subtitle"
    rows_by_name = {row["cells"]["name"]: row for row in show_all_body["rows"]}
    assert [row["index"] for row in show_all_body["rows"]] == [0, 1, 2]
    assert [row["result_index"] for row in show_all_body["rows"]] == [1, 2, 3]
    alpha_name_cell = rows_by_name["Alpha"]["cell_metadata"]["name"]
    assert alpha_name_cell == {
        "field": "name",
        "header_name": "Name",
        "value": "Alpha",
        "display_value": "Alpha",
        "empty": False,
        "boolean": False,
        "display_link": True,
        "sortable": True,
        "ordering_field": "name",
        "editable": False,
        "empty_value_display": "-",
    }
    beta_tagline_cell = rows_by_name["Beta"]["cell_metadata"]["tagline"]
    assert beta_tagline_cell["value"] is None
    assert beta_tagline_cell["display_value"] == "No description"
    assert beta_tagline_cell["empty"] is True
    assert beta_tagline_cell["empty_value_display"] == "No description"
    beta_stock_cell = rows_by_name["Beta"]["cell_metadata"]["stock_status"]
    assert beta_stock_cell["editable"] is True
    assert beta_stock_cell["display_link"] is False

    show_all_by_presence = admin_client.get("/admin-api/testapp/product?all=0")
    assert show_all_by_presence.status_code == 200
    show_all_by_presence_body = show_all_by_presence.json()
    assert show_all_by_presence_body["config"]["show_all"] is True
    assert show_all_by_presence_body["config"]["pagination_required"] is False
    assert len(show_all_by_presence_body["rows"]) == show_all_by_presence_body["config"]["result_count"]

    alpha_row = rows_by_name["Alpha"]
    content_type = ContentType.objects.get_for_model(Product)
    assert alpha_row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert alpha_row["delete_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["view_on_site_url"] == f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}"
    assert alpha_row["permissions"] == {
        "has_add_permission": True,
        "has_change_permission": True,
        "has_delete_permission": True,
        "has_view_permission": True,
    }
    assert rows_by_name["Alpha"]["cells"]["has_description"] is True
    assert rows_by_name["Alpha"]["cells"]["tagline"] == "Nice camera"
    assert rows_by_name["Alpha"]["cells"]["is_expensive"] is True
    assert rows_by_name["Alpha"]["cells"]["subtitle"] == "Nice camera"
    assert rows_by_name["Beta"]["cells"]["has_description"] is False
    assert rows_by_name["Beta"]["cells"]["tagline"] == "No description"
    assert rows_by_name["Beta"]["cells"]["is_expensive"] is False
    assert rows_by_name["Beta"]["cells"]["subtitle"] == "No subtitle"

    empty = admin_client.get("/admin-api/testapp/product?q=missing")
    assert empty.status_code == 200
    assert empty.json()["config"]["search_term"] == "missing"
    assert empty.json()["config"]["has_search"] is True
    assert empty.json()["config"]["clear_search_query_string"] == "?"
    assert empty.json()["config"]["result_count"] == 0
    assert empty.json()["config"]["page_result_count"] == 0
    assert empty.json()["config"]["result_start_index"] == 0
    assert empty.json()["config"]["result_end_index"] == 0


def test_changelist_supports_callable_list_display(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    @display(description="Stock badge", ordering="stock_status", boolean=True)
    def stock_badge(obj):
        return obj.stock_status == "in_stock"

    monkeypatch.setattr(product_admin, "list_display", ("name", stock_badge))
    monkeypatch.setattr(product_admin, "sortable_by", (stock_badge,))

    response = admin_client.get("/admin-api/testapp/product?o=-2")

    assert response.status_code == 200
    error_ids = {error.id for error in product_admin.check()}
    assert "django_ninja_admin.E002" not in error_ids
    assert "django_ninja_admin.E057" not in error_ids
    body = response.json()
    stock_column = next(column for column in body["columns"] if column["field"] == "stock_badge")
    assert stock_column["header_name"] == "Stock badge"
    assert stock_column["boolean"] is True
    assert stock_column["sortable"] is True
    assert stock_column["ordering_field"] == "stock_status"
    assert body["config"]["ordering_field_columns"] == {"stock_badge": 2}
    assert body["rows"][0]["cells"]["name"] == "Beta"
    assert body["rows"][0]["cells"]["stock_badge"] is False
    assert body["rows"][1]["cells"]["name"] == "Alpha"
    assert body["rows"][1]["cells"]["stock_badge"] is True


def test_changelist_supports_relation_path_list_display(admin_client, sample, monkeypatch):
    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Omega", category=accessories, price="1.00")
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_display", ("name", "category__name"))

    response = admin_client.get("/admin-api/testapp/product?o=2")

    assert response.status_code == 200
    body = response.json()
    category_column = next(column for column in body["columns"] if column["field"] == "category__name")
    assert category_column["header_name"] == "Name"
    assert category_column["sortable"] is True
    assert category_column["ordering_field"] == "category__name"
    assert category_column["ordering_index"] == 2
    assert body["config"]["ordering"] == ["category__name", "-pk"]
    assert body["config"]["ordering_field_columns"] == {"name": 1, "category__name": 2}
    assert body["rows"][0]["cells"] == {"name": "Omega", "category__name": "Accessories"}
    assert body["rows"][1]["cells"]["category__name"] == "Cameras"


def test_changelist_ordering_adds_deterministic_pk_fallback(admin_client, sample, monkeypatch):
    duplicate = Product.objects.create(name="Alpha", category=sample.category, price="6.00")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["name", "-pk"]
    alpha_ids = [row["id"] for row in body["rows"] if row["cells"]["name"] == "Alpha"]
    assert alpha_ids == [duplicate.pk, sample.pk]

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "ordering", ("id",))

    unique_ordering = admin_client.get("/admin-api/testapp/product")

    assert unique_ordering.status_code == 200
    assert unique_ordering.json()["config"]["ordering"] == ["id"]


def test_changelist_preserves_custom_queryset_ordering(db, sample):
    class QuerysetOrderedProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)

        def get_queryset(self, request):
            return super().get_queryset(request).order_by("-price")

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, QuerysetOrderedProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    user = get_user_model().objects.create_user("queryset-ordering-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, model_admin)

    assert changelist.ordering == ["-price", "-pk"]
    assert [obj.name for obj in changelist.result_list] == ["Alpha", "Gamma", "Beta"]
    price_sort = changelist.column_sort_query_strings("price")
    assert price_sort["sorted"] is True
    assert price_sort["ascending"] is False
    assert price_sort["sort_priority"] == 1
    assert price_sort["remove_sorting_query_string"] is None


def test_changelist_row_metadata_honors_object_permissions(staff_client, sample):
    response = staff_client("view_product").get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["index"] == 0
    assert row["result_index"] == 1
    assert row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert row["delete_url"] is None
    assert row["permissions"] == {
        "has_add_permission": False,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_change_form_metadata_honors_custom_object_permission_hooks(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_change_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    def has_delete_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    monkeypatch.setattr(product_admin, "has_change_permission", has_change_permission)
    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    assert response.json()["form"]["permissions"] == {
        "has_add_permission": True,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_changelist_action_ui_metadata_follows_model_admin(admin_client, staff_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "actions_on_top", False)
    monkeypatch.setattr(product_admin, "actions_on_bottom", True)
    monkeypatch.setattr(product_admin, "actions_selection_counter", False)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["actions_on_top"] is False
    assert config["actions_on_bottom"] is True
    assert config["actions_selection_counter"] is False
    choices_by_action = {choice["action"]: choice for choice in config["action_choices"]}
    assert choices_by_action["delete_selected"]["permissions"] == ["delete"]
    assert choices_by_action["mark_out_of_stock"]["permissions"] == ["change"]
    assert choices_by_action["report_names"]["permissions"] == ["view"]
    assert choices_by_action["set_stock_status"]["permissions"] == ["change"]
    assert {field["name"] for field in response.json()["action_form"]} == {"action", "selected_ids", "select_across"}

    view_only = staff_client("view_product").get("/admin-api/testapp/product")
    assert view_only.status_code == 200
    assert view_only.json()["config"]["action_choices"] == [
        {"action": "report_names", "description": "Report names", "permissions": ["view"]}
    ]
    action_field = next(field for field in view_only.json()["action_form"] if field["name"] == "action")
    assert action_field["attrs"]["choices"] == [["report_names", "Report names"]]


def test_changelist_exposes_list_editing_row_metadata(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    rows = body["list_editing_rows"]
    legacy_formset = body["list_editing_formset"]

    assert body["list_editing_formset_prefix"] == "form"
    assert body["list_editing_total_form_count"] == 2
    assert body["list_editing_initial_form_count"] == 2
    management_fields = {field["name"]: field for field in body["list_editing_management_form"]}
    assert_no_rendered_field_attrs(management_fields["TOTAL_FORMS"]["attrs"])
    assert management_fields["TOTAL_FORMS"]["attrs"]["value"] == 2
    assert_no_rendered_field_attrs(management_fields["INITIAL_FORMS"]["attrs"])
    assert management_fields["INITIAL_FORMS"]["attrs"]["value"] == 2
    assert management_fields["MIN_NUM_FORMS"]["attrs"]["value"] == 0
    assert management_fields["MAX_NUM_FORMS"]["attrs"]["value"] >= 2
    assert [row["index"] for row in rows] == [0, 1]
    assert [row["pk"] for row in rows] == [row["id"] for row in body["rows"]]
    assert {row["pk_name"] for row in rows} == {"id"}
    assert [row["form_prefix"] for row in rows] == ["form-0", "form-1"]
    assert [row["empty_permitted"] for row in rows] == [False, False]
    assert [[field["name"] for field in row["fields"]] for row in rows] == [["stock_status"], ["stock_status"]]
    assert legacy_formset == [row["fields"] for row in rows]
    assert rows[0]["fields"][0]["attrs"]["value"] == "in_stock"
    assert_no_rendered_field_attrs(rows[0]["fields"][0]["attrs"])
    assert rows[1]["fields"][0]["attrs"]["value"] == "out_of_stock"
    assert_no_rendered_field_attrs(rows[1]["fields"][0]["attrs"])
    assert rows[0]["fields"][0]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]


def test_changelist_can_skip_full_result_count(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "show_full_result_count", False)

    response = admin_client.get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["result_count"] == 1
    assert config["full_count"] is None
    assert config["show_full_result_count"] is False
    assert config["show_admin_actions"] is True


def test_choices_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    Product.objects.filter(pk=sample.pk).update(condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["Unspecified"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["New"]["query_string"] == "?condition__exact=new"

    unspecified = admin_client.get("/admin-api/testapp/product?condition__isnull=1")
    assert unspecified.status_code == 200
    unspecified_body = unspecified.json()
    assert unspecified_body["config"]["result_count"] == 1
    assert unspecified_body["rows"][0]["cells"]["name"] == "Beta"
    condition_filter = next(
        item for item in unspecified_body["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    selected_unspecified = next(choice for choice in condition_filter["choices"] if choice["display"] == "Unspecified")
    assert selected_unspecified["selected"] is True

    concrete = admin_client.get("/admin-api/testapp/product?condition__exact=new")
    assert concrete.status_code == 200
    assert concrete.json()["config"]["result_count"] == 1
    assert concrete.json()["rows"][0]["cells"]["name"] == "Alpha"


def test_all_values_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    Product.objects.filter(pk=sample.pk).update(condition="used")
    Product.objects.create(name="Tripod", category=sample.category, price="6.00", condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "condition")
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["-"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["-"]["query_string"] != choices_by_display["All"]["query_string"]

    null_response = admin_client.get(f"/admin-api/testapp/product{choices_by_display['-']['query_string']}")

    assert null_response.status_code == 200
    assert null_response.json()["config"]["result_count"] == 1
    condition_filter = next(item for item in null_response.json()["config"]["filters"] if item["title"] == "condition")
    null_choice = next(choice for choice in condition_filter["choices"] if choice["display"] == "-")
    assert null_choice["selected"] is True


def test_list_filters_reject_invalid_isnull_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    choices_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert choices_response.status_code == 400
    assert choices_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", ("category",))
    related_response = admin_client.get("/admin-api/testapp/product?category__isnull=maybe")
    assert related_response.status_code == 400
    assert related_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "category__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    all_values_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert all_values_response.status_code == 400
    assert all_values_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]


def test_changelist_direct_lookup_params_prepare_in_and_isnull_values(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(condition="new")

    in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk},{beta.pk}")

    assert in_lookup.status_code == 200
    assert in_lookup.json()["config"]["result_count"] == 2

    repeated_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk}")
    assert repeated_in_lookup.status_code == 200
    assert repeated_in_lookup.json()["config"]["result_count"] == 2

    mixed_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk},999999")
    assert mixed_in_lookup.status_code == 200
    assert mixed_in_lookup.json()["config"]["result_count"] == 2

    non_null = admin_client.get("/admin-api/testapp/product?condition__isnull=0")
    assert non_null.status_code == 200
    assert non_null.json()["config"]["result_count"] == 1
    assert non_null.json()["rows"][0]["cells"]["name"] == "Alpha"

    null = admin_client.get("/admin-api/testapp/product?condition__isnull=true")
    assert null.status_code == 200
    assert null.json()["config"]["result_count"] == 1
    assert null.json()["rows"][0]["cells"]["name"] == "Beta"

    invalid_in = admin_client.get("/admin-api/testapp/product?id__in=not-a-number")
    assert invalid_in.status_code == 400
    assert invalid_in.json()["errors"] == [{"message": "Invalid lookup value.", "param": "id__in"}]

    invalid_isnull = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert invalid_isnull.status_code == 400
    assert invalid_isnull.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]


def test_empty_field_list_filter_validates_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("description", EmptyFieldListFilter),))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    description_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "description__isempty"
    )
    choices_by_display = {choice["display"]: choice for choice in description_filter["choices"]}
    assert choices_by_display["Empty"]["query_string"] == "?description__isempty=1"
    assert choices_by_display["Not empty"]["query_string"] == "?description__isempty=0"

    empty = admin_client.get("/admin-api/testapp/product?description__isempty=1")
    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"

    not_empty = admin_client.get("/admin-api/testapp/product?description__isempty=0")
    assert not_empty.status_code == 200
    assert not_empty.json()["config"]["result_count"] == 1
    assert not_empty.json()["rows"][0]["cells"]["name"] == "Alpha"

    invalid = admin_client.get("/admin-api/testapp/product?description__isempty=maybe")
    assert invalid.status_code == 400
    assert invalid.json()["errors"] == [{"message": "Invalid lookup value.", "param": "description__isempty"}]


def test_simple_list_filter_without_lookups_is_hidden(admin_client, sample, monkeypatch):
    class HiddenFilter(SimpleListFilter):
        title = "hidden"
        parameter_name = "hidden"

        def lookups(self, request, model_admin):
            return ()

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (HiddenFilter,))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_related_field_list_filter_includes_many_to_many_empty_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("tags",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    tag_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in tag_filter["choices"]}
    assert choices_by_display["None"]["query_string"] == "?tags__isnull=1"

    empty = admin_client.get("/admin-api/testapp/product?tags__isnull=1")

    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"
    tag_filter = next(item for item in empty.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact")
    selected_none = next(choice for choice in tag_filter["choices"] if choice["display"] == "None")
    assert selected_none["selected"] is True


def test_related_only_list_filter_honors_related_admin_ordering(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    category_admin = site.get_model_admin(Category)
    zooms = Category.objects.create(name="Zooms")
    Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=zooms, price="6.00", description="Stable")
    monkeypatch.setattr(product_admin, "list_filter", (("category", RelatedOnlyFieldListFilter),))
    monkeypatch.setattr(category_admin, "ordering", ("-name",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    category_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "category__id__exact"
    )
    choices = [choice["display"] for choice in category_filter["choices"] if choice["display"] != "All"]
    assert choices == ["Zooms", "Cameras"]


def test_changelist_search_distincts_duplicate_many_to_many_matches(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    match_one = Tag.objects.create(name="Search Match One")
    match_two = Tag.objects.create(name="Search Match Two")
    sample.tags.add(match_one, match_two)
    monkeypatch.setattr(product_admin, "search_fields", ("tags__name",))

    response = admin_client.get("/admin-api/testapp/product?q=Search")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert [row["cells"]["name"] for row in response.json()["rows"]] == ["Alpha"]


def test_changelist_multi_column_ordering_metadata(admin_client, sample):
    Product.objects.create(name="Gamma", category=sample.category, price="3.00")

    response = admin_client.get("/admin-api/testapp/product?o=3,-1")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["price", "-name", "-pk"]
    assert [row["cells"]["name"] for row in body["rows"]][:2] == ["Gamma", "Beta"]

    columns_by_field = {column["field"]: column for column in body["columns"]}
    price_column = columns_by_field["price"]
    name_column = columns_by_field["name"]
    stock_column = columns_by_field["stock_status"]
    assert price_column["sorted"] is True
    assert price_column["ascending"] is True
    assert price_column["sort_priority"] == 1
    assert price_column["ascending_query_string"] == "?o=3,-1"
    assert price_column["descending_query_string"] == "?o=-3,-1"
    assert price_column["remove_sorting_query_string"] == "?o=-1"
    assert name_column["sorted"] is True
    assert name_column["ascending"] is False
    assert name_column["sort_priority"] == 2
    assert name_column["ascending_query_string"] == "?o=1,3"
    assert name_column["descending_query_string"] == "?o=-1,3"
    assert name_column["remove_sorting_query_string"] == "?o=3"
    assert stock_column["sorted"] is False
    assert stock_column["sort_priority"] is None


def test_changelist_search_supports_lookup_suffixes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(
        name="Alphabet",
        category=sample.category,
        price="14.00",
        description="Starts the same",
    )
    Product.objects.create(
        name="Beta Alpha",
        category=sample.category,
        price="5.00",
        description="Contains the word later",
    )

    monkeypatch.setattr(product_admin, "search_fields", ("^name",))
    startswith = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert startswith.status_code == 200
    assert [row["cells"]["name"] for row in startswith.json()["rows"]] == ["Alpha", "Alphabet"]

    monkeypatch.setattr(product_admin, "search_fields", ("=name",))
    iexact = admin_client.get("/admin-api/testapp/product?q=alpha")
    assert iexact.status_code == 200
    assert [row["cells"]["name"] for row in iexact.json()["rows"]] == ["Alpha"]

    monkeypatch.setattr(product_admin, "search_fields", ("category__id__exact",))
    category_exact = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id}")
    assert category_exact.status_code == 200
    assert category_exact.json()["config"]["result_count"] == 4

    padded_category = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id:03d}")
    assert padded_category.status_code == 200
    assert padded_category.json()["config"]["result_count"] == 0


def test_changelist_auto_selects_related_list_display_fields(db):
    user = get_user_model().objects.create_user("query-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, site.get_model_admin(Product))

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related


def test_changelist_auto_selects_related_display_ordering_paths(db, sample):
    @display(description="Category label", ordering="category__name")
    def category_label(obj):
        return obj.category.name

    class RelatedOrderingProductAdmin(ModelAdmin):
        list_display = ("name", category_label)
        ordering = ("name",)

    Category.objects.create(name="Accessories")
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelatedOrderingProductAdmin)
    user = get_user_model().objects.create_user("query-admin-callable", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [category_label(obj) for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_auto_selects_relation_path_list_display_fields(db, sample):
    class RelationPathProductAdmin(ModelAdmin):
        list_display = ("name", "category__name")
        sortable_by = ("name",)
        ordering = ("name",)

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelationPathProductAdmin)
    user = get_user_model().objects.create_user("query-admin-relation-path", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [obj.category.name for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_applies_list_prefetch_related_for_callable_display(db, sample):
    @display(description="Tag names")
    def tag_names(obj):
        return ", ".join(sorted(tag.name for tag in obj.tags.all()))

    class PrefetchProductAdmin(ModelAdmin):
        list_display = ("name", tag_names)
        list_prefetch_related = ("tags",)
        ordering = ("name",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, PrefetchProductAdmin)
    user = get_user_model().objects.create_user("query-admin-prefetch", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.list_prefetch_related == ("tags",)
    assert changelist.queryset._prefetch_related_lookups == ("tags",)
    with CaptureQueriesContext(connection) as queries:
        rendered = [tag_names(obj) for obj in changelist.result_list]

    assert rendered == ["Compact, Featured", ""]
    assert len(queries) == 0


def test_changelist_applies_prefetch_objects_for_callable_display(db, sample):
    @display(description="Prefetched tag names")
    def prefetched_tag_names(obj):
        return ", ".join(tag.name for tag in obj.prefetched_tags)

    class PrefetchObjectProductAdmin(ModelAdmin):
        list_display = ("name", prefetched_tag_names)
        list_prefetch_related = (
            models.Prefetch("tags", queryset=Tag.objects.order_by("name"), to_attr="prefetched_tags"),
        )
        ordering = ("name",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, PrefetchObjectProductAdmin)
    user = get_user_model().objects.create_user("query-admin-prefetch-object", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert isinstance(changelist.list_prefetch_related[0], models.Prefetch)
    assert isinstance(changelist.queryset._prefetch_related_lookups[0], models.Prefetch)
    with CaptureQueriesContext(connection) as queries:
        rendered = [prefetched_tag_names(obj) for obj in changelist.result_list]

    assert rendered == ["Compact, Featured", ""]
    assert len(queries) == 0


def test_changelist_route_uses_model_admin_hook(admin_client, sample, monkeypatch):
    class CustomChangeList(ChangeList):
        def filter_descriptions(self):
            return []

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "get_changelist", lambda request, **kwargs: CustomChangeList)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_changelist_route_uses_model_admin_paginator_hook(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    calls = {}

    def get_paginator(request, queryset, per_page, orphans=0, allow_empty_first_page=True):
        calls["path"] = request.path
        calls["model"] = queryset.model
        calls["is_queryset"] = isinstance(queryset, models.QuerySet)
        calls["per_page"] = per_page
        calls["orphans"] = orphans
        calls["allow_empty_first_page"] = allow_empty_first_page
        return Paginator(
            queryset,
            per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    monkeypatch.setattr(product_admin, "get_paginator", get_paginator)

    response = admin_client.get("/admin-api/testapp/product?pp=1")

    assert response.status_code == 200
    assert response.json()["config"]["page_count"] == 3
    assert calls == {
        "path": "/admin-api/testapp/product",
        "model": Product,
        "is_queryset": True,
        "per_page": 1,
        "orphans": 0,
        "allow_empty_first_page": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_custom_site_and_model_admin_views_are_registered_and_permissioned(admin_client, staff_client, sample):
    site_response = admin_client.get("/custom-admin/status")
    assert site_response.status_code == 200
    assert site_response.json() == {"site": "ok"}

    decorated_site_response = admin_client.get("/custom-admin/decorated-status")
    assert decorated_site_response.status_code == 200
    assert decorated_site_response.json() == {"site": "decorated"}

    auto_site_response = admin_client.get("/custom-admin/auto-status")
    assert auto_site_response.status_code == 200
    assert auto_site_response.json() == {"site": "auto"}

    mapped_site_response = admin_client.get("/custom-admin/mapped-status")
    assert mapped_site_response.status_code == 200
    assert mapped_site_response.json() == {"site": "mapped"}

    explicit_multi_get = admin_client.get("/custom-admin/explicit-multi-status")
    explicit_multi_post = admin_client.post("/custom-admin/explicit-multi-status")
    assert explicit_multi_get.status_code == 200
    assert explicit_multi_get.json() == {"site": "explicit-multi"}
    assert explicit_multi_post.status_code == 200
    assert explicit_multi_post.json() == {"site": "explicit-multi"}

    decorated_auto_site_response = admin_client.get("/custom-admin/decorated-auto-status")
    assert decorated_auto_site_response.status_code == 200
    assert decorated_auto_site_response.json() == {"site": "decorated-auto"}

    token_primary = Client().get("/custom-admin/token-status", headers={"X-Primary-Token": "primary"})
    token_secondary = Client().get("/custom-admin/token-status", headers={"X-Secondary-Token": "secondary"})
    token_denied = Client().get("/custom-admin/token-status")
    assert token_primary.status_code == 200
    assert token_primary.json() == {"auth": "primary"}
    assert token_secondary.status_code == 200
    assert token_secondary.json() == {"auth": "secondary"}
    assert token_denied.status_code == 401

    public_response = Client().get("/custom-admin/public-status")
    assert public_response.status_code == 200
    assert public_response.json() == {"public": "ok"}

    hidden_response = admin_client.get("/custom-admin/hidden-status")
    assert hidden_response.status_code == 200
    assert hidden_response.json() == {"hidden": "ok"}

    stats = admin_client.get("/custom-admin/testapp/product/stats")
    assert stats.status_code == 200
    assert stats.json() == {"count": 2}

    decorated_stats = admin_client.get("/custom-admin/testapp/product/decorated-stats")
    assert decorated_stats.status_code == 200
    assert decorated_stats.json() == {"count": 2}

    auto_stats = admin_client.get("/custom-admin/testapp/product/auto-stats")
    assert auto_stats.status_code == 200
    assert auto_stats.json() == {"count": 2}

    auto_multi_get = admin_client.get("/custom-admin/testapp/product/auto-multi-stats")
    auto_multi_post = admin_client.post("/custom-admin/testapp/product/auto-multi-stats")
    assert auto_multi_get.status_code == 200
    assert auto_multi_get.json() == {"count": 2}
    assert auto_multi_post.status_code == 200
    assert auto_multi_post.json() == {"count": 2}

    denied = staff_client().get("/custom-admin/testapp/product/stats")
    assert denied.status_code == 403

    decorated_denied = staff_client().get("/custom-admin/testapp/product/decorated-stats")
    assert decorated_denied.status_code == 403

    schema = admin_client.get("/custom-admin/openapi.json").json()
    status_operation = schema["paths"]["/custom-admin/status"]["get"]
    decorated_status_operation = schema["paths"]["/custom-admin/decorated-status"]["get"]
    auto_status_operation = schema["paths"]["/custom-admin/auto-status"]["get"]
    mapped_status_operation = schema["paths"]["/custom-admin/mapped-status"]["get"]
    explicit_multi_get_operation = schema["paths"]["/custom-admin/explicit-multi-status"]["get"]
    explicit_multi_post_operation = schema["paths"]["/custom-admin/explicit-multi-status"]["post"]
    decorated_auto_status_operation = schema["paths"]["/custom-admin/decorated-auto-status"]["get"]
    token_operation = schema["paths"]["/custom-admin/token-status"]["get"]
    public_operation = schema["paths"]["/custom-admin/public-status"]["get"]
    stats_operation = schema["paths"]["/custom-admin/testapp/product/stats"]["get"]
    decorated_stats_operation = schema["paths"]["/custom-admin/testapp/product/decorated-stats"]["get"]
    auto_stats_operation = schema["paths"]["/custom-admin/testapp/product/auto-stats"]["get"]
    auto_multi_get_operation = schema["paths"]["/custom-admin/testapp/product/auto-multi-stats"]["get"]
    auto_multi_post_operation = schema["paths"]["/custom-admin/testapp/product/auto-multi-stats"]["post"]

    def assert_custom_route_error_responses(operation, *, include_401=True):
        expected_statuses = {"400", "403", "404", "422"}
        if include_401:
            expected_statuses.add("401")
        for status in expected_statuses:
            assert _response_schema_ref(operation, status) == "#/components/schemas/ErrorResponse"

    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))

    assert status_operation["operationId"] == "custom_site_status"
    assert status_operation["tags"] == ["custom.site"]
    assert status_operation["security"] == [{"SessionAuthIsStaff": []}]
    assert _response_schema_ref(status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(status_operation)
    assert decorated_status_operation["operationId"] == "custom_site_decorated_status"
    assert decorated_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(decorated_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(decorated_status_operation)
    assert auto_status_operation["operationId"] == "custom_get_auto_status"
    assert auto_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(auto_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(auto_status_operation)
    assert mapped_status_operation["operationId"] == "custom_mapped_status"
    assert mapped_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(mapped_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert _response_schema_ref(mapped_status_operation, "418") == "#/components/schemas/ErrorResponse"
    assert_custom_route_error_responses(mapped_status_operation)
    assert explicit_multi_get_operation["operationId"] == "custom_explicit_multi_status_get"
    assert explicit_multi_get_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(explicit_multi_get_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(explicit_multi_get_operation)
    assert explicit_multi_post_operation["operationId"] == "custom_explicit_multi_status_post"
    assert explicit_multi_post_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(explicit_multi_post_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(explicit_multi_post_operation)
    assert decorated_auto_status_operation["operationId"] == "custom_get_decorated_auto_status"
    assert decorated_auto_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(decorated_auto_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(decorated_auto_status_operation)
    assert token_operation["operationId"] == "custom_token_status"
    assert token_operation["tags"] == ["custom.auth"]
    assert {"PrimaryTokenAuth": []} in token_operation["security"]
    assert {"SecondaryTokenAuth": []} in token_operation["security"]
    assert _response_schema_ref(token_operation, "200") == "#/components/schemas/AuthStatusResponse"
    assert_custom_route_error_responses(token_operation)
    assert public_operation["operationId"] == "custom_public_status"
    assert public_operation["tags"] == ["custom.public"]
    assert "security" not in public_operation
    assert _response_schema_ref(public_operation, "200") == "#/components/schemas/PublicStatusResponse"
    assert "401" not in public_operation["responses"]
    assert_custom_route_error_responses(public_operation, include_401=False)
    assert stats_operation["operationId"] == "custom_product_stats"
    assert stats_operation["tags"] == ["custom.product"]
    assert stats_operation["summary"] == "Product stats"
    assert stats_operation["description"] == "Custom product statistics."
    assert _response_schema_ref(stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(stats_operation)
    assert decorated_stats_operation["operationId"] == "custom_product_decorated_stats"
    assert decorated_stats_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(decorated_stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(decorated_stats_operation)
    assert auto_stats_operation["operationId"] == "custom_get_testapp_product_auto_stats"
    assert auto_stats_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_stats_operation)
    assert auto_multi_get_operation["operationId"] == "custom_get_testapp_product_auto_multi_stats"
    assert auto_multi_get_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_multi_get_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_multi_get_operation)
    assert auto_multi_post_operation["operationId"] == "custom_post_testapp_product_auto_multi_stats"
    assert auto_multi_post_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_multi_post_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_multi_post_operation)
    assert "/custom-admin/hidden-status" not in schema["paths"]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_site_auth_accepts_ninja_auth_sequences():
    client = Client()

    assert client.get("/multi-auth-admin/whoami").status_code == 401
    assert client.get("/multi-auth-admin/openapi.json").status_code == 401
    primary = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "primary"})
    secondary = client.get("/multi-auth-admin/whoami", headers={"X-Secondary-Token": "secondary"})
    invalid = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "wrong"})
    schema_response = client.get("/multi-auth-admin/openapi.json", headers={"X-Primary-Token": "primary"})

    assert primary.status_code == 200
    assert primary.json() == {"auth": "primary"}
    assert secondary.status_code == 200
    assert secondary.json() == {"auth": "secondary"}
    assert invalid.status_code == 401
    assert schema_response.status_code == 200

    schema = schema_response.json()
    operation = schema["paths"]["/multi-auth-admin/whoami"]["get"]
    assert operation["operationId"] == "multi_auth_whoami"
    assert {"PrimaryTokenAuth": []} in operation["security"]
    assert {"SecondaryTokenAuth": []} in operation["security"]
    assert schema["components"]["securitySchemes"]["PrimaryTokenAuth"]["in"] == "header"
    assert schema["components"]["securitySchemes"]["SecondaryTokenAuth"]["name"] == "X-Secondary-Token"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_context_uses_site_customization_and_permission_hook(admin_client):
    response = admin_client.get("/context-admin/context")

    assert response.status_code == 200
    body = response.json()
    assert body["site_title"] == "Custom Context Title"
    assert body["site_header"] == "Custom Context Header"
    assert body["site_url"] == "/dashboard/"
    assert body["is_nav_sidebar_enabled"] is False
    assert body["has_permission"] is True
    assert [app["app_label"] for app in body["available_apps"]] == ["testapp"]
    assert [model["model_name"] for model in body["available_apps"][0]["models"]] == ["category"]

    locked_response = admin_client.get("/locked-context-admin/context")

    assert locked_response.status_code == 200
    assert locked_response.json()["has_permission"] is False


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_custom_form_class_drives_schema_metadata_and_validation(admin_client, sample):
    schema = admin_client.get("/custom-form-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]
    delete_operation = schema["paths"]["/custom-form-admin/testapp/product/{object_id}"]["delete"]

    assert "manual" not in create_data_schema["properties"]
    assert set(create_data_schema["required"]) == {"name", "category", "price", "stock_status"}
    assert _response_schema_ref(delete_operation, "200") == "#/components/schemas/ProductDeleteHookResponse"
    assert _response_schema_ref(delete_operation, "202") == "#/components/schemas/ProductDeleteHookResponse"

    form = admin_client.get("/custom-form-admin/testapp/product/form")
    assert form.status_code == 200
    assert form.json()["form"]["media"] == {
        "css": {
            "all": ["admin/product-name.css"],
            "print": ["/print/product-name.css"],
        },
        "js": ["admin/product-name.js", "https://cdn.example.test/product-name.js"],
    }
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["widget_attrs"]["data-admin"] == "custom"
    assert fields_by_name["name"]["attrs"]["error_messages"]["required"] == "Product name is required."
    assert fields_by_name["description"]["attrs"]["widget"] == "Textarea"
    assert fields_by_name["description"]["attrs"]["widget_attrs"]["rows"] == 2
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"

    tag_ids = list(sample.tags.values_list("pk", flat=True))
    invalid = admin_client.post(
        "/custom-form-admin/testapp/product",
        data={
            "data": {
                "name": "Forbidden",
                "category": sample.category_id,
                "tags": tag_ids,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Blocked",
            }
        },
        content_type="application/json",
    )
    assert invalid.status_code == 400
    ErrorResponse.model_validate(invalid.json())
    assert invalid.json()["errors"][0]["param"] == "name"
    assert invalid.json()["errors"][0]["message"] == ["Forbidden product name."]

    created = admin_client.post(
        "/custom-form-admin/testapp/product",
        data={
            "data": {
                "name": "Allowed",
                "category": sample.category_id,
                "tags": tag_ids,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Created through custom form",
            }
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    created_body = created.json()
    created_id = created_body["data"]["id"]
    hooked_tag = Tag.objects.get(name="Hooked")
    assert created_body["data"]["name"] == "Allowed"
    assert created_body["data"]["description"] == "Created through custom form [add:save_form] [add:save_model]"
    assert set(created_body["data"]["tags"]) == {*tag_ids, hooked_tag.pk}
    assert set(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == {*tag_ids, hooked_tag.pk}

    changed = admin_client.patch(
        f"/custom-form-admin/testapp/product/{created_id}",
        data={"data": {"description": "Changed through custom form"}},
        content_type="application/json",
    )
    assert changed.status_code == 200
    changed_body = changed.json()
    assert changed_body["data"]["description"] == "Changed through custom form [change:save_form] [change:save_model]"
    assert set(changed_body["data"]["tags"]) == {*tag_ids, hooked_tag.pk}
    assert Product.objects.get(pk=created_id).description == (
        "Changed through custom form [change:save_form] [change:save_model]"
    )

    direct_deleted = admin_client.delete(f"/custom-form-admin/testapp/product/{created_id}")
    assert direct_deleted.status_code == 200
    assert direct_deleted.json() == {
        "deleted_id": str(created_id),
        "deleted_display": "Allowed",
        "response_hook": "delete",
    }
    assert Tag.objects.filter(name=f"delete_model:{created_id}:Allowed").exists()
    assert not Product.objects.filter(pk=created_id).exists()

    bulk_product = Product.objects.create(
        name="Bulk Hooked",
        category=sample.category,
        price="4.00",
        stock_status="in_stock",
    )
    bulk_deleted = admin_client.post(
        "/custom-form-admin/testapp/product/actions",
        data={"action": "delete_selected", "selected_ids": [bulk_product.pk]},
        content_type="application/json",
    )
    assert bulk_deleted.status_code == 200
    assert Tag.objects.filter(name="delete_queryset:Bulk Hooked").exists()
    assert not Product.objects.filter(pk=bulk_product.pk).exists()


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_response_hooks_can_return_custom_status(admin_client, sample):
    schema = admin_client.get("/status-hook-admin/openapi.json").json()
    paths = schema["paths"]
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product"]["post"], "202")
        == "#/components/schemas/ProductAddHookResponse"
    )
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product/{object_id}"]["patch"], "202")
        == "#/components/schemas/ProductChangeHookResponse"
    )
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product/{object_id}"]["delete"], "202")
        == "#/components/schemas/ProductDeleteStatusHookResponse"
    )

    created = admin_client.post(
        "/status-hook-admin/testapp/product",
        data={
            "data": {
                "name": "Status Hook",
                "category": sample.category_id,
                "price": "8.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 202
    created_body = created.json()
    assert created_body["hook"] == "add"
    created_id = created_body["id"]
    assert Product.objects.filter(pk=created_id, name="Status Hook").exists()

    changed = admin_client.patch(
        f"/status-hook-admin/testapp/product/{created_id}",
        data={"data": {"description": "Custom status response"}},
        content_type="application/json",
    )

    assert changed.status_code == 202
    assert changed.json() == {
        "hook": "change",
        "id": created_id,
        "description": "Custom status response",
    }
    assert Product.objects.get(pk=created_id).description == "Custom status response"

    deleted = admin_client.delete(f"/status-hook-admin/testapp/product/{created_id}")

    assert deleted.status_code == 202
    assert deleted.json() == {"hook": "delete", "id": str(created_id), "display": "Status Hook"}
    assert not Product.objects.filter(pk=created_id).exists()


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_split_datetime_payload_uses_pydantic_and_multivalue_form_normalization(admin_client, sample):
    schema = admin_client.get("/split-datetime-admin/openapi.json").json()
    description_schema = schema["components"]["schemas"]["ProductAdminCreateData"]["properties"]["description"][
        "anyOf"
    ][0]
    assert description_schema["prefixItems"] == [
        {"format": "date", "type": "string"},
        {"format": "time", "type": "string"},
    ]

    invalid = admin_client.post(
        "/split-datetime-admin/testapp/product",
        data={
            "data": {
                "name": "Bad split time",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": ["2026-07-01", "not-a-time"],
            }
        },
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "data.description.1"

    created = admin_client.post(
        "/split-datetime-admin/testapp/product",
        data={
            "data": {
                "name": "Split window",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": ["2026-07-01", "09:30"],
            }
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    product_id = created.json()["data"]["id"]
    product = Product.objects.get(pk=product_id)
    assert product.description.startswith("2026-07-01T09:30:00")

    changed = admin_client.patch(
        f"/split-datetime-admin/testapp/product/{product_id}",
        data={"data": {"description": ["2026-07-02", "10:15"]}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    product.refresh_from_db()
    assert product.description.startswith("2026-07-02T10:15:00")


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_multivalue_payload_uses_subfield_pydantic_and_form_normalization(admin_client, sample):
    schema = admin_client.get("/multi-value-admin/openapi.json").json()
    description_schema = schema["components"]["schemas"]["ProductAdminCreateData"]["properties"]["description"][
        "anyOf"
    ][0]
    assert description_schema["prefixItems"][0]["pattern"] == "^[A-Z]{3}$"
    assert description_schema["prefixItems"][1]["minimum"] == 1
    assert description_schema["prefixItems"][1]["maximum"] == 9

    invalid = admin_client.post(
        "/multi-value-admin/testapp/product",
        data={
            "data": {
                "name": "Bad code count",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": ["abc", 4],
            }
        },
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "data.description.0"

    created = admin_client.post(
        "/multi-value-admin/testapp/product",
        data={
            "data": {
                "name": "Code counted",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": ["ABC", "4"],
            }
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    product_id = created.json()["data"]["id"]
    product = Product.objects.get(pk=product_id)
    assert product.description == "ABC:4"

    renamed = admin_client.patch(
        f"/multi-value-admin/testapp/product/{product_id}",
        data={"data": {"name": "Code counted again"}},
        content_type="application/json",
    )
    assert renamed.status_code == 200, renamed.json()
    product.refresh_from_db()
    assert product.name == "Code counted again"
    assert product.description == "ABC:4"

    changed = admin_client.patch(
        f"/multi-value-admin/testapp/product/{product_id}",
        data={"data": {"description": ["XYZ", 9]}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    product.refresh_from_db()
    assert product.description == "XYZ:9"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_temporal_payload_uses_pydantic_cleaned_python_values_for_form_binding(admin_client, sample):
    invalid = admin_client.post(
        "/temporal-admin/testapp/product",
        data={
            "data": {
                "name": "Bad temporal",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "not-a-datetime",
            }
        },
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "data.description"

    created = admin_client.post(
        "/temporal-admin/testapp/product",
        data={
            "data": {
                "name": "Temporal window",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "01/07/2026 09.30",
            }
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    product_id = created.json()["data"]["id"]
    product = Product.objects.get(pk=product_id)
    assert product.description.startswith("2026-07-01T09:30:00")

    changed = admin_client.patch(
        f"/temporal-admin/testapp/product/{product_id}",
        data={"data": {"description": "02/07/2026 10.15"}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    product.refresh_from_db()
    assert product.description.startswith("2026-07-02T10:15:00")


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_scalar_payload_normalizes_pydantic_python_values_for_form_binding(admin_client, sample):
    invalid = admin_client.post(
        "/scalar-admin/testapp/product",
        data={
            "data": {
                "name": "Bad scalar",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "homepage": "https://example.com/products",
                "host": "not-an-ip",
                "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        },
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "data.host"

    created = admin_client.post(
        "/scalar-admin/testapp/product",
        data={
            "data": {
                "name": "Scalar payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "homepage": "https://example.com/products",
                "host": "2001:db8::1",
                "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
            }
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.json()
    product_id = created.json()["data"]["id"]
    product = Product.objects.get(pk=product_id)
    assert product.description == "https://example.com/products|2001:db8::1|550e8400-e29b-41d4-a716-446655440000"

    changed = admin_client.patch(
        f"/scalar-admin/testapp/product/{product_id}",
        data={
            "data": {
                "homepage": "https://example.com/changed",
                "host": "192.0.2.10",
                "tracking_id": "550e8400-e29b-41d4-a716-446655440001",
            }
        },
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    product.refresh_from_db()
    assert product.description == "https://example.com/changed|192.0.2.10|550e8400-e29b-41d4-a716-446655440001"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_disabled_form_fields_are_optional_in_write_schema(admin_client, sample):
    schema = admin_client.get("/disabled-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "name" in create_data_schema["properties"]
    assert "name" not in create_data_schema["required"]
    assert set(create_data_schema["required"]) == {"category", "price", "stock_status"}

    form = admin_client.get("/disabled-admin/testapp/product/form")
    assert form.status_code == 200
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["required"] is True
    assert fields_by_name["name"]["attrs"]["disabled"] is True
    assert fields_by_name["name"]["attrs"]["initial"] == "Server named product"
    assert_no_rendered_field_attrs(fields_by_name["name"]["attrs"])

    created = admin_client.post(
        "/disabled-admin/testapp/product",
        data={
            "data": {
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 201, created.json()
    product = Product.objects.get(pk=created.json()["data"]["id"])
    assert product.name == "Server named product"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_formfield_hooks_drive_schema_metadata_validation_and_persistence(admin_client, sample):
    allowed_category = Category.objects.create(name="Allowed Cameras")

    schema = admin_client.get("/custom-formfield-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]
    assert set(create_data_schema["required"]) == {"name", "category", "price", "stock_status"}

    form = admin_client.get("/custom-formfield-admin/testapp/product/form")
    assert form.status_code == 200
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["help_text"] == "Name from formfield_for_dbfield."
    assert_no_rendered_field_attrs(fields_by_name["name"]["attrs"])
    assert fields_by_name["name"]["attrs"]["min_length"] == 3
    name_validator_details = fields_by_name["name"]["attrs"]["validator_details"]
    assert {
        "class": "MinLengthValidator",
        "code": "min_length",
        "limit_value": 3,
        "message": "",
    } in name_validator_details
    assert fields_by_name["description"]["attrs"]["help_text"] == "Describe the product carefully."
    assert fields_by_name["description"]["attrs"]["widget"] == "Textarea"
    assert fields_by_name["description"]["attrs"]["widget_attrs"]["data-hook"] == "override"
    assert fields_by_name["description"]["attrs"]["widget_attrs"]["rows"] == 4
    assert_no_rendered_field_attrs(fields_by_name["description"]["attrs"])
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [["in_stock", "Available"]]
    assert fields_by_name["stock_status"]["attrs"]["widget"] == "RadioSelect"
    assert fields_by_name["stock_status"]["attrs"]["admin_widget"] == "radio"
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
    assert fields_by_name["stock_status"]["attrs"]["radio"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "stock_status",
        "orientation": VERTICAL,
    }
    category_choices = fields_by_name["category"]["attrs"]["choices"]
    assert [str(allowed_category.pk), "Allowed Cameras"] in category_choices
    assert [str(sample.category_id), "Cameras"] not in category_choices

    invalid_name = admin_client.post(
        "/custom-formfield-admin/testapp/product",
        data={
            "data": {
                "name": "No",
                "category": allowed_category.pk,
                "price": "9.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )
    assert invalid_name.status_code == 422
    assert invalid_name.json()["errors"][0]["param"] == "data.name"

    invalid_category = admin_client.post(
        "/custom-formfield-admin/testapp/product",
        data={
            "data": {
                "name": "Allowed Product",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )
    assert invalid_category.status_code == 400
    ErrorResponse.model_validate(invalid_category.json())
    assert invalid_category.json()["errors"][0]["param"] == "category"

    created = admin_client.post(
        "/custom-formfield-admin/testapp/product",
        data={
            "data": {
                "name": "Allowed Product",
                "category": allowed_category.pk,
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Hooked description",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 201
    created_id = created.json()["data"]["id"]
    product = Product.objects.get(pk=created_id)
    assert product.category == allowed_category
    assert product.description == "Hooked description"


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


def test_changelist_facets_and_date_hierarchy(admin_client, sample):
    alpha_date = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=alpha_date)
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 2, 20, 10, 0, tzinfo=UTC))
    Product.objects.create(
        name="Tripod",
        category=sample.category,
        price="6.00",
        description="Stable",
        created_at=datetime(2025, 3, 5, 10, 0, tzinfo=UTC),
    )

    response = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["show_facets"] is True
    assert body["config"]["facets_optional"] is True
    assert body["config"]["add_facets_query_string"] is None
    assert body["config"]["remove_facets_query_string"] == "?"
    assert body["config"]["has_filters"] is True
    assert body["config"]["has_active_filters"] is False
    assert body["config"]["clear_all_filters_query_string"] is None
    stock_filter = next(item for item in body["config"]["filters"] if item["parameter_name"] == "stock_status__exact")
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["In Stock"] == 2
    assert body["config"]["date_hierarchy"]["level"] == "year"
    assert body["config"]["date_hierarchy"]["field_type"] == "DateTimeField"
    assert body["config"]["date_hierarchy"]["timezone"] == timezone.get_current_timezone_name()
    assert body["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert body["config"]["date_hierarchy"]["back_query_string"] is None
    assert [choice["value"] for choice in body["config"]["date_hierarchy"]["choices"]] == [2024, 2025]

    by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2024&_facets=1")
    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == 2
    assert by_year.json()["config"]["has_active_filters"] is True
    assert by_year.json()["config"]["clear_all_filters_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["remove_facets_query_string"] == "?created_at__year=2024"
    assert by_year.json()["config"]["date_hierarchy"]["level"] == "month"
    assert by_year.json()["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["date_hierarchy"]["back_query_string"] == "?_facets=1"
    assert [choice["value"] for choice in by_year.json()["config"]["date_hierarchy"]["choices"]] == [1, 2]

    by_month = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1")
    assert by_month.status_code == 200
    assert by_month.json()["config"]["result_count"] == 1
    assert by_month.json()["config"]["date_hierarchy"]["level"] == "day"
    assert by_month.json()["config"]["date_hierarchy"]["clear_query_string"] == "?"
    assert by_month.json()["config"]["date_hierarchy"]["back_query_string"] == "?created_at__year=2024"
    assert by_month.json()["config"]["date_hierarchy"]["choices"][0]["value"] == 15

    by_day = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1&created_at__day=15")
    assert by_day.status_code == 200
    assert by_day.json()["config"]["date_hierarchy"]["back_query_string"] == (
        "?created_at__year=2024&created_at__month=1"
    )
    assert by_day.json()["config"]["date_hierarchy"]["choices"][0]["selected"] is True

    bad_day = admin_client.get(
        "/admin-api/testapp/product?created_at__year=2024&created_at__month=2&created_at__day=31"
    )
    assert bad_day.status_code == 400
    assert bad_day.json()["errors"] == [{"message": "Invalid day.", "param": "created_at__day"}]


def test_changelist_date_hierarchy_selects_lowest_useful_initial_level(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 2, 20, 10, 0, tzinfo=UTC))

    same_year = admin_client.get("/admin-api/testapp/product")

    assert same_year.status_code == 200
    same_year_hierarchy = same_year.json()["config"]["date_hierarchy"]
    assert same_year_hierarchy["level"] == "month"
    assert same_year_hierarchy["params"] == {"year": 2024}
    assert same_year_hierarchy["clear_query_string"] == "?"
    assert same_year_hierarchy["back_query_string"] == "?"
    assert [(choice["value"], choice["query_string"]) for choice in same_year_hierarchy["choices"]] == [
        (1, "?created_at__year=2024&created_at__month=1"),
        (2, "?created_at__year=2024&created_at__month=2"),
    ]

    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 1, 20, 10, 0, tzinfo=UTC))
    same_month = admin_client.get("/admin-api/testapp/product")

    assert same_month.status_code == 200
    same_month_hierarchy = same_month.json()["config"]["date_hierarchy"]
    assert same_month_hierarchy["level"] == "day"
    assert same_month_hierarchy["params"] == {"year": 2024, "month": 1}
    assert same_month_hierarchy["clear_query_string"] == "?"
    assert same_month_hierarchy["back_query_string"] == "?created_at__year=2024"
    assert [(choice["value"], choice["query_string"]) for choice in same_month_hierarchy["choices"]] == [
        (15, "?created_at__year=2024&created_at__month=1&created_at__day=15"),
        (20, "?created_at__year=2024&created_at__month=1&created_at__day=20"),
    ]


def test_changelist_date_hierarchy_uses_active_timezone(admin_client, sample):
    boundary = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
    Product.objects.all().update(created_at=boundary)

    with timezone.override("America/Los_Angeles"):
        response = admin_client.get("/admin-api/testapp/product")
        by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2023")
        request = RequestFactory().get("/admin-api/testapp/product?created_at__year=2023")
        request.user = get_user_model().objects.get(username="admin")
        changelist = ChangeList(request, site.get_model_admin(Product))
        start, end = changelist.date_hierarchy_bounds({"year": 2023})

    assert response.status_code == 200
    hierarchy = response.json()["config"]["date_hierarchy"]
    assert hierarchy["field_type"] == "DateTimeField"
    assert hierarchy["timezone"] == "America/Los_Angeles"
    assert hierarchy["level"] == "day"
    assert hierarchy["params"] == {"year": 2023, "month": 12}
    assert [choice["value"] for choice in hierarchy["choices"]] == [31]

    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == Product.objects.count()
    by_year_hierarchy = by_year.json()["config"]["date_hierarchy"]
    assert by_year_hierarchy["timezone"] == "America/Los_Angeles"
    assert by_year_hierarchy["level"] == "month"
    assert [choice["value"] for choice in by_year_hierarchy["choices"]] == [12]
    assert start.isoformat() == "2023-01-01T00:00:00-08:00"
    assert end.isoformat() == "2024-01-01T00:00:00-08:00"


def test_changelist_date_hierarchy_handles_max_year_bounds(admin_client, sample):
    year = admin_client.get("/admin-api/testapp/product?created_at__year=9999")
    day = admin_client.get("/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31")

    assert year.status_code == 200
    assert year.json()["config"]["result_count"] == 0
    assert day.status_code == 200
    assert day.json()["config"]["result_count"] == 0

    request = RequestFactory().get(
        "/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31"
    )
    request.user = get_user_model().objects.get(username="admin")
    changelist = ChangeList(request, site.get_model_admin(Product))
    start, end = changelist.date_hierarchy_bounds({"year": 9999, "month": 12, "day": 31})

    assert start.isoformat().startswith("9999-12-31T00:00:00")
    assert end is None


def test_changelist_show_facets_modes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.NEVER)
    never = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert never.status_code == 200
    assert never.json()["config"]["show_facets"] is False
    assert never.json()["config"]["facets_optional"] is False
    assert never.json()["config"]["add_facets_query_string"] is None
    assert never.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in never.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert all(choice["count"] is None for choice in stock_filter["choices"])

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.ALWAYS)
    always = admin_client.get("/admin-api/testapp/product")
    assert always.status_code == 200
    assert always.json()["config"]["show_facets"] is True
    assert always.json()["config"]["facets_optional"] is False
    assert always.json()["config"]["add_facets_query_string"] is None
    assert always.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in always.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1


def test_changelist_date_hierarchy_supports_relation_paths(admin_client, sample):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"
        ordering = ("title",)

    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2025, 2, 20, 10, 0, tzinfo=UTC))
    ProductImage.objects.create(product=beta, title="Beta image")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(ProductImage, RelatedDateHierarchyImageAdmin)
    model_admin = admin_site.get_model_admin(ProductImage)
    user = get_user_model().objects.get(username="admin")

    request = RequestFactory().get("/admin-api/testapp/productimage")
    request.user = user
    changelist = ChangeList(request, model_admin)

    description = changelist.date_hierarchy_description()
    assert description["field"] == "product__created_at"
    assert description["field_type"] == "DateTimeField"
    assert description["timezone"] == timezone.get_current_timezone_name()
    assert description["level"] == "year"
    assert [choice["value"] for choice in description["choices"]] == [2024, 2025]

    by_year_request = RequestFactory().get("/admin-api/testapp/productimage?product__created_at__year=2024")
    by_year_request.user = user
    by_year = ChangeList(by_year_request, model_admin)
    by_year_description = by_year.date_hierarchy_description()

    assert by_year.result_count == 1
    assert by_year_description["level"] == "month"
    assert by_year_description["choices"][0]["query_string"] == (
        "?product__created_at__year=2024&product__created_at__month=1"
    )


def test_date_field_list_filter_uses_bounded_ranges(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("created_at",))
    monkeypatch.setattr(
        "django_ninja_admin.filters.timezone.now",
        lambda: datetime(2024, 1, 15, 12, 0, tzinfo=UTC),
    )
    Product.objects.all().update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.create(
        name="Future",
        category=sample.category,
        price="7.00",
        created_at=datetime(2024, 2, 1, 10, 0, tzinfo=UTC),
    )

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    date_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "created at")
    this_month = next(choice for choice in date_filter["choices"] if choice["display"] == "This month")
    assert "created_at__gte=" in this_month["query_string"]
    assert "created_at__lt=" in this_month["query_string"]

    filtered = admin_client.get(f"/admin-api/testapp/product{this_month['query_string']}")
    assert filtered.status_code == 200
    assert filtered.json()["config"]["result_count"] == 2
    assert [row["cells"]["name"] for row in filtered.json()["rows"]] == ["Alpha", "Beta"]

    stale_response = admin_client.get(
        "/admin-api/testapp/product",
        {
            "created_at__gte": "2023-01-01 00:00:00+00:00",
            "created_at__lt": "2023-02-01 00:00:00+00:00",
        },
    )
    stale_filter = next(item for item in stale_response.json()["config"]["filters"] if item["title"] == "created at")
    stale_any_date = next(choice for choice in stale_filter["choices"] if choice["display"] == "Any date")
    stale_this_month = next(choice for choice in stale_filter["choices"] if choice["display"] == "This month")
    assert stale_any_date["query_string"] == "?"
    assert "2023" not in stale_this_month["query_string"]


def test_changelist_allows_local_field_lookup_suffixes(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?price__gte=10")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert response.json()["rows"][0]["cells"]["name"] == "Alpha"


@isolate_apps("tests.testapp")
def test_lookup_allowed_honors_limit_choices_to_relation_lookups(db):
    class LimitedCategory(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "testapp"

    class LimitedProduct(models.Model):
        category = models.ForeignKey(LimitedCategory, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class LimitedImage(models.Model):
        product = models.ForeignKey(
            LimitedProduct,
            on_delete=models.CASCADE,
            limit_choices_to={"category__name": "Cameras"},
        )

        class Meta:
            app_label = "testapp"

    class LimitedProductAdmin(ModelAdmin):
        list_filter = ()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(LimitedProduct, LimitedProductAdmin)
    model_admin = admin_site.get_model_admin(LimitedProduct)
    request = RequestFactory().get("/admin-api/testapp/limitedproduct")

    assert model_admin.lookup_allowed("category__name", "Cameras", request) is True
    assert model_admin.lookup_allowed("category__name", "Accessories", request) is False


def test_changelist_rejects_bad_lookup_page_and_ordering(admin_client, sample):
    bad_lookup = admin_client.get("/admin-api/testapp/product?category__name=Cameras")
    assert bad_lookup.status_code == 400

    bad_filter_value = admin_client.get("/admin-api/testapp/product?category__id__exact=not-an-id")
    assert bad_filter_value.status_code == 400
    assert bad_filter_value.json()["errors"] == [{"message": "Invalid lookup value.", "param": "category__id__exact"}]

    bad_direct_value = admin_client.get("/admin-api/testapp/product?price=not-a-decimal")
    assert bad_direct_value.status_code == 400
    assert bad_direct_value.json()["errors"] == [{"message": "Invalid lookup value.", "param": "price"}]

    bad_page = admin_client.get("/admin-api/testapp/product?page=0")
    assert bad_page.status_code == 404

    bad_ordering = admin_client.get("/admin-api/testapp/product?o=999")
    assert bad_ordering.status_code == 400

    bad_date_hierarchy = admin_client.get("/admin-api/testapp/product?created_at__month=2")
    assert bad_date_hierarchy.status_code == 400


def test_forms_create_update_delete_and_history(admin_client, sample):
    category = sample.category
    form = admin_client.get("/admin-api/testapp/product/form")
    assert form.status_code == 200
    assert form.json()["form"]["model"] == "testapp.product"
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["error_messages"]["required"] == "This field is required."
    assert fields_by_name["name"]["attrs"]["localize"] is False
    assert fields_by_name["name"]["attrs"]["is_localized"] is False
    assert fields_by_name["category"]["attrs"]["related_model"] == "testapp.category"
    assert fields_by_name["category"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["category"]["attrs"]["related_model_name"] == "category"
    assert fields_by_name["category"]["attrs"]["related_object_name"] == "Category"
    assert fields_by_name["category"]["attrs"]["related_verbose_name"] == "category"
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "id"
    assert fields_by_name["category"]["attrs"]["to_field_class"] == "BigAutoField"
    assert fields_by_name["category"]["attrs"]["to_field_internal_type"] == "BigAutoField"
    assert fields_by_name["category"]["attrs"]["to_field_attname"] == "id"
    assert fields_by_name["category"]["attrs"]["model_field_name"] == "category"
    assert fields_by_name["category"]["attrs"]["model_field_class"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["internal_type"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["attname"] == "category_id"
    assert fields_by_name["category"]["attrs"]["column"] == "category_id"
    assert fields_by_name["category"]["attrs"]["blank"] is False
    assert fields_by_name["category"]["attrs"]["null"] is False
    assert fields_by_name["category"]["attrs"]["editable"] is True
    assert fields_by_name["price"]["attrs"]["max_digits"] == 8
    assert fields_by_name["price"]["attrs"]["decimal_places"] == 2
    assert fields_by_name["price"]["attrs"]["blank"] is False
    assert fields_by_name["price"]["attrs"]["unique"] is False
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]
    assert fields_by_name["stock_status"]["attrs"]["default"] == "in_stock"
    assert fields_by_name["stock_status"]["attrs"]["admin_widget"] == "radio"
    assert fields_by_name["stock_status"]["attrs"]["add_id_index"] is True
    assert fields_by_name["stock_status"]["attrs"]["checked_attribute"] == {"checked": True}
    assert_no_rendered_field_attrs(fields_by_name["stock_status"]["attrs"])
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
    assert fields_by_name["stock_status"]["attrs"]["radio"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "stock_status",
        "orientation": VERTICAL,
    }
    assert fields_by_name["category"]["attrs"]["admin_widget"] == "autocomplete"
    assert fields_by_name["category"]["attrs"]["autocomplete"] == {
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
        "url": "/admin-api/autocomplete",
        "query": {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
        },
    }
    assert fields_by_name["description"]["attrs"]["blank"] is True
    assert fields_by_name["description"]["attrs"]["null"] is False
    assert fields_by_name["description"]["attrs"]["prepopulated_from"] == ["name"]
    assert fields_by_name["description"]["attrs"]["prepopulated"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "description",
        "sources": [{"field_name": "name", "label": "name", "internal_type": "CharField"}],
    }
    assert fields_by_name["manual"]["type"] == "FileField"
    assert fields_by_name["manual"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["manual"]["attrs"]["blank"] is True
    assert fields_by_name["manual"]["attrs"]["upload_to"] == "manuals"
    assert fields_by_name["manual"]["attrs"]["clearable_file_input"] is True
    assert fields_by_name["manual"]["attrs"]["initial_text"] == "Currently"
    assert fields_by_name["manual"]["attrs"]["input_text"] == "Change"
    assert fields_by_name["manual"]["attrs"]["clear_checkbox_label"] == "Clear"
    assert_no_rendered_field_attrs(fields_by_name["manual"]["attrs"])
    assert fields_by_name["photo"]["type"] == "ImageField"
    assert fields_by_name["photo"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["photo"]["attrs"]["image"] is True
    assert fields_by_name["photo"]["attrs"]["accepted_content_types"] == ["image/*"]
    assert_no_rendered_field_attrs(fields_by_name["photo"]["attrs"])
    assert fields_by_name["photo"]["attrs"]["upload_to"] == "photos"
    assert fields_by_name["photo"]["attrs"]["width_field"] == "photo_width"
    assert fields_by_name["photo"]["attrs"]["height_field"] == "photo_height"
    assert fields_by_name["tags"]["type"] == "ModelMultipleChoiceField"
    assert fields_by_name["tags"]["attrs"]["related_model"] == "testapp.tag"
    assert fields_by_name["tags"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["tags"]["attrs"]["related_model_name"] == "tag"
    assert fields_by_name["tags"]["attrs"]["related_object_name"] == "Tag"
    assert fields_by_name["tags"]["attrs"]["model_field_name"] == "tags"
    assert fields_by_name["tags"]["attrs"]["model_field_class"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["internal_type"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["multiple"] is True
    assert fields_by_name["tags"]["attrs"]["blank"] is True
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"
    assert fields_by_name["tags"]["attrs"]["filtered_select"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "tags",
        "direction": "horizontal",
        "is_stacked": False,
        "verbose_name": "tags",
        "related_model": "testapp.tag",
        "related_app_label": "testapp",
        "related_model_name": "tag",
        "related_verbose_name": "tag",
        "related_verbose_name_plural": "tags",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
    }
    assert form.json()["form"]["filter_horizontal"] == ["tags"]

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    assert change_form.status_code == 200
    change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
    assert change_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert set(change_fields_by_name["tags"]["attrs"]["value"]) == set(sample.tags.values_list("pk", flat=True))
    assert {option["text"] for option in change_fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }
    assert change_fields_by_name["manual"]["attrs"]["current_file"] == {
        "name": "manuals/alpha.pdf",
        "url": "/media/manuals/alpha.pdf",
    }
    assert fields_by_name["upper_name"]["attrs"]["read_only"] is True

    created = admin_client.post(
        "/admin-api/testapp/product",
        data={
            "data": {
                "name": "Gamma",
                "category": category.pk,
                "tags": list(sample.tags.values_list("pk", flat=True)),
                "price": "9.00",
                "stock_status": "in_stock",
                "description": "Created",
            },
            "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}},
        },
        content_type="application/json",
    )
    assert created.status_code == 201
    created_id = created.json()["data"]["id"]
    assert set(created.json()["data"]["tags"]) == set(sample.tags.values_list("pk", flat=True))
    assert set(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == set(
        sample.tags.values_list("pk", flat=True)
    )
    assert ProductImage.objects.filter(product_id=created_id, title="Side").exists()
    addition_entry = LogEntry.objects.get(object_id=str(created_id), action_flag=ADDITION)
    addition_message = json.loads(addition_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in addition_message

    changed = admin_client.patch(
        f"/admin-api/testapp/product/{created_id}",
        data={"data": {"price": "11.00"}},
        content_type="application/json",
    )
    assert changed.status_code == 200
    assert Product.objects.get(pk=created_id).price == 11
    price_change_entry = LogEntry.objects.filter(object_id=str(created_id), action_flag=CHANGE).latest("action_time")
    assert json.loads(price_change_entry.change_message) == [{"changed": {"fields": ["Price"]}}]

    tag = Tag.objects.create(name="Clearance")
    retagged = admin_client.patch(
        f"/admin-api/testapp/product/{created_id}",
        data={"data": {"tags": [tag.pk]}},
        content_type="application/json",
    )
    assert retagged.status_code == 200
    assert retagged.json()["data"]["tags"] == [tag.pk]
    assert list(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == [tag.pk]
    change_entry = LogEntry.objects.filter(object_id=str(created_id), action_flag=CHANGE).latest("action_time")
    assert json.loads(change_entry.change_message) == [{"changed": {"fields": ["Tags"]}}]

    history = admin_client.get("/admin-api/history?app_label=testapp&model=product")
    assert history.status_code == 200
    assert history.json()["pagination"]["count"] >= 2
    latest_history = history.json()["results"][0]
    assert latest_history["change_message"] == [{"changed": {"fields": ["Tags"]}}]
    assert latest_history["change_message_text"] == "Changed Tags."

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")
    assert deleted.status_code == 204


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


def test_direct_update_skips_empty_change_log(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    save_calls = []
    original_save_model = product_admin.save_model

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

    monkeypatch.setattr(product_admin, "save_model", save_model)
    before = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count()
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"name": sample.name}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert save_calls == [sample.pk]
    assert LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count() == before
    sample.refresh_from_db()
    assert sample.name == "Alpha"


def test_form_description_uses_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def get_extra(self, request, obj=None, **kwargs):
        return 2 if obj is not None else 4

    def get_min_num(self, request, obj=None, **kwargs):
        return 1

    def get_max_num(self, request, obj=None, **kwargs):
        return 5

    monkeypatch.setattr(ProductImageInline, "get_extra", get_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", get_min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", get_max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["extra"] == 2
    assert inline["min_num"] == 1
    assert inline["max_num"] == 5
    assert inline["fieldset_layout"] == [
        {
            "name": None,
            "classes": [],
            "description": None,
            "fields": ["id", "product", "title"],
            "rows": [{"fields": ["id"]}, {"fields": ["product"]}, {"fields": ["title"]}],
        }
    ]
    assert inline["formset_prefix"] == "images"
    assert inline["total_form_count"] == 3
    assert inline["initial_form_count"] == 1
    management_fields = {field["name"]: field for field in inline["management_form"]}
    assert_no_rendered_field_attrs(management_fields["TOTAL_FORMS"]["attrs"])
    assert management_fields["TOTAL_FORMS"]["attrs"]["value"] == 3
    assert_no_rendered_field_attrs(management_fields["INITIAL_FORMS"]["attrs"])
    assert management_fields["INITIAL_FORMS"]["attrs"]["value"] == 1
    assert management_fields["MIN_NUM_FORMS"]["attrs"]["value"] == 1
    assert management_fields["MAX_NUM_FORMS"]["attrs"]["value"] == 5
    assert [row["prefix"] for row in inline["formset_row_metadata"]] == ["images-0", "images-1", "images-2"]
    assert [row["is_initial"] for row in inline["formset_row_metadata"]] == [True, False, False]
    assert inline["formset_row_metadata"][0]["object_id"] == str(ProductImage.objects.get(product=sample).pk)
    title_values = [
        next(field for field in row if field["name"] == "title")["attrs"].get("value") for row in inline["formset"]
    ]
    assert title_values == ["Front", None, None]
    first_row_fields = {field["name"]: field for field in inline["formset"][0]}
    assert_no_rendered_field_attrs(first_row_fields["title"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["id"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["DELETE"]["attrs"])
    assert_no_rendered_field_attrs(first_row_fields["product"]["attrs"])
    assert inline["empty_form_prefix"] == "images-__prefix__"
    empty_form_fields = {field["name"]: field for field in inline["empty_form"]}
    assert_no_rendered_field_attrs(empty_form_fields["title"]["attrs"])

    add_response = admin_client.get("/admin-api/testapp/product/form")

    assert add_response.status_code == 200
    add_inline = next(item for item in add_response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert add_inline["extra"] == 4
    assert add_inline["min_num"] == 1
    assert add_inline["formset_prefix"] == "images"
    assert add_inline["total_form_count"] == 5
    assert add_inline["initial_form_count"] == 0
    assert len(add_inline["formset"]) == 5
    assert [row["prefix"] for row in add_inline["formset_row_metadata"]] == [
        "images-0",
        "images-1",
        "images-2",
        "images-3",
        "images-4",
    ]
    assert all(row["is_initial"] is False for row in add_inline["formset_row_metadata"])


def test_form_description_rejects_invalid_dynamic_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def negative_extra(self, request, obj=None, **kwargs):
        return -1

    monkeypatch.setattr(ProductImageInline, "get_extra", negative_extra)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'extra' must not be negative.",
            "param": "inlines.testapp.productimage.extra",
        }
    ]

    def zero_extra(self, request, obj=None, **kwargs):
        return 0

    def min_num(self, request, obj=None, **kwargs):
        return 3

    def max_num(self, request, obj=None, **kwargs):
        return 1

    monkeypatch.setattr(ProductImageInline, "get_extra", zero_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'min_num' must not exceed 'max_num'.",
            "param": "inlines.testapp.productimage.min_num",
        }
    ]


def test_inline_descriptions_use_formfield_hooks_and_media(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class InlineTitleWidget(forms.TextInput):
        class Media:
            css = {"all": ("admin/inline-title.css",)}
            js = ("admin/inline-title.js",)

    original_formfield_for_dbfield = ProductImageInline.formfield_for_dbfield

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "title":
            kwargs["help_text"] = "Inline title from formfield hook."
            kwargs["widget"] = InlineTitleWidget(attrs={"data-inline": "title"})
        return original_formfield_for_dbfield(self, db_field, request, **kwargs)

    monkeypatch.setattr(ProductImageInline, "formfield_for_dbfield", formfield_for_dbfield)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["media"] == {
        "css": {"all": ["admin/inline-title.css"]},
        "js": ["admin/inline-title.js"],
    }
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["help_text"] == "Inline title from formfield hook." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-inline"] == "title" for field in title_fields)


def test_inline_admin_form_class_drives_metadata_and_validation(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class ProductImageAdminForm(forms.ModelForm):
        title = forms.CharField(
            max_length=100,
            required=False,
            help_text="Inline title from custom form.",
            widget=forms.TextInput(attrs={"data-form": "inline"}),
        )

        class Meta:
            model = ProductImage
            fields = ("title",)

        def clean_title(self):
            title = self.cleaned_data["title"]
            if title == "Forbidden":
                raise forms.ValidationError("Forbidden inline title.")
            return title

    monkeypatch.setattr(ProductImageInline, "form_class", ProductImageAdminForm)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["required"] is False for field in title_fields)
    assert all(field["attrs"]["help_text"] == "Inline title from custom form." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-form"] == "inline" for field in title_fields)
    inline_admin = ProductImageInline(Product, NinjaAdminSite(include_auth=False))
    row_schema = inline_admin.get_inline_row_schema(RequestFactory().get("/"), sample)
    assert "title" not in row_schema.model_json_schema().get("required", [])

    invalid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Forbidden"}]}}},
        content_type="application/json",
    )

    assert invalid.status_code == 400
    assert "Forbidden inline title." in str(invalid.json()["errors"])
    assert not ProductImage.objects.filter(product=sample, title="Forbidden").exists()

    valid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Allowed inline"}]}}},
        content_type="application/json",
    )

    assert valid.status_code == 200
    assert ProductImage.objects.filter(product=sample, title="Allowed inline").exists()


def test_disabled_inline_form_fields_are_optional_in_write_schema(db, sample):
    class DisabledProductImageForm(forms.ModelForm):
        title = forms.CharField(disabled=True, initial="Generated image title", max_length=100)

        class Meta:
            model = ProductImage
            fields = ("title",)

    class DisabledProductImageInline(TabularInline):
        model = ProductImage
        form_class = DisabledProductImageForm

    inline_admin = DisabledProductImageInline(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    field = inline_admin.get_form_fields_description(request, None)[0]
    row_schema = inline_admin.get_inline_row_schema(request, sample)

    assert field["name"] == "title"
    assert field["attrs"]["required"] is True
    assert field["attrs"]["disabled"] is True
    assert field["attrs"]["initial"] == "Generated image title"
    assert "title" not in row_schema.model_json_schema().get("required", [])


def test_readonly_display_fields_include_values_and_display_metadata(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def callable_summary(obj):
        return f"{obj.name}:{obj.stock_status}"

    callable_summary.short_description = "Callable summary"
    monkeypatch.setattr(
        product_admin,
        "readonly_fields",
        ("upper_name", "has_description", "subtitle", callable_summary),
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


def test_history_filters_by_permission_and_params(staff_client, sample):
    actor = get_user_model().objects.create_user("history-actor", password="pw", is_staff=True)
    product_ct = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    category_ct = ContentType.objects.get_for_model(Category, for_concrete_model=False)
    product_addition = LogEntry.objects.create(
        user=actor,
        content_type=product_ct,
        object_id=str(sample.pk),
        object_repr=str(sample),
        action_flag=ADDITION,
        change_message=json.dumps([{"added": {}}]),
    )
    LogEntry.objects.create(
        user=actor,
        content_type=product_ct,
        object_id=str(sample.pk),
        object_repr=str(sample),
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
    )
    LogEntry.objects.create(
        user=actor,
        content_type=category_ct,
        object_id=str(sample.category_id),
        object_repr=str(sample.category),
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
    )

    client = staff_client("view_product")
    global_history = client.get("/admin-api/history")
    assert global_history.status_code == 200
    assert {item["content_type_id"] for item in global_history.json()["results"]} == {product_ct.pk}
    assert global_history.json()["pagination"]["page"] == 1
    assert global_history.json()["pagination"]["per_page"] == 20
    assert global_history.json()["pagination"]["count"] == 2
    assert {item["change_message_text"] for item in global_history.json()["results"]} == {"Added.", "Changed Name."}
    assert {
        (
            item["model"],
            item["app_label"],
            item["model_name"],
            item["model_verbose_name"],
            item["model_verbose_name_plural"],
        )
        for item in global_history.json()["results"]
    } == {("testapp.product", "testapp", "product", "product", "products")}
    assert {(item["detail_url"], item["change_form_url"]) for item in global_history.json()["results"]} == {
        (f"/admin-api/testapp/product/{sample.pk}", f"/admin-api/testapp/product/{sample.pk}/form")
    }

    paged = client.get("/admin-api/history", {"per_page": 1, "page": 2})
    assert paged.status_code == 200
    assert paged.json()["pagination"] == {
        "count": 2,
        "num_pages": 2,
        "page": 2,
        "per_page": 1,
        "has_next": False,
        "has_previous": True,
        "more": False,
    }
    assert len(paged.json()["results"]) == 1

    filtered = client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": ADDITION},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["results"]] == [product_addition.pk]
    assert filtered.json()["results"][0]["change_message_text"] == "Added."

    forbidden = client.get("/admin-api/history", {"app_label": "testapp", "model": "category"})
    assert forbidden.status_code == 403

    missing_app_label = client.get("/admin-api/history", {"model": "product"})
    assert missing_app_label.status_code == 400
    assert missing_app_label.json()["errors"] == [
        {"message": "app_label is required when model is provided.", "param": "app_label"}
    ]

    bad_page = client.get("/admin-api/history", {"page": 0})
    assert bad_page.status_code == 404

    bad_page_size = client.get("/admin-api/history", {"per_page": 0})
    assert bad_page_size.status_code == 400
    assert bad_page_size.json()["errors"] == [{"message": "Invalid page size.", "param": "per_page"}]

    excessive_page_size = client.get("/admin-api/history", {"per_page": 101})
    assert excessive_page_size.status_code == 400
    assert excessive_page_size.json()["errors"] == [{"message": "Page size cannot exceed 100.", "param": "per_page"}]


def test_history_uses_queryset_pagination_for_global_permissions(admin_client, sample, monkeypatch):
    actor = get_user_model().objects.create_user("history-query-actor", password="pw", is_staff=True)
    product_admin = site.get_model_admin(Product)
    product_ct = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    for index in range(3):
        LogEntry.objects.create(
            user=actor,
            content_type=product_ct,
            object_id=str(sample.pk),
            object_repr=f"{sample}:{index}",
            action_flag=CHANGE,
            change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
        )

    monkeypatch.setattr(product_admin, "get_object", lambda *args, **kwargs: pytest.fail("history fetched objects"))

    response = admin_client.get("/admin-api/history", {"app_label": "testapp", "model": "product", "per_page": 1})

    assert response.status_code == 200
    assert response.json()["pagination"] == {
        "count": 3,
        "num_pages": 3,
        "page": 1,
        "per_page": 1,
        "has_next": True,
        "has_previous": False,
        "more": True,
    }
    assert len(response.json()["results"]) == 1


def test_history_filters_object_level_permissions(admin_client, sample, monkeypatch):
    actor = get_user_model().objects.create_user("history-object-actor", password="pw", is_staff=True)
    product_admin = site.get_model_admin(Product)
    product_ct = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    hidden = Product.objects.create(name="Hidden history", category=sample.category, price="5.00")
    visible_entry = LogEntry.objects.create(
        user=actor,
        content_type=product_ct,
        object_id=str(sample.pk),
        object_repr=str(sample),
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
    )
    LogEntry.objects.create(
        user=actor,
        content_type=product_ct,
        object_id=str(hidden.pk),
        object_repr=str(hidden),
        action_flag=CHANGE,
        change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
    )

    def has_object_permission(request, obj=None):
        return obj is None or obj.pk != hidden.pk

    monkeypatch.setattr(product_admin, "has_view_permission", has_object_permission)
    monkeypatch.setattr(product_admin, "has_change_permission", has_object_permission)

    response = admin_client.get("/admin-api/history", {"app_label": "testapp", "model": "product"})

    assert response.status_code == 200
    assert response.json()["pagination"]["count"] == 1
    assert [item["id"] for item in response.json()["results"]] == [visible_entry.pk]
    assert response.json()["results"][0]["object_repr"] == "Alpha"

    hidden_response = admin_client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(hidden.pk)},
    )

    assert hidden_response.status_code == 200
    assert hidden_response.json()["pagination"]["count"] == 0
    assert hidden_response.json()["results"] == []


def test_history_object_level_permissions_are_page_scoped(admin_client, sample, monkeypatch):
    actor = get_user_model().objects.create_user("history-page-actor", password="pw", is_staff=True)
    product_admin = site.get_model_admin(Product)
    product_ct = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    products = [
        Product.objects.create(
            name=f"History page {index}",
            category=sample.category,
            price="5.00",
        )
        for index in range(5)
    ]
    now = timezone.now()
    for index, product in enumerate(products):
        LogEntry.objects.create(
            user=actor,
            content_type=product_ct,
            object_id=str(product.pk),
            object_repr=str(product),
            action_flag=CHANGE,
            action_time=now + timedelta(seconds=index),
            change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
        )
    objects_by_id = {str(product.pk): product for product in products}
    fetched_object_ids = []

    def has_object_permission(request, obj=None):
        return True

    def get_object(request, object_id, from_field=None):
        fetched_object_ids.append(str(object_id))
        if len(fetched_object_ids) > 2:
            pytest.fail("history fetched more objects than the requested page")
        return objects_by_id[str(object_id)]

    monkeypatch.setattr(product_admin, "has_view_permission", has_object_permission)
    monkeypatch.setattr(product_admin, "has_change_permission", has_object_permission)
    monkeypatch.setattr(product_admin, "get_object", get_object)

    response = admin_client.get("/admin-api/history", {"app_label": "testapp", "model": "product", "per_page": 2})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert len(fetched_object_ids) == 2
    assert response.json()["pagination"] == {
        "count": 2,
        "num_pages": 1,
        "page": 1,
        "per_page": 2,
        "has_next": False,
        "has_previous": False,
        "more": False,
    }


def test_form_description_marks_raw_id_and_filter_vertical_widget_modes(db, sample):
    user = get_user_model().objects.create_user("widget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    request.user = user

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
        "related_model": "testapp.tag",
        "related_app_label": "testapp",
        "related_model_name": "tag",
        "related_verbose_name": "tag",
        "related_verbose_name_plural": "tags",
        "to_field_name": "id",
        "to_field_class": "BigAutoField",
        "to_field_internal_type": "BigAutoField",
        "to_field_attname": "id",
    }
    assert {option["text"] for option in fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }


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


def test_file_field_can_be_cleared_with_null_payload(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"manual": None}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["manual"] is None
    sample.refresh_from_db()
    assert sample.manual.name == ""

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
    assert detail.status_code == 200
    assert detail.json()["manual"] is None

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    manual_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "manual")
    assert "current_file" not in manual_attrs

    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    assert json.loads(change_entry.change_message) == [{"changed": {"fields": ["Manual"]}}]


def test_file_and_image_fields_reject_non_string_json_payloads(admin_client, sample):
    invalid_manual = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"manual": {"name": "manual.txt"}}},
        content_type="application/json",
    )
    invalid_photo = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"photo": ["photo.png"]}},
        content_type="application/json",
    )

    assert invalid_manual.status_code == 422
    assert invalid_manual.json()["errors"][0]["param"] == "data.manual"
    assert invalid_photo.status_code == 422
    assert invalid_photo.json()["errors"][0]["param"] == "data.photo"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_multipart_file_parts_satisfy_required_file_schema_fields(admin_client, sample, tmp_path):
    schema = admin_client.get("/required-file-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "manual" in create_data_schema["required"]
    assert create_data_schema["properties"]["manual"] == {"title": "Manual", "type": "string"}
    multipart_schema = schema["paths"]["/required-file-admin/testapp/product/multipart"]["post"]["requestBody"][
        "content"
    ]["multipart/form-data"]["schema"]
    assert multipart_schema["required"] == ["data", "manual"]

    form = admin_client.get("/required-file-admin/testapp/product/form")
    manual_attrs = next(field["attrs"] for field in form.json()["form"]["fields"] if field["name"] == "manual")
    assert manual_attrs["allowed_extensions"] == ["pdf", "txt"]
    assert manual_attrs["accepted_extensions"] == [".pdf", ".txt"]

    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Invalid manual extension",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.exe", b"required", content_type="application/octet-stream"),
            },
        )

        assert invalid.status_code == 400
        ErrorResponse.model_validate(invalid.json())
        assert invalid.json()["errors"][0]["param"] == "manual"
        assert not Product.objects.filter(name="Invalid manual extension").exists()

        created = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Required manual",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.txt", b"required", content_type="text/plain"),
            },
        )

        assert created.status_code == 201, created.json()
        product = Product.objects.get(pk=created.json()["data"]["id"])
        assert product.manual.name.startswith("manuals/required")
        assert (tmp_path / product.manual.name).read_bytes() == b"required"
        assert created.json()["data"]["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }


def test_file_field_can_be_uploaded_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        created = admin_client.post(
            "/admin-api/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Upload",
                        "category": sample.category_id,
                        "tags": list(sample.tags.values_list("pk", flat=True)),
                        "price": "7.00",
                        "stock_status": "in_stock",
                        "description": "Created with upload",
                    }
                ),
                "manual": SimpleUploadedFile("manual.txt", b"hello", content_type="text/plain"),
            },
        )

        assert created.status_code == 201
        created_body = created.json()["data"]
        product = Product.objects.get(pk=created_body["id"])
        assert product.manual.name.startswith("manuals/manual")
        assert (tmp_path / product.manual.name).read_bytes() == b"hello"
        assert created_body["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }

        changed = admin_client.patch(
            f"/admin-api/testapp/product/{product.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Updated with upload"}),
                    "manual": SimpleUploadedFile("replacement.txt", b"updated", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200
        product.refresh_from_db()
        assert product.description == "Updated with upload"
        assert product.manual.name.startswith("manuals/replacement")
        assert (tmp_path / product.manual.name).read_bytes() == b"updated"
        change_entry = LogEntry.objects.filter(object_id=str(product.pk), action_flag=CHANGE).latest("action_time")
        changed_fields = json.loads(change_entry.change_message)[0]["changed"]["fields"]
        assert set(changed_fields) == {"Description", "Manual"}


def test_image_field_validates_and_uploads_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Invalid image upload"}),
                    "photo": SimpleUploadedFile("not-image.txt", b"not an image", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert invalid.status_code == 400
        invalid_body = invalid.json()
        ErrorResponse.model_validate(invalid_body)
        assert invalid_body["errors"][0]["param"] == "photo"
        assert Product.objects.get(pk=sample.pk).photo.name == ""

        uploaded = _uploaded_png("cover.png", size=(2, 3))
        changed = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Image uploaded"}),
                    "photo": uploaded,
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200, changed.json()
        sample.refresh_from_db()
        assert sample.description == "Image uploaded"
        assert sample.photo.name.startswith("photos/cover")
        assert sample.photo_width == 2
        assert sample.photo_height == 3
        assert (tmp_path / sample.photo.name).exists()
        assert changed.json()["data"]["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
        assert detail.status_code == 200
        assert detail.json()["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        photo_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "photo")
        assert photo_attrs["current_file"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        cleared = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}",
            data={"data": {"photo": None}},
            content_type="application/json",
        )

        assert cleared.status_code == 200, cleared.json()
        assert cleared.json()["data"]["photo"] is None
        sample.refresh_from_db()
        assert sample.photo.name == ""
        assert sample.photo_width is None
        assert sample.photo_height is None
        cleared_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        cleared_photo_attrs = next(
            field["attrs"] for field in cleared_form.json()["form"]["fields"] if field["name"] == "photo"
        )
        assert "current_file" not in cleared_photo_attrs
        clear_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
        assert json.loads(clear_entry.change_message) == [{"changed": {"fields": ["Photo"]}}]


def test_file_field_metadata_handles_storage_without_public_url(admin_client, sample, monkeypatch):
    manual_field = Product._meta.get_field("manual")
    monkeypatch.setattr(manual_field, "storage", Storage())

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")

    assert detail.status_code == 200
    assert detail.json()["manual"] == {"name": "manuals/alpha.pdf", "url": None}

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    manual_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "manual")

    assert change_form.status_code == 200
    assert manual_attrs["current_file"] == {"name": "manuals/alpha.pdf", "url": None}
    assert manual_attrs["clearable_file_input"] is True
    assert_no_rendered_field_attrs(manual_attrs)


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
            {"additionalProperties": True, "type": "object"},
            {"items": {}, "type": "array"},
            {"type": "string"},
            {"type": "integer"},
            {"type": "number"},
            {"type": "boolean"},
            {"type": "null"},
        ],
    }

    assert output_json_schema["properties"]["payload"] == {
        **json_value_schema,
        "title": "Payload",
    }
    assert output_json_schema["properties"]["optional_payload"] == {
        **json_value_schema,
        "default": None,
        "title": "Optional Payload",
    }
    assert write_json_schema["properties"]["payload"] == {
        **json_value_schema,
        "title": "Payload",
    }
    assert write_json_schema["properties"]["optional_payload"] == {
        **json_value_schema,
        "default": None,
        "title": "Optional Payload",
    }

    output_schema.model_validate({"id": 1, "payload": {"nested": [1, "two"]}, "optional_payload": None})
    output_schema.model_validate({"id": 1, "payload": ["nested", 1], "optional_payload": True})
    write_schema.model_validate({"payload": {"nested": [1, "two"]}, "optional_payload": "value"})
    with pytest.raises(PydanticValidationError):
        output_schema.model_validate({"id": 1, "payload": object(), "optional_payload": None})
    with pytest.raises(PydanticValidationError):
        write_schema.model_validate({"payload": object(), "optional_payload": None})
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


def test_multipart_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/multipart",
        data={
            "data": json.dumps(
                {
                    "category": sample.category_id,
                    "price": "7.00",
                    "stock_status": "in_stock",
                }
            ),
            "manual": SimpleUploadedFile("manual.txt", b"hello", content_type="text/plain"),
        },
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "data.name"


def test_direct_delete_returns_protected_object_details(admin_client, sample):
    ProductReview.objects.create(product=sample, note="Pinned review")

    response = admin_client.delete(f"/admin-api/testapp/product/{sample.pk}")

    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["param"] == "object_id"
    assert_sample_deleted_objects_tree(body)
    assert body["protected"] == ["Pinned review"]
    assert body["model_count"]["testapp.product"] == 1
    assert Product.objects.filter(pk=sample.pk).exists()


def test_direct_delete_returns_permission_needed_details(staff_client, sample):
    client = staff_client("delete_category")

    response = client.delete(f"/admin-api/testapp/category/{sample.category_id}")

    assert response.status_code == 403
    body = response.json()
    assert body["errors"][0]["param"] == "object_id"
    assert body["perms_needed"] == ["product"]
    assert Category.objects.filter(pk=sample.category_id).exists()


def test_direct_delete_checks_object_level_permission_before_collecting(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    sample_pk = sample.pk
    calls = []

    def has_delete_permission(request, obj=None):
        calls.append(obj.pk if obj is not None else None)
        if len(calls) == 1:
            return obj is not None and obj.pk == sample_pk
        return True

    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.delete(f"/admin-api/testapp/product/{sample.pk}")

    assert response.status_code == 204
    assert calls[0] == sample_pk
    assert not Product.objects.filter(pk=sample_pk).exists()


def test_direct_delete_denies_object_level_permission(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_delete_permission(request, obj=None):
        return obj is None

    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.delete(f"/admin-api/testapp/product/{sample.pk}")

    assert response.status_code == 403
    assert response.json() == {"errors": [{"message": "Permission denied.", "param": "non_field_errors"}]}
    assert Product.objects.filter(pk=sample.pk).exists()


def test_model_routes_validate_to_field(admin_client, sample):
    allowed = admin_client.get(f"/admin-api/testapp/category/{sample.category_id}?_to_field=id")
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "Cameras"

    bad_category_field = admin_client.get(f"/admin-api/testapp/category/{sample.category.name}?_to_field=name")
    assert bad_category_field.status_code == 400
    assert bad_category_field.json()["errors"] == [
        {"message": "The field 'name' cannot be referenced.", "param": "_to_field"}
    ]

    bad_product_field = admin_client.delete(f"/admin-api/testapp/product/{sample.category_id}?_to_field=category")
    assert bad_product_field.status_code == 400
    assert Product.objects.filter(pk=sample.pk).exists()

    bad_update_field = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}?_to_field=category",
        data={"data": {"name": "Nope"}},
        content_type="application/json",
    )
    assert bad_update_field.status_code == 400
    sample.refresh_from_db()
    assert sample.name == "Alpha"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_changelist_routes_support_allowed_to_field(admin_client):
    Category.objects.create(name="Cameras", slug="cameras")

    response = admin_client.get("/slug-autocomplete-admin/testapp/category?_to_field=slug&o=1")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["to_field"] == "slug"
    assert body["config"]["object_id_field"] == "slug"
    row = body["rows"][0]
    assert row["id"] == "cameras"
    assert row["detail_url"] == "/slug-autocomplete-admin/testapp/category/cameras?_to_field=slug"
    assert row["change_form_url"] == "/slug-autocomplete-admin/testapp/category/cameras/form?_to_field=slug"
    assert row["delete_url"] == "/slug-autocomplete-admin/testapp/category/cameras?_to_field=slug"

    detail = admin_client.get(row["detail_url"])
    assert detail.status_code == 200
    assert detail.json()["name"] == "Cameras"

    bad_field = admin_client.get("/slug-autocomplete-admin/testapp/category?_to_field=name")
    assert bad_field.status_code == 400
    assert bad_field.json()["errors"] == [{"message": "The field 'name' cannot be referenced.", "param": "_to_field"}]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_bulk_update_supports_changelist_to_field_row_identity(admin_client):
    category = Category.objects.create(name="Cameras", slug="cameras")

    changelist = admin_client.get("/slug-editable-admin/testapp/category?_to_field=slug&o=2")

    assert changelist.status_code == 200
    body = changelist.json()
    assert body["config"]["to_field"] == "slug"
    assert body["config"]["object_id_field"] == "slug"
    assert body["rows"][0]["id"] == "cameras"
    assert body["list_editing_rows"][0]["pk"] == "cameras"
    assert body["list_editing_rows"][0]["pk_name"] == "slug"

    response = admin_client.put(
        "/slug-editable-admin/testapp/category/bulk?_to_field=slug",
        data={"data": [{"pk": "cameras", "name": "Updated Cameras"}]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["0"]["name"] == "Updated Cameras"
    category.refresh_from_db()
    assert category.name == "Updated Cameras"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_bulk_update_uses_changelist_form_hook(admin_client, sample):
    changelist = admin_client.get("/bulk-form-admin/testapp/product")

    assert changelist.status_code == 200
    fields_by_name = {field["name"]: field for row in changelist.json()["list_editing_rows"] for field in row["fields"]}
    assert list(fields_by_name) == ["stock_status"]
    assert fields_by_name["stock_status"]["attrs"]["help_text"] == "Bulk-only status field."
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [["out_of_stock", "Bulk unavailable"]]

    invalid = admin_client.put(
        "/bulk-form-admin/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "in_stock"}]},
        content_type="application/json",
    )

    assert invalid.status_code == 400
    ErrorResponse.model_validate(invalid.json())
    assert invalid.json()["errors"][0]["param"] == "data.0.stock_status"
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"

    updated = admin_client.put(
        "/bulk-form-admin/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "out_of_stock"}]},
        content_type="application/json",
    )

    assert updated.status_code == 200, updated.json()
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_update_routes_support_allowed_to_field(admin_client):
    category = Category.objects.create(name="Cameras", slug="cameras")

    response = admin_client.patch(
        "/slug-autocomplete-admin/testapp/category/cameras?_to_field=slug",
        data={"data": {"name": "Updated Cameras"}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Updated Cameras"
    category.refresh_from_db()
    assert category.name == "Updated Cameras"


def test_create_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product",
        data={"data": {"category": sample.category_id, "price": "9.00", "stock_status": "in_stock"}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "data.name"


def test_mutation_payload_rejects_unknown_parent_data_fields(admin_client, sample):
    created = admin_client.post(
        "/admin-api/testapp/product",
        data={
            "data": {
                "name": "Ignored field",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "unknown": "silently bad",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 422
    assert created.json()["errors"][0]["param"] == "data.unknown"
    assert not Product.objects.filter(name="Ignored field").exists()

    changed = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"unknown": "silently bad"}},
        content_type="application/json",
    )

    assert changed.status_code == 422
    assert changed.json()["errors"][0]["param"] == "data.unknown"


def test_inline_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{}]}}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_inline_multivalue_payload_uses_pydantic_and_formset_normalization(admin_client, sample):
    product = Product.objects.create(
        name="Inline coded",
        category=sample.category,
        price="4.00",
        stock_status="in_stock",
    )

    invalid = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["abc", 4]}]}}},
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title.0"
    assert not ProductImage.objects.filter(product=product).exists()

    created = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["ABC", "4"]}]}}},
        content_type="application/json",
    )
    assert created.status_code == 200, created.json()
    image = ProductImage.objects.get(product=product)
    assert image.title == "ABC:4"
    assert created.json()["inlines"]["testapp.productimage"]["add"][0]["title"] == "ABC:4"

    changed = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": ["XYZ", 9]}]}}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    image.refresh_from_db()
    assert image.title == "XYZ:9"
    assert changed.json()["inlines"]["testapp.productimage"]["change"][0]["title"] == "XYZ:9"


def test_actions_bulk_autocomplete_and_view_on_site(admin_client, sample):
    action = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert action.status_code == 200
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"

    bulk = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "in_stock"}]},
        content_type="application/json",
    )
    assert bulk.status_code == 200
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"

    autocomplete = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Cam",
        },
    )
    assert autocomplete.status_code == 200
    assert autocomplete.json()["results"][0]["text"] == "Cameras"

    content_type = ContentType.objects.get_for_model(Product)
    onsite = admin_client.get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert onsite.status_code == 200
    assert onsite.json() == {"url": f"http://example.com/products/{sample.pk}/"}


def test_autocomplete_honors_remote_get_search_fields_hook(admin_client, sample, monkeypatch):
    category_admin = site.get_model_admin(Category)
    monkeypatch.setattr(category_admin, "search_fields", ())
    monkeypatch.setattr(category_admin, "get_search_fields", lambda request: ("name",))

    response = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Cam",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"id": str(sample.category_id), "text": "Cameras"}]


def test_view_on_site_supports_callable_external_urls(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    content_type = ContentType.objects.get_for_model(Product, for_concrete_model=False)

    monkeypatch.setattr(product_admin, "view_on_site", lambda obj: f"https://example.test/products/{obj.pk}/")
    absolute = admin_client.get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert absolute.status_code == 200
    assert absolute.json() == {"url": f"https://example.test/products/{sample.pk}/"}

    monkeypatch.setattr(product_admin, "view_on_site", lambda obj: f"//assets.example.test/products/{obj.pk}/")
    protocol_relative = admin_client.get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert protocol_relative.status_code == 200
    assert protocol_relative.json() == {"url": f"//assets.example.test/products/{sample.pk}/"}


def test_view_on_site_falls_back_to_request_host_when_site_is_missing(admin_client, sample):
    with override_settings(ALLOWED_HOSTS=["admin.testserver"]):
        Site.objects.filter(pk=1).delete()
        content_type = ContentType.objects.get_for_model(Product, for_concrete_model=False)

        response = admin_client.get(
            f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}",
            HTTP_HOST="admin.testserver",
        )

        assert response.status_code == 200
        assert response.json() == {"url": f"http://admin.testserver/products/{sample.pk}/"}


def test_autocomplete_paginates_and_supports_many_to_many_source_fields(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "autocomplete_fields", ("category", "tags"))
    Tag.objects.bulk_create(Tag(name=f"Tag {index:02d}") for index in range(25))

    first_page = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "page": 1,
        },
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["results"]) == 20
    assert first_page.json()["pagination"] == {
        "count": 25,
        "num_pages": 2,
        "page": 1,
        "per_page": 20,
        "has_next": True,
        "has_previous": False,
        "more": True,
    }

    second_page = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "page": 2,
        },
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["results"]) == 5
    assert second_page.json()["pagination"] == {
        "count": 25,
        "num_pages": 2,
        "page": 2,
        "per_page": 20,
        "has_next": False,
        "has_previous": True,
        "more": False,
    }
    assert all(result["text"].startswith("Tag ") for result in second_page.json()["results"])

    bad_page = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "page": 0,
        },
    )
    assert bad_page.status_code == 404


def test_autocomplete_uses_remote_model_admin_paginator_hook(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    tag_admin = site.get_model_admin(Tag)
    monkeypatch.setattr(product_admin, "autocomplete_fields", ("tags",))
    Tag.objects.bulk_create(Tag(name=f"Tag {index:02d}") for index in range(3))
    calls = {}

    def get_paginator(request, queryset, per_page, orphans=0, allow_empty_first_page=True):
        calls["path"] = request.path
        calls["model"] = queryset.model
        calls["is_queryset"] = isinstance(queryset, models.QuerySet)
        calls["per_page"] = per_page
        calls["orphans"] = orphans
        calls["allow_empty_first_page"] = allow_empty_first_page
        return Paginator(
            queryset,
            per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    monkeypatch.setattr(tag_admin, "get_paginator", get_paginator)

    response = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
        },
    )

    assert response.status_code == 200
    assert calls == {
        "path": "/admin-api/autocomplete",
        "model": Tag,
        "is_queryset": True,
        "per_page": 20,
        "orphans": 0,
        "allow_empty_first_page": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_autocomplete_uses_remote_related_to_field(admin_client):
    Category.objects.create(name="Cameras", slug="cameras")
    Category.objects.create(name="Accessories", slug="accessories")
    link = CategorySlugLink.objects.create(name="Camera link", category_id="cameras")
    source_model_name = CategorySlugLink._meta.model_name

    form = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink/form")
    assert form.status_code == 200
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "slug"
    assert fields_by_name["category"]["attrs"]["to_field_class"] == "SlugField"
    assert fields_by_name["category"]["attrs"]["to_field_internal_type"] == "SlugField"
    assert fields_by_name["category"]["attrs"]["to_field_attname"] == "slug"
    assert fields_by_name["category"]["attrs"]["autocomplete"] == {
        "app_label": "testapp",
        "model_name": source_model_name,
        "field_name": "category",
        "related_model": "testapp.category",
        "related_app_label": "testapp",
        "related_model_name": "category",
        "related_object_name": "Category",
        "related_verbose_name": "category",
        "related_verbose_name_plural": "categorys",
        "to_field_name": "slug",
        "to_field_class": "SlugField",
        "to_field_internal_type": "SlugField",
        "to_field_attname": "slug",
        "multiple": False,
        "url": "/slug-autocomplete-admin/autocomplete",
        "query": {
            "app_label": "testapp",
            "model_name": source_model_name,
            "field_name": "category",
        },
    }

    openapi = admin_client.get("/slug-autocomplete-admin/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()
    components = schema["components"]["schemas"]
    assert components["CategorySlugLinkAdminCreateData"]["properties"]["category"] == {
        "maxLength": 100,
        "pattern": r"^[-a-zA-Z0-9_]+\z",
        "title": "Category",
        "type": "string",
    }
    assert components["CategorySlugLinkAdminOut"]["properties"]["category_id"] == {
        "maxLength": 100,
        "pattern": r"^[-a-zA-Z0-9_]+\z",
        "title": "Category Id",
        "type": "string",
    }
    create_example = schema["paths"]["/slug-autocomplete-admin/testapp/categorysluglink"]["post"]["requestBody"][
        "content"
    ]["application/json"]["examples"]["create"]["value"]["data"]
    assert create_example["category"] == "example"

    detail = admin_client.get(f"/slug-autocomplete-admin/testapp/categorysluglink/{link.pk}")
    assert detail.status_code == 200
    assert detail.json()["category_id"] == "cameras"
    assert detail.json()["category_label"] == "Cameras"

    response = admin_client.get(
        "/slug-autocomplete-admin/autocomplete",
        {
            "app_label": "testapp",
            "model_name": source_model_name,
            "field_name": "category",
            "term": "Cam",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"id": "cameras", "text": "Cameras"}]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_related_list_filters_use_remote_to_field_values(admin_client, monkeypatch):
    from tests.custom_urls import slug_autocomplete_site

    Category.objects.create(name="Cameras", slug="cameras")
    Category.objects.create(name="Accessories", slug="accessories")
    Category.objects.create(name="Unused", slug="unused")
    CategorySlugLink.objects.create(name="Camera link", category_id="cameras")
    CategorySlugLink.objects.create(name="Accessory link", category_id="accessories")
    link_admin = slug_autocomplete_site.get_model_admin(CategorySlugLink)

    monkeypatch.setattr(link_admin, "list_filter", ("category",))
    response = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink")

    assert response.status_code == 200
    category_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in category_filter["choices"]}
    assert choices_by_display["Cameras"]["query_string"] == "?category__slug__exact=cameras"
    assert choices_by_display["Accessories"]["query_string"] == "?category__slug__exact=accessories"
    assert choices_by_display["Unused"]["query_string"] == "?category__slug__exact=unused"

    filtered = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink?category__slug__exact=cameras")

    assert filtered.status_code == 200
    assert [row["cells"]["name"] for row in filtered.json()["rows"]] == ["Camera link"]
    filtered_category_filter = next(
        item for item in filtered.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    assert (
        next(choice for choice in filtered_category_filter["choices"] if choice["display"] == "Cameras")["selected"]
        is True
    )

    monkeypatch.setattr(link_admin, "list_filter", (("category", RelatedOnlyFieldListFilter),))
    related_only = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink")

    assert related_only.status_code == 200
    related_only_filter = next(
        item for item in related_only.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    related_only_choices = {choice["display"]: choice for choice in related_only_filter["choices"]}
    assert {"Cameras", "Accessories"}.issubset(related_only_choices)
    assert "Unused" not in related_only_choices
    assert related_only_choices["Cameras"]["query_string"] == "?category__slug__exact=cameras"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_autocomplete_applies_source_field_limit_choices_to(admin_client):
    public = Category.objects.create(name="Public Cameras", slug="public-cameras")
    Category.objects.create(name="Private Cameras", slug="private-cameras")
    link = CategoryLimitedLink.objects.create(name="Limited", category=public)
    source_model_name = CategoryLimitedLink._meta.model_name

    add_form = admin_client.get("/slug-autocomplete-admin/testapp/categorylimitedlink/form")
    assert add_form.status_code == 200
    add_fields_by_name = {field["name"]: field for field in add_form.json()["form"]["fields"]}
    category_attrs = add_fields_by_name["category"]["attrs"]
    assert category_attrs["limit_choices_to"] == {"slug__startswith": "public"}
    assert category_attrs["to_field_name"] == "id"
    assert category_attrs["to_field_class"] == "BigAutoField"
    assert category_attrs["to_field_internal_type"] == "BigAutoField"
    assert category_attrs["to_field_attname"] == "id"
    assert category_attrs["multiple"] is False
    assert category_attrs["autocomplete"] == {
        "app_label": "testapp",
        "model_name": source_model_name,
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
        "url": "/slug-autocomplete-admin/autocomplete",
        "query": {
            "app_label": "testapp",
            "model_name": source_model_name,
            "field_name": "category",
        },
    }

    change_form = admin_client.get(f"/slug-autocomplete-admin/testapp/categorylimitedlink/{link.pk}/form")
    assert change_form.status_code == 200
    change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
    assert change_fields_by_name["category"]["attrs"]["value"] == public.pk
    assert change_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(public.pk), "text": "Public Cameras"}
    ]

    openapi = admin_client.get("/slug-autocomplete-admin/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()
    components = schema["components"]["schemas"]
    assert components["CategoryLimitedLinkAdminCreateData"]["properties"]["category"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "title": "Category",
        "type": "integer",
    }
    assert components["CategoryLimitedLinkAdminOut"]["properties"]["category_id"] == {
        "maximum": 9223372036854775807,
        "minimum": -9223372036854775808,
        "title": "Category Id",
        "type": "integer",
    }

    detail = admin_client.get(f"/slug-autocomplete-admin/testapp/categorylimitedlink/{link.pk}")
    assert detail.status_code == 200
    assert detail.json()["category_id"] == public.pk
    assert detail.json()["category_label"] == "Public Cameras"

    response = admin_client.get(
        "/slug-autocomplete-admin/autocomplete",
        {
            "app_label": "testapp",
            "model_name": source_model_name,
            "field_name": "category",
            "term": "Cam",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"id": str(public.pk), "text": "Public Cameras"}]


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


def test_autocomplete_filters_object_level_view_permissions(admin_client, sample, monkeypatch):
    category_admin = site.get_model_admin(Category)
    hidden = Category.objects.create(name="Hidden")

    def has_view_permission(request, obj=None):
        return obj is None or obj.pk != hidden.pk

    monkeypatch.setattr(category_admin, "has_view_permission", has_view_permission)

    response = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"id": str(sample.category_id), "text": "Cameras"}]
    assert response.json()["pagination"] == {
        "count": 1,
        "num_pages": 1,
        "page": 1,
        "per_page": 20,
        "has_next": False,
        "has_previous": False,
        "more": False,
    }


def test_autocomplete_object_level_permissions_are_page_scoped(admin_client, sample, monkeypatch):
    category_admin = site.get_model_admin(Category)
    Category.objects.bulk_create(Category(name=f"Paged Category {index:02d}") for index in range(25))
    checked_object_ids = []

    def has_view_permission(request, obj=None):
        if obj is not None:
            checked_object_ids.append(obj.pk)
            if len(checked_object_ids) > 20:
                pytest.fail("autocomplete checked more objects than the requested page")
        return True

    monkeypatch.setattr(category_admin, "has_view_permission", has_view_permission)

    response = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Paged",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 20
    assert len(checked_object_ids) == 20
    assert response.json()["pagination"] == {
        "count": 20,
        "num_pages": 1,
        "page": 1,
        "per_page": 20,
        "has_next": False,
        "has_previous": False,
        "more": False,
    }


def test_actions_use_filtered_changelist_queryset(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/actions?stock_status__exact=out_of_stock",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert response.status_code == 200
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"


def test_custom_actions_check_object_level_permissions(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_change_permission(request, obj=None):
        return obj is None

    monkeypatch.setattr(product_admin, "has_change_permission", has_change_permission)

    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["errors"] == [{"message": "Permission denied.", "param": "selected_ids"}]
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"


def test_actions_support_custom_return_values_empty_selection_and_select_across(admin_client, sample):
    empty_selection = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "report_names", "selected_ids": []},
        content_type="application/json",
    )
    assert empty_selection.status_code == 400
    assert empty_selection.json()["errors"][0]["param"] == "selected_ids"

    selected_only = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "report_names", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert selected_only.status_code == 200
    assert selected_only.json() == {"names": ["Alpha"]}

    select_across = admin_client.post(
        "/admin-api/testapp/product/actions?stock_status__exact=out_of_stock",
        data={"action": "report_names", "selected_ids": [sample.pk], "select_across": True},
        content_type="application/json",
    )
    assert select_across.status_code == 200
    assert select_across.json() == {"names": ["Beta"]}


def test_actions_can_return_custom_status(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductAdmin, StockStatusActionData, StockStatusActionResult

    @action(
        description="Set stock status",
        permissions=["change"],
        input_schema=StockStatusActionData,
        response_schema=StockStatusActionResult,
    )
    def status_set_stock_status(self, request, queryset, data):
        updated = queryset.update(stock_status=data.status)
        return Status(202, {"updated": updated, "status": data.status, "note": data.note})

    monkeypatch.setattr(ProductAdmin, "set_stock_status", status_set_stock_status)

    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={
            "action": "set_stock_status",
            "selected_ids": [sample.pk],
            "data": {"status": "out_of_stock", "note": "custom status"},
        },
        content_type="application/json",
    )

    assert response.status_code == 202
    assert response.json() == {"updated": 1, "status": "out_of_stock", "note": "custom status"}
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"


def test_actions_reject_invalid_selected_ids(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "report_names", "selected_ids": ["not-a-pk"]},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"] == [{"message": "Invalid selected object id.", "param": "selected_ids"}]


def test_action_input_schema_validates_and_dispatches(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={
            "action": "set_stock_status",
            "selected_ids": [sample.pk],
            "data": {"status": "out_of_stock", "note": "seasonal"},
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {"updated": 1, "status": "out_of_stock", "note": "seasonal"}
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"

    missing_data = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "set_stock_status", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert missing_data.status_code == 422
    assert missing_data.json()["errors"][0]["param"] == "data"

    unexpected_data = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "report_names", "selected_ids": [sample.pk], "data": {"status": "out_of_stock"}},
        content_type="application/json",
    )

    assert unexpected_data.status_code == 422
    assert unexpected_data.json()["errors"][0]["param"] == "data"


def test_delete_selected_returns_protected_object_details(admin_client, sample):
    ProductReview.objects.create(product=sample, note="Pinned review")

    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "delete_selected", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["param"] == "selected_ids"
    assert_sample_deleted_objects_tree(body)
    assert body["protected"] == ["Pinned review"]
    assert Product.objects.filter(pk=sample.pk).exists()


def test_delete_selected_returns_object_permission_needed_details(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_delete_permission(request, obj=None):
        return obj is None

    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "delete_selected", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert response.status_code == 403
    body = response.json()
    assert body["errors"][0]["param"] == "selected_ids"
    assert_sample_deleted_objects_tree(body)
    assert body["perms_needed"] == ["product"]
    assert body["model_count"]["testapp.product"] == 1
    assert Product.objects.filter(pk=sample.pk).exists()


def test_delete_selected_select_across_checks_filtered_object_permissions(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    beta = Product.objects.get(name="Beta")

    def has_delete_permission(request, obj=None):
        return obj is None or obj.pk != beta.pk

    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.post(
        "/admin-api/testapp/product/actions?stock_status__exact=out_of_stock",
        data={"action": "delete_selected", "selected_ids": [sample.pk], "select_across": True},
        content_type="application/json",
    )

    assert response.status_code == 403
    body = response.json()
    assert body["errors"][0]["param"] == "selected_ids"
    assert body["deleted_objects"] == ["Beta"]
    assert body["perms_needed"] == ["product"]
    assert body["model_count"]["testapp.product"] == 1
    assert Product.objects.filter(pk=sample.pk).exists()
    assert Product.objects.filter(pk=beta.pk).exists()


def test_action_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "not_a_real_action", "selected_ids": [sample.pk]},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "action"


def test_bulk_update_checks_object_level_change_permission(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_change_permission(request, obj=None):
        return obj is None

    monkeypatch.setattr(product_admin, "has_change_permission", has_change_permission)
    response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "out_of_stock"}]},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["errors"] == [{"message": "Permission denied.", "param": "data.0.pk"}]
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"


def test_bulk_update_rejects_duplicate_rows_and_non_editable_fields(admin_client, sample):
    duplicate = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={
            "data": [
                {"pk": sample.pk, "stock_status": "out_of_stock"},
                {"pk": sample.pk, "stock_status": "in_stock"},
            ]
        },
        content_type="application/json",
    )
    assert duplicate.status_code == 400
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"

    non_editable = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "price": "99.00"}]},
        content_type="application/json",
    )
    assert non_editable.status_code == 422
    sample.refresh_from_db()
    assert str(sample.price) == "12.50"


def test_bulk_update_validates_all_rows_before_saving(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={
            "data": [
                {"pk": sample.pk, "stock_status": "out_of_stock"},
                {"pk": beta.pk, "price": "99.00"},
            ]
        },
        content_type="application/json",
    )

    assert response.status_code == 422
    sample.refresh_from_db()
    beta.refresh_from_db()
    assert sample.stock_status == "in_stock"
    assert str(beta.price) == "3.00"


def test_bulk_update_is_limited_to_filtered_changelist_queryset(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    response = admin_client.put(
        "/admin-api/testapp/product/bulk?stock_status__exact=out_of_stock",
        data={
            "data": [
                {"pk": sample.pk, "stock_status": "out_of_stock"},
                {"pk": beta.pk, "stock_status": "in_stock"},
            ]
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"] == [{"message": "Object not found.", "param": "data.0.pk"}]
    sample.refresh_from_db()
    beta.refresh_from_db()
    assert sample.stock_status == "in_stock"
    assert beta.stock_status == "out_of_stock"


def test_bulk_update_returns_all_server_side_row_errors(admin_client, sample):
    response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={
            "data": [
                {"pk": sample.pk, "stock_status": "archived"},
                {"pk": 999999, "stock_status": "in_stock"},
            ]
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    errors = response.json()["errors"]
    assert errors[0]["param"] == "data.0.stock_status"
    assert errors[1] == {"message": "Object not found.", "param": "data.1.pk"}
    sample.refresh_from_db()
    assert sample.stock_status == "in_stock"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_bulk_update_skips_unchanged_rows(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    beta = Product.objects.get(name="Beta")
    save_form_calls = []
    save_calls = []
    original_save_form = product_admin.save_form
    original_save_model = product_admin.save_model

    def save_form(request, form, change):
        obj = original_save_form(request, form, change)
        save_form_calls.append(obj.pk)
        return obj

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

    monkeypatch.setattr(product_admin, "save_form", save_form)
    monkeypatch.setattr(product_admin, "save_model", save_model)
    response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={
            "data": [
                {"pk": sample.pk, "stock_status": "out_of_stock"},
                {"pk": beta.pk},
            ]
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert set(response.json()["data"]) == {"0", "1"}
    assert save_form_calls == [sample.pk]
    assert save_calls == [sample.pk]
    assert LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count() == 1
    assert not LogEntry.objects.filter(object_id=str(beta.pk), action_flag=CHANGE).exists()
    sample.refresh_from_db()
    beta.refresh_from_db()
    assert sample.stock_status == "out_of_stock"
    assert beta.stock_status == "out_of_stock"


def test_bulk_update_skips_empty_change_log_entries(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    save_calls = []
    log_calls = []
    original_save_model = product_admin.save_model
    original_log_change = product_admin.log_change

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

    def log_change(request, obj, message):
        log_calls.append((obj.pk, message))
        return original_log_change(request, obj, message)

    monkeypatch.setattr(product_admin, "save_model", save_model)
    monkeypatch.setattr(product_admin, "log_change", log_change)
    monkeypatch.setattr(product_admin, "construct_change_message", lambda request, form: [])

    response = admin_client.put(
        "/admin-api/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "out_of_stock"}]},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert save_calls == [sample.pk]
    assert log_calls == []
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()
    sample.refresh_from_db()
    assert sample.stock_status == "out_of_stock"


def test_inline_mutations_check_inline_permissions(staff_client, sample):
    client = staff_client("change_product")
    image = ProductImage.objects.get(product=sample)

    add_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}}},
        content_type="application/json",
    )
    assert add_response.status_code == 403
    assert ProductImage.objects.filter(product=sample).count() == 1

    change_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert change_response.status_code == 403
    image.refresh_from_db()
    assert image.title == "Front"

    delete_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert delete_response.status_code == 403
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_mutations_reject_unknown_and_readonly_fields(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    unknown_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side", "bogus": "x"}]}},
        },
        content_type="application/json",
    )
    assert unknown_response.status_code == 422
    assert unknown_response.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.change.0.bogus"}
    ]

    monkeypatch.setattr(ProductImageInline, "readonly_fields", ("title",))
    readonly_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert readonly_response.status_code == 400
    assert readonly_response.json()["errors"] == [
        {
            "message": "Unknown or readonly inline field.",
            "param": "inlines.testapp.productimage.change.0.title",
        }
    ]
    image.refresh_from_db()
    assert image.title == "Front"


def test_inline_mutations_reject_unknown_inline_keys(admin_client, sample):
    unknown_inline = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.unknown": {"add": []}}},
        content_type="application/json",
    )
    assert unknown_inline.status_code == 422
    assert unknown_inline.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.unknown"}
    ]

    unknown_operation = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"replace": []}}},
        content_type="application/json",
    )
    assert unknown_operation.status_code == 422
    assert unknown_operation.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.replace"}
    ]


def test_inline_formset_enforces_max_num(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "add": [
                        {"title": "Side"},
                        {"title": "Back"},
                        {"title": "Detail"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(product=sample).count() == 1


def test_inline_formset_honors_can_delete(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    monkeypatch.setattr(ProductImageInline, "can_delete", False)
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_change_message_includes_inline_operations(admin_client, sample):
    image = sample.images.get()
    deleted_image = ProductImage.objects.create(product=sample, title="Back")
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Profile"}],
                    "add": [{"title": "Side"}],
                    "delete": [deleted_image.pk],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    inline_response = response.json()["inlines"]["testapp.productimage"]
    assert "_changed_fields" not in inline_response["change"][0]
    assert inline_response["delete"] == [deleted_image.pk]
    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    change_message = json.loads(change_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in change_message
    assert {"changed": {"name": "product image", "object": "Profile", "fields": ["title"]}} in change_message
    assert {"deleted": {"name": "product image", "object": "Back"}} in change_message
    history = admin_client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": CHANGE},
    )
    assert history.status_code == 200
    assert history.json()["results"][0]["change_message_text"] == (
        "Added product image \u201cSide\u201d. "
        "Changed title for product image \u201cProfile\u201d. "
        "Deleted product image \u201cBack\u201d."
    )


def test_inline_mutation_rejects_duplicate_and_conflicting_rows(admin_client, sample):
    image = sample.images.get()

    duplicate_change = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Front A"},
                        {"pk": image.pk, "title": "Front B"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert duplicate_change.status_code == 400
    assert ProductImage.objects.get(pk=image.pk).title == "Front"

    changed_and_deleted = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Front A"}],
                    "delete": [image.pk],
                }
            },
        },
        content_type="application/json",
    )
    assert changed_and_deleted.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk, title="Front").exists()

    duplicate_delete = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk, image.pk]}}},
        content_type="application/json",
    )
    assert duplicate_delete.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_mutation_aggregates_server_side_row_errors(admin_client, sample):
    image = sample.images.get()
    other = ProductImage.objects.create(product=sample, title="Back")

    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Profile"},
                        {"pk": other.pk, "title": "Back A"},
                        {"pk": other.pk, "title": "Back B"},
                        {"pk": 999999, "title": "Ghost"},
                    ],
                    "delete": [image.pk, 999999],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    errors = response.json()["errors"]
    assert {
        "message": "Inline object cannot be changed and deleted in the same request.",
        "param": "inlines.testapp.productimage.change.0.pk",
    } in errors
    assert {
        "message": "Duplicate inline change pk.",
        "param": "inlines.testapp.productimage.change.2.pk",
    } in errors
    assert {
        "message": "Unknown inline object.",
        "param": "inlines.testapp.productimage.change.3.pk",
    } in errors
    assert {
        "message": "Unknown inline object.",
        "param": "inlines.testapp.productimage.delete.1.pk",
    } in errors
    assert len(errors) == 4
    image.refresh_from_db()
    other.refresh_from_db()
    sample.refresh_from_db()
    assert image.title == "Front"
    assert other.title == "Back"
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_inline_mutation_rolls_back_parent_save_for_unknown_inline_object(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {"testapp.productimage": {"change": [{"pk": 999999, "title": "Ghost"}]}},
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {"message": "Unknown inline object.", "param": "inlines.testapp.productimage.change.0.pk"}
    ]
    sample.refresh_from_db()
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_schema_field_overrides_are_included_and_serialize_admin_methods(sample):
    class ProductAdminWithOverride(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None)}

        @display(description="Custom note")
        def custom_note(self, obj):
            return f"{obj.name}:{obj.stock_status}"

    admin_site = NinjaAdminSite(include_auth=False)
    model_admin = ProductAdminWithOverride(Product, admin_site)

    assert "custom_note" in model_admin.get_output_schema().model_fields
    assert model_admin.serialize_object(sample)["custom_note"] == "Alpha:in_stock"


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


def test_admin_checks_validate_schema_field_overrides(db):
    class ValidSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None), "score": (int,)}

    class BadMappingSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = [("custom_note", str)]

    class BadKeySchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {123: str}

    class BadTupleSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None, "extra")}

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSchemaOverrideProductAdmin)
    bad_mapping_site = NinjaAdminSite(include_auth=False)
    bad_mapping_site.register(Product, BadMappingSchemaOverrideProductAdmin)
    bad_key_site = NinjaAdminSite(include_auth=False)
    bad_key_site.register(Product, BadKeySchemaOverrideProductAdmin)
    bad_tuple_site = NinjaAdminSite(include_auth=False)
    bad_tuple_site.register(Product, BadTupleSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E098", "django_ninja_admin.E099", "django_ninja_admin.E100"})
    assert bad_mapping_ids == {"django_ninja_admin.E098"}
    assert bad_key_ids == {"django_ninja_admin.E099"}
    assert bad_tuple_ids == {"django_ninja_admin.E100"}


def test_admin_checks_validate_form_schema_field_overrides(db):
    class ValidFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": dict[str, int], "score": (int,)}

    class BadMappingFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = [("metadata", dict[str, int])]

    class BadKeyFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {123: str}

    class BadTupleFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": (dict[str, int], None, "extra")}

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFormSchemaOverrideProductAdmin)
    bad_mapping_site = NinjaAdminSite(include_auth=False)
    bad_mapping_site.register(Product, BadMappingFormSchemaOverrideProductAdmin)
    bad_key_site = NinjaAdminSite(include_auth=False)
    bad_key_site.register(Product, BadKeyFormSchemaOverrideProductAdmin)
    bad_tuple_site = NinjaAdminSite(include_auth=False)
    bad_tuple_site.register(Product, BadTupleFormSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E101", "django_ninja_admin.E102", "django_ninja_admin.E103"})
    assert bad_mapping_ids == {"django_ninja_admin.E101"}
    assert bad_key_ids == {"django_ninja_admin.E102"}
    assert bad_tuple_ids == {"django_ninja_admin.E103"}


def test_model_actions_require_model_access(staff_client, sample):
    client = staff_client()
    response = client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_autocomplete_requires_source_model_access_and_declared_field(admin_client, staff_client, sample):
    source_denied = staff_client("view_category").get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Cam",
        },
    )
    assert source_denied.status_code == 403

    undeclared_field = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "stock_status",
            "term": "in",
        },
    )
    assert undeclared_field.status_code == 404


def test_view_on_site_requires_model_access(staff_client, sample):
    content_type = ContentType.objects.get_for_model(Product)
    response = staff_client().get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert response.status_code == 403


def test_unauthenticated_is_rejected(db):
    response = Client().get("/admin-api/apps")
    assert response.status_code in {401, 403}


def test_admin_site_auth_contracts():
    default_site = NinjaAdminSite(include_auth=False)
    assert isinstance(default_site.auth, SessionAuthIsStaff)

    no_auth_site = NinjaAdminSite(auth=None, include_auth=False)
    assert no_auth_site.auth is None

    def custom_auth(request):
        return "token"

    custom_auth_site = NinjaAdminSite(auth=custom_auth, include_auth=False)
    assert custom_auth_site.auth is custom_auth


def test_no_drf_imports():
    import django_ninja_admin

    assert django_ninja_admin.site is not None
    assert LogEntry._meta.db_table == "django_ninja_admin_log"
