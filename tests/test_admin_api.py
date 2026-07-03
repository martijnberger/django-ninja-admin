import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Annotated
from uuid import UUID

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
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
from django.test import Client, RequestFactory, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import CaptureQueriesContext, isolate_apps
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
    SimpleListFilter,
    TabularInline,
    display,
    site,
)
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import (
    Category,
    Product,
    ProductImage,
    ProductReview,
    Tag,
)


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


def test_view_on_site_requires_model_access(staff_client, sample):
    content_type = ContentType.objects.get_for_model(Product)
    response = staff_client().get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert response.status_code == 403


def test_no_drf_imports():
    import django_ninja_admin

    assert django_ninja_admin.site is not None
    assert LogEntry._meta.db_table == "django_ninja_admin_log"
