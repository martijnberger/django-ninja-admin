import json
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
from django.test import Client, RequestFactory
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import (
    VERTICAL,
    ModelAdmin,
    NinjaAdminSite,
    TabularInline,
    site,
)
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import (
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


def test_no_drf_imports():
    import django_ninja_admin

    assert django_ninja_admin.site is not None
    assert LogEntry._meta.db_table == "django_ninja_admin_log"
