from copy import deepcopy

import pytest
from pydantic import BaseModel, ValidationError

from django_ninja_admin import ModelAdmin, NinjaAdminSite, action, site
from django_ninja_admin.schemas import (
    ActionResponse,
    ChangelistConfig,
    ChangelistResponse,
    DateHierarchyChoice,
    DateHierarchyParams,
    ErrorResponse,
    FieldAttributes,
    FormResponse,
    HistoryResponse,
    ImageFieldValue,
    Pagination,
)
from tests.testapp.models import Product


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
    assert multipart_schema["additionalProperties"] is False
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
    assert {
        "MutationPayload",
        "MutationResponse",
        "ActionPayload",
        "BulkPayload",
        "MessageResponse",
    }.isdisjoint(components)
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
    image_value_props = components["ImageFieldValue"]["properties"]
    assert image_value_props["width"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert image_value_props["height"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    ImageFieldValue.model_validate({"name": "photos/sample.png", "width": 1, "height": 1})
    with pytest.raises(ValidationError) as exc_info:
        ImageFieldValue.model_validate({"name": "photos/sample.png", "width": -1, "height": 1})
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("width",)
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
    for component_name in [
        "ProductAdminCreatePayload",
        "ProductAdminPartialUpdatePayload",
        "ProductAdminUpdatePayload",
        "ProductAdminBulkPayload",
        "ProductAdminBulkResponse",
        "ProductAdminMutationResponse",
    ]:
        assert components[component_name]["additionalProperties"] is False
    for component_name in [
        "ProductAdminDeleteSelectedActionPayload",
        "ProductAdminMarkOutOfStockActionPayload",
        "ProductAdminReportNamesActionPayload",
        "ProductAdminSetStockStatusActionPayload",
    ]:
        assert components[component_name]["additionalProperties"] is False
    partial_payload_example = components["ProductAdminPartialUpdatePayload"]["examples"][0]
    assert partial_payload_example["data"] == {"name": "example"}
    assert partial_payload_example["inlines"]["testapp.productimage"]["change"] == [{"pk": 1, "title": "example"}]
    assert partial_payload_example["inlines"]["testapp.productimage"]["delete"] == [2]
    mutation_response_schema = components["ProductAdminMutationResponse"]
    assert mutation_response_schema["required"] == ["data"]
    assert mutation_response_schema["properties"]["data"] == {"$ref": "#/components/schemas/ProductAdminMutationData"}
    assert mutation_response_schema["properties"]["inlines"]["anyOf"] == [
        {"$ref": "#/components/schemas/ProductAdminInlineResponse"},
        {"type": "null"},
    ]
    assert components["CategoryAdminInlineResponse"]["additionalProperties"] is False
    assert components["CategoryAdminInlineResponse"]["properties"] == {}
    assert components["ProductAdminInlineResponse"]["propertyNames"] == {"const": "testapp.productimage"}
    assert components["ProductAdminInlineResponse"]["additionalProperties"] == {
        "$ref": "#/components/schemas/ProductImageInlineOperationResults"
    }
    inline_result_props = components["ProductImageInlineOperationResults"]["properties"]
    assert inline_result_props["add"]["items"] == {"$ref": "#/components/schemas/ProductImageAdminOut"}
    assert inline_result_props["change"]["items"] == {"$ref": "#/components/schemas/ProductImageAdminOut"}
    assert inline_result_props["delete"]["items"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
    assert components["ProductImageInlineOperationResults"]["additionalProperties"] is False
    assert (
        components["ProductAdminMutationData"]["properties"]["name"]
        == components["ProductAdminOut"]["properties"]["name"]
    )
    assert components["ProductAdminOut"]["additionalProperties"] is False
    assert components["ProductAdminMutationData"]["additionalProperties"] is False
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
    assert components["ObjectIdentifier"] == {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "number"}]}
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
    assert components["ProductAdminBulkRow"]["properties"]["pk"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
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
    assert components["ProductImageInlineChangeRow"]["properties"]["pk"] == {
        "$ref": "#/components/schemas/ObjectIdentifier"
    }
    assert components["ProductImageInlineChangeRow"]["examples"][0] == {"pk": 1, "title": "example"}
    assert components["ProductImageInlineOperations"]["properties"]["delete"]["items"] == {
        "$ref": "#/components/schemas/ObjectIdentifier"
    }
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
    assert set_status_payload["properties"]["selected_ids"]["items"] == {
        "$ref": "#/components/schemas/ObjectIdentifier"
    }
    assert set(set_status_payload["required"]) == {"action", "data"}
    action_responses = schema_body["paths"]["/admin-api/testapp/product/actions"]["post"]["responses"]
    action_response_schema = action_responses["200"]["content"]["application/json"]["schema"]
    assert components["ActionResponse"]["additionalProperties"] is False
    assert components["ActionResponse"]["properties"]["deleted"]["anyOf"] == [
        {
            "additionalProperties": {"$ref": "#/components/schemas/NonNegativeCount"},
            "type": "object",
        },
        {"type": "null"},
    ]
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


def non_null_parameter_type(parameter):
    schema = parameter["schema"]
    variants = schema.get("anyOf", [schema])
    return [variant["type"] for variant in variants if variant.get("type") != "null"]


def non_null_parameter_schema(parameter):
    schema = parameter["schema"]
    variants = schema.get("anyOf", [schema])
    return next(variant for variant in variants if variant.get("type") != "null")


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
    list_parameters = {parameter["name"]: parameter for parameter in list_operation["parameters"]}
    assert non_null_parameter_type(list_parameters["q"]) == ["string"]
    assert non_null_parameter_type(list_parameters["o"]) == ["string"]
    assert non_null_parameter_type(list_parameters["p"]) == ["string"]
    assert non_null_parameter_type(list_parameters["page"]) == ["string"]
    assert non_null_parameter_type(list_parameters["pp"]) == ["integer"]
    assert non_null_parameter_type(list_parameters["all"]) == ["boolean"]
    assert non_null_parameter_type(list_parameters["_facets"]) == ["boolean"]
    assert non_null_parameter_type(list_parameters["_to_field"]) == ["string"]
    assert list_parameters["_to_field"]["description"] == "Use an allowed alternate object id field."
    assert list_parameters["pp"]["description"] == "Page size override from 1 to 200."
    assert (
        non_null_parameter_schema(list_parameters["o"])["pattern"]
        == r"^-?(?:\d+|[A-Za-z_][A-Za-z0-9_]*)(?:[,.]-?(?:\d+|[A-Za-z_][A-Za-z0-9_]*))*$"
    )
    assert non_null_parameter_schema(list_parameters["p"])["pattern"] == r"^(last|[1-9][0-9]*)$"
    assert non_null_parameter_schema(list_parameters["page"])["pattern"] == r"^(last|[1-9][0-9]*)$"
    assert non_null_parameter_schema(list_parameters["pp"])["minimum"] == 1
    assert non_null_parameter_schema(list_parameters["pp"])["maximum"] == 200
    for path, method in [
        ("/admin-api/testapp/product/{object_id}", "get"),
        ("/admin-api/testapp/product/{object_id}", "patch"),
        ("/admin-api/testapp/product/{object_id}", "put"),
        ("/admin-api/testapp/product/{object_id}", "delete"),
        ("/admin-api/testapp/product/{object_id}/form", "get"),
        ("/admin-api/testapp/product/{object_id}/multipart", "patch"),
        ("/admin-api/testapp/product/{object_id}/multipart", "put"),
    ]:
        object_route_parameters = {parameter["name"]: parameter for parameter in paths[path][method]["parameters"]}
        assert object_route_parameters["_to_field"]["description"] == "Use an allowed alternate object id field."
        assert non_null_parameter_type(object_route_parameters["_to_field"]) == ["string"]
    action_parameters = {
        parameter["name"]: parameter for parameter in paths["/admin-api/testapp/product/actions"]["post"]["parameters"]
    }
    assert action_parameters["_to_field"]["description"] == "Use an allowed alternate object id field."
    assert non_null_parameter_type(action_parameters["_to_field"]) == ["string"]

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
    assert components["HistoryItem"]["properties"]["id"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
    assert components["HistoryItem"]["properties"]["user_id"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
    assert components["HistoryItem"]["properties"]["content_type_id"]["anyOf"] == [
        {"$ref": "#/components/schemas/ObjectIdentifier"},
        {"type": "null"},
    ]
    assert components["HistoryItem"]["properties"]["change_message"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
    assert components["HistoryItem"]["properties"]["action_time"]["format"] == "date-time"
    assert components["HistoryItem"]["properties"]["action_flag"] == {"$ref": "#/components/schemas/HistoryActionFlag"}
    assert components["HistoryItem"]["properties"]["change_message_text"]["type"] == "string"
    assert components["HistoryItem"]["properties"]["model"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert components["HistoryItem"]["properties"]["detail_url"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert components["HistoryResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    assert components["HistoryActionFlag"] == {
        "enum": [1, 2, 3],
        "title": "HistoryActionFlag",
        "type": "integer",
    }
    history_parameters = {
        parameter["name"]: parameter for parameter in paths["/admin-api/history"]["get"]["parameters"]
    }
    assert history_parameters["app_label"]["description"] == "Optional app label to restrict history entries."
    assert history_parameters["model"]["description"] == "Optional model name to restrict history entries."
    assert history_parameters["object_id"]["description"] == "Optional object identifier to restrict history entries."
    assert history_parameters["action_flag"]["description"] == "Optional Django admin log action flag."
    assert history_parameters["o"]["description"] == "Ordering: `action_time` or `-action_time`."
    assert history_parameters["page"]["description"] == "1-based page number."
    assert history_parameters["per_page"]["description"] == "Page size from 1 to 100."
    assert history_parameters["action_flag"]["schema"]["anyOf"][0] == {"$ref": "#/components/schemas/HistoryActionFlag"}
    assert set(history_parameters["o"]["schema"]["enum"]) == {"-action_time", "action_time"}
    assert non_null_parameter_type(history_parameters["page"]) == ["integer"]
    assert non_null_parameter_type(history_parameters["per_page"]) == ["integer"]
    assert history_parameters["page"]["schema"]["minimum"] == 1
    assert history_parameters["per_page"]["schema"]["minimum"] == 1
    assert history_parameters["per_page"]["schema"]["maximum"] == 100
    history_example = components["HistoryResponse"]["examples"][0]
    assert history_example["pagination"]["per_page"] == 20
    assert history_example["pagination"]["more"] is False
    assert history_example["results"][0]["change_form_url"] == "/admin-api/shop/product/1/form"
    assert history_example["results"][0]["change_message_text"] == "Changed Name."
    HistoryResponse.model_validate(history_example)
    invalid_history_example = deepcopy(history_example)
    invalid_history_example["results"][0]["action_flag"] = 99
    with pytest.raises(ValidationError) as exc_info:
        HistoryResponse.model_validate(invalid_history_example)
    assert exc_info.value.errors()[0]["type"] == "enum"
    assert exc_info.value.errors()[0]["loc"] == ("results", 0, "action_flag")
    assert _response_schema_ref(paths["/admin-api/autocomplete"]["get"], "200") == (
        "#/components/schemas/AutocompleteResponse"
    )
    assert components["AutocompleteResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    autocomplete_parameters = {
        parameter["name"]: parameter for parameter in paths["/admin-api/autocomplete"]["get"]["parameters"]
    }
    assert autocomplete_parameters["app_label"]["description"] == "Source model app label."
    assert autocomplete_parameters["model_name"]["description"] == "Source model name."
    assert autocomplete_parameters["field_name"]["description"] == "Source relation field configured for autocomplete."
    assert (
        autocomplete_parameters["term"]["description"] == "Search term matched against the remote admin search fields."
    )
    assert autocomplete_parameters["page"]["description"] == "1-based page number."
    assert autocomplete_parameters["per_page"]["description"] == "Page size from 1 to 100."
    assert autocomplete_parameters["app_label"]["required"] is True
    assert autocomplete_parameters["model_name"]["required"] is True
    assert autocomplete_parameters["field_name"]["required"] is True
    assert non_null_parameter_type(autocomplete_parameters["page"]) == ["integer"]
    assert non_null_parameter_type(autocomplete_parameters["per_page"]) == ["integer"]
    assert autocomplete_parameters["page"]["schema"]["minimum"] == 1
    assert autocomplete_parameters["per_page"]["schema"]["minimum"] == 1
    assert autocomplete_parameters["per_page"]["schema"]["maximum"] == 100
    autocomplete_example = components["AutocompleteResponse"]["examples"][0]
    assert autocomplete_example["results"] == [{"id": "1", "text": "Cameras"}]
    assert autocomplete_example["pagination"]["more"] is False
    changelist_config_props = components["ChangelistConfig"]["properties"]
    assert changelist_config_props["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    assert changelist_config_props["full_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert changelist_config_props["result_count"]["minimum"] == 0
    assert changelist_config_props["page_result_count"]["minimum"] == 0
    assert changelist_config_props["result_start_index"]["minimum"] == 0
    assert changelist_config_props["result_end_index"]["minimum"] == 0
    assert changelist_config_props["page_count"]["minimum"] == 0
    assert changelist_config_props["page"]["minimum"] == 1
    assert changelist_config_props["per_page"]["minimum"] == 1
    assert components["FilterChoice"]["properties"]["count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert components["PageChoice"]["properties"]["page"]["anyOf"] == [
        {"minimum": 1, "type": "integer"},
        {"type": "null"},
    ]
    assert changelist_config_props["page_range"]["items"] == {"$ref": "#/components/schemas/PageRangeItem"}
    assert components["PageRangeItem"]["anyOf"] == [
        {"$ref": "#/components/schemas/PageRangePage"},
        {"const": "\u2026", "type": "string"},
    ]
    assert components["PageRangePage"] == {"minimum": 1, "type": "integer"}
    assert changelist_config_props["ordering_field_columns"]["additionalProperties"] == {
        "$ref": "#/components/schemas/OrderingFieldColumnIndex"
    }
    assert components["OrderingFieldColumnIndex"] == {"minimum": 1, "type": "integer"}
    assert changelist_config_props["date_hierarchy"]["anyOf"][0] == {
        "$ref": "#/components/schemas/DateHierarchyDescription"
    }
    assert components["DateHierarchyLevel"] == {
        "enum": ["year", "month", "day"],
        "type": "string",
    }
    assert components["DateHierarchyChoice"]["properties"]["level"] == {
        "$ref": "#/components/schemas/DateHierarchyLevel"
    }
    assert components["DateHierarchyChoice"]["properties"]["value"] == {
        "$ref": "#/components/schemas/DateHierarchyChoiceValue"
    }
    assert components["DateHierarchyChoiceValue"] == {"minimum": 1, "maximum": 9999, "type": "integer"}
    assert components["DateHierarchyChoice"]["properties"]["count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert components["DateHierarchyDescription"]["properties"]["level"] == {
        "$ref": "#/components/schemas/DateHierarchyLevel"
    }
    assert components["DateHierarchyDescription"]["properties"]["params"] == {
        "$ref": "#/components/schemas/DateHierarchyParams"
    }
    date_hierarchy_params = components["DateHierarchyParams"]
    assert date_hierarchy_params["additionalProperties"] is False
    assert date_hierarchy_params["properties"]["year"]["anyOf"][0] == {"$ref": "#/components/schemas/DateHierarchyYear"}
    assert date_hierarchy_params["properties"]["month"]["anyOf"][0] == {
        "$ref": "#/components/schemas/DateHierarchyMonth"
    }
    assert date_hierarchy_params["properties"]["day"]["anyOf"][0] == {"$ref": "#/components/schemas/DateHierarchyDay"}
    assert components["DateHierarchyYear"] == {"minimum": 1, "maximum": 9999, "type": "integer"}
    assert components["DateHierarchyMonth"] == {"minimum": 1, "maximum": 12, "type": "integer"}
    assert components["DateHierarchyDay"] == {"minimum": 1, "maximum": 31, "type": "integer"}
    assert _response_schema_ref(paths["/admin-api/view-on-site/{content_type_id}/{object_id}"]["get"], "200") == (
        "#/components/schemas/ViewOnSiteResponse"
    )
    assert components["ViewOnSiteResponse"]["examples"][0] == {"url": "https://example.com/products/1/"}
    column_props = components["Column"]["properties"]
    assert column_props["sort_priority"]["anyOf"] == [
        {"minimum": 1, "type": "integer"},
        {"type": "null"},
    ]
    assert column_props["ordering_index"]["anyOf"] == [
        {"minimum": 1, "type": "integer"},
        {"type": "null"},
    ]
    assert components["Row"]["properties"]["cell_metadata"]["additionalProperties"] == {
        "$ref": "#/components/schemas/CellMetadata"
    }
    assert components["Row"]["properties"]["id"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
    assert components["Row"]["properties"]["index"]["minimum"] == 0
    assert components["Row"]["properties"]["result_index"]["minimum"] == 0
    assert components["Row"]["properties"]["cells"]["additionalProperties"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
    cell_metadata_props = components["CellMetadata"]["properties"]
    assert cell_metadata_props["value"]["allOf"] == [{"$ref": "#/components/schemas/FieldMetadataValue"}]
    assert cell_metadata_props["display_value"]["allOf"] == [{"$ref": "#/components/schemas/FieldMetadataValue"}]
    assert cell_metadata_props["empty"]["type"] == "boolean"
    assert cell_metadata_props["editable"]["type"] == "boolean"
    assert cell_metadata_props["link_url"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    changelist_response_props = components["ChangelistResponse"]["properties"]
    assert changelist_response_props["action_form"]["items"] == {"$ref": "#/components/schemas/ActionFormField"}
    assert components["ActionFormField"]["anyOf"] == [
        {"$ref": "#/components/schemas/ActionChoiceFieldDescription"},
        {"$ref": "#/components/schemas/ActionSelectedIdsFieldDescription"},
        {"$ref": "#/components/schemas/ActionSelectAcrossFieldDescription"},
    ]
    assert components["ActionChoiceFieldDescription"]["additionalProperties"] is False
    assert components["ActionChoiceFieldDescription"]["properties"]["name"]["const"] == "action"
    assert components["ActionChoiceFieldDescription"]["properties"]["type"]["const"] == "ChoiceField"
    assert components["ActionChoiceFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/ActionChoiceFieldAttributes"
    }
    assert components["ActionChoiceFieldAttributes"]["additionalProperties"] is False
    assert components["ActionChoiceFieldAttributes"]["required"] == ["choices"]
    assert components["ActionChoiceFieldAttributes"]["properties"]["required"]["const"] is True
    assert components["ActionChoiceFieldAttributes"]["properties"]["choices"]["items"] == {
        "$ref": "#/components/schemas/ChoicePair"
    }
    assert components["ActionSelectedIdsFieldDescription"]["additionalProperties"] is False
    assert components["ActionSelectedIdsFieldDescription"]["properties"]["name"]["const"] == "selected_ids"
    assert components["ActionSelectedIdsFieldDescription"]["properties"]["type"]["const"] == "MultipleChoiceField"
    assert components["ActionSelectedIdsFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/ActionSelectedIdsFieldAttributes"
    }
    assert components["ActionSelectedIdsFieldAttributes"]["additionalProperties"] is False
    assert components["ActionSelectedIdsFieldAttributes"]["properties"]["required"]["const"] is False
    assert components["ActionSelectAcrossFieldDescription"]["additionalProperties"] is False
    assert components["ActionSelectAcrossFieldDescription"]["properties"]["name"]["const"] == "select_across"
    assert components["ActionSelectAcrossFieldDescription"]["properties"]["type"]["const"] == "BooleanField"
    assert components["ActionSelectAcrossFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/ActionSelectAcrossFieldAttributes"
    }
    assert components["ActionSelectAcrossFieldAttributes"]["additionalProperties"] is False
    assert components["ActionSelectAcrossFieldAttributes"]["properties"]["required"]["const"] is False
    assert changelist_response_props["list_editing_formset_prefix"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_management_form"]["items"] == {
        "$ref": "#/components/schemas/ManagementFormField"
    }
    assert components["ManagementFormField"]["anyOf"] == [
        {"$ref": "#/components/schemas/TotalFormsFieldDescription"},
        {"$ref": "#/components/schemas/InitialFormsFieldDescription"},
        {"$ref": "#/components/schemas/MinNumFormsFieldDescription"},
        {"$ref": "#/components/schemas/MaxNumFormsFieldDescription"},
    ]
    assert components["TotalFormsFieldDescription"]["additionalProperties"] is False
    assert components["TotalFormsFieldDescription"]["properties"]["name"]["const"] == "TOTAL_FORMS"
    assert components["TotalFormsFieldDescription"]["properties"]["type"]["const"] == "IntegerField"
    assert components["TotalFormsFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/RequiredManagementFormFieldAttributes"
    }
    assert components["InitialFormsFieldDescription"]["additionalProperties"] is False
    assert components["InitialFormsFieldDescription"]["properties"]["name"]["const"] == "INITIAL_FORMS"
    assert components["InitialFormsFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/RequiredManagementFormFieldAttributes"
    }
    assert components["MinNumFormsFieldDescription"]["additionalProperties"] is False
    assert components["MinNumFormsFieldDescription"]["properties"]["name"]["const"] == "MIN_NUM_FORMS"
    assert components["MinNumFormsFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/OptionalManagementFormFieldAttributes"
    }
    assert components["MaxNumFormsFieldDescription"]["additionalProperties"] is False
    assert components["MaxNumFormsFieldDescription"]["properties"]["name"]["const"] == "MAX_NUM_FORMS"
    assert components["MaxNumFormsFieldDescription"]["properties"]["attrs"] == {
        "$ref": "#/components/schemas/OptionalManagementFormFieldAttributes"
    }
    required_management_attrs = components["RequiredManagementFormFieldAttributes"]
    assert required_management_attrs["additionalProperties"] is False
    assert required_management_attrs["properties"]["required"]["const"] is True
    assert required_management_attrs["properties"]["widget"]["const"] == "HiddenInput"
    assert required_management_attrs["properties"]["is_hidden"]["const"] is True
    assert required_management_attrs["properties"]["input_type"]["const"] == "hidden"
    assert required_management_attrs["properties"]["value"]["type"] == "integer"
    assert required_management_attrs["properties"]["value"]["minimum"] == 0
    optional_management_attrs = components["OptionalManagementFormFieldAttributes"]
    assert optional_management_attrs["additionalProperties"] is False
    assert optional_management_attrs["properties"]["required"]["const"] is False
    assert changelist_response_props["list_editing_total_form_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_initial_form_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert changelist_response_props["list_editing_formset"]["items"]["items"] == {
        "$ref": "#/components/schemas/FieldDescription"
    }
    assert changelist_response_props["list_editing_rows"]["items"] == {"$ref": "#/components/schemas/ListEditingRow"}
    list_editing_row_props = components["ListEditingRow"]["properties"]
    assert list_editing_row_props["index"]["minimum"] == 0
    assert list_editing_row_props["pk"] == {"$ref": "#/components/schemas/ObjectIdentifier"}
    assert list_editing_row_props["form_prefix"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert list_editing_row_props["empty_permitted"]["type"] == "boolean"

    form_response_props = components["FormResponse"]["properties"]
    assert form_response_props["inlines"]["items"] == {"$ref": "#/components/schemas/InlineDescription"}
    form_description_props = components["FormDescription"]["properties"]
    assert "fieldsets" not in form_description_props
    assert form_description_props["fieldset_layout"]["items"] == {"$ref": "#/components/schemas/FieldsetDescription"}
    assert form_description_props["prepopulated"] == {"$ref": "#/components/schemas/PrepopulatedFieldMap"}
    assert form_description_props["radio_fields"]["allOf"] == [{"$ref": "#/components/schemas/RadioFieldMap"}]
    assert components["PrepopulatedFieldMap"]["additionalProperties"]["items"] == {"type": "string"}
    assert components["RadioFieldMap"]["additionalProperties"] == {"enum": [1, 2], "type": "integer"}
    fieldset_description_props = components["FieldsetDescription"]["properties"]
    assert fieldset_description_props["name"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert fieldset_description_props["classes"]["items"] == {"type": "string"}
    assert fieldset_description_props["rows"]["items"] == {"$ref": "#/components/schemas/FieldsetRow"}
    assert components["FieldsetRow"]["properties"]["fields"]["items"] == {"type": "string"}
    inline_response_props = components["InlineDescription"]["properties"]
    assert "fieldsets" not in inline_response_props
    assert inline_response_props["fieldset_layout"]["items"] == {"$ref": "#/components/schemas/FieldsetDescription"}
    assert inline_response_props["prepopulated"] == {"$ref": "#/components/schemas/PrepopulatedFieldMap"}
    assert inline_response_props["management_form"]["items"] == {"$ref": "#/components/schemas/ManagementFormField"}
    assert inline_response_props["empty_form"]["items"] == {"$ref": "#/components/schemas/FieldDescription"}
    assert inline_response_props["formset_row_metadata"]["items"] == {
        "$ref": "#/components/schemas/InlineFormsetRowMetadata"
    }
    assert inline_response_props["total_form_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert inline_response_props["initial_form_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert inline_response_props["extra"]["minimum"] == 0
    assert inline_response_props["min_num"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert inline_response_props["max_num"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    inline_row_metadata_props = components["InlineFormsetRowMetadata"]["properties"]
    assert inline_row_metadata_props["index"]["minimum"] == 0
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
    assert field_attrs_example["input_schema_override"] == {"schema": {"type": "boolean"}}
    assert "html_name" not in field_attrs_example
    assert "rendered_attrs" not in field_attrs_example
    assert "rendered_subwidgets" not in field_attrs_example
    field_attrs_component = components["FieldAttributes"]
    assert field_attrs_component["additionalProperties"] is False
    field_attrs_props = field_attrs_component["properties"]
    assert RENDERED_FIELD_ATTR_KEYS.isdisjoint(field_attrs_props)
    assert field_attrs_props["required"]["anyOf"] == [{"type": "boolean"}, {"type": "null"}]
    assert field_attrs_props["ordering_field"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert field_attrs_props["max_length"]["anyOf"] == [
        {"$ref": "#/components/schemas/NonNegativeMetadataInteger"},
        {"type": "null"},
    ]
    assert field_attrs_props["min_length"]["anyOf"] == [
        {"$ref": "#/components/schemas/NonNegativeMetadataInteger"},
        {"type": "null"},
    ]
    assert field_attrs_props["decimal_places"]["anyOf"] == [
        {"$ref": "#/components/schemas/NonNegativeMetadataInteger"},
        {"type": "null"},
    ]
    assert field_attrs_props["max_digits"]["anyOf"] == [
        {"$ref": "#/components/schemas/PositiveMetadataInteger"},
        {"type": "null"},
    ]
    assert components["NonNegativeMetadataInteger"] == {"minimum": 0, "type": "integer"}
    assert components["PositiveMetadataInteger"] == {"minimum": 1, "type": "integer"}
    for metadata_value_field in (
        "default",
        "initial",
        "value",
        "empty_value",
        "min_value",
        "max_value",
        "step_size",
        "step_offset",
    ):
        assert field_attrs_props[metadata_value_field]["allOf"] == [{"$ref": "#/components/schemas/FieldMetadataValue"}]
    assert {"$ref": "#/components/schemas/FileFieldValue"} in field_attrs_props["current_file"]["anyOf"]
    assert {"$ref": "#/components/schemas/ImageFieldValue"} in field_attrs_props["current_file"]["anyOf"]
    assert field_attrs_props["choices"]["anyOf"][0]["items"] == {"$ref": "#/components/schemas/ChoicePair"}
    assert components["ChoicePair"]["minItems"] == 2
    assert components["ChoicePair"]["maxItems"] == 2
    assert components["ChoicePair"]["prefixItems"][1] == {"type": "string"}
    assert field_attrs_props["choice_options"]["anyOf"][0]["items"] == {"$ref": "#/components/schemas/ChoiceOption"}
    assert components["ChoiceOption"]["additionalProperties"] is False
    assert components["ChoiceOption"]["required"] == ["label"]
    assert components["ChoiceOption"]["properties"]["raw_value"]["allOf"] == [
        {"$ref": "#/components/schemas/FieldMetadataValue"}
    ]
    assert components["ChoiceOption"]["properties"]["coerced_value"]["allOf"] == [
        {"$ref": "#/components/schemas/FieldMetadataValue"}
    ]
    assert field_attrs_props["choice_groups"]["anyOf"][0]["items"] == {"$ref": "#/components/schemas/ChoiceGroup"}
    assert components["ChoiceGroup"]["additionalProperties"] is False
    assert components["ChoiceGroup"]["required"] == ["options"]
    assert components["ChoiceGroup"]["properties"]["options"]["items"] == {"$ref": "#/components/schemas/ChoiceOption"}
    assert field_attrs_props["combo_fields"]["anyOf"][0]["items"] == {"$ref": "#/components/schemas/ComboFieldMetadata"}
    assert components["ComboFieldMetadata"]["additionalProperties"] is False
    assert set(components["ComboFieldMetadata"]["required"]) == {"attrs", "index", "type"}
    assert components["ComboFieldMetadata"]["properties"]["index"]["minimum"] == 0
    assert components["ComboFieldMetadata"]["properties"]["attrs"] == {"$ref": "#/components/schemas/FieldAttributes"}
    assert {"type": "string"} in components["FieldMetadataValue"]["anyOf"]
    assert {"type": "null"} in components["FieldMetadataValue"]["anyOf"]
    assert field_attrs_props["validator_details"]["anyOf"][0]["items"] == {
        "$ref": "#/components/schemas/ValidatorDetail"
    }
    assert components["ValidatorDetail"]["additionalProperties"] is False
    assert components["ValidatorDetail"]["required"] == ["class"]
    assert components["ValidatorDetail"]["properties"]["class"]["type"] == "string"
    assert components["ValidatorDetail"]["properties"]["limit_value"]["allOf"] == [
        {"$ref": "#/components/schemas/FieldMetadataValue"}
    ]
    assert field_attrs_props["widget_attrs"]["anyOf"][0]["additionalProperties"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
    assert field_attrs_props["checked_attribute"]["anyOf"][0]["additionalProperties"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
    assert field_attrs_props["subwidgets"]["anyOf"][0]["items"] == {"$ref": "#/components/schemas/SubwidgetMetadata"}
    assert components["SubwidgetMetadata"]["additionalProperties"] is False
    assert set(components["SubwidgetMetadata"]["required"]) == {
        "is_hidden",
        "is_localized",
        "multiple",
        "name_suffix",
        "widget",
    }
    input_format_items = field_attrs_props["input_formats"]["anyOf"][0]["items"]["anyOf"]
    assert {"type": "string"} in input_format_items
    assert {"$ref": "#/components/schemas/IndexedInputFormats"} in input_format_items
    assert components["IndexedInputFormats"]["additionalProperties"] is False
    assert set(components["IndexedInputFormats"]["required"]) == {"index", "input_formats"}
    assert components["IndexedInputFormats"]["properties"]["index"]["minimum"] == 0
    assert field_attrs_props["select_date"]["anyOf"][0] == {"$ref": "#/components/schemas/SelectDateMetadata"}
    assert components["SelectDateMetadata"]["additionalProperties"] is False
    assert components["SelectDateMetadata"]["properties"]["years"]["items"] == {
        "$ref": "#/components/schemas/SelectDateYear"
    }
    assert components["SelectDateMetadata"]["properties"]["months"]["items"] == {
        "$ref": "#/components/schemas/SelectDateMonthChoice"
    }
    assert components["SelectDateMetadata"]["properties"]["days"]["items"] == {
        "$ref": "#/components/schemas/SelectDateDay"
    }
    assert components["SelectDateMetadata"]["properties"]["empty_choices"] == {
        "$ref": "#/components/schemas/SelectDateEmptyChoices"
    }
    assert components["SelectDateMetadata"]["properties"]["selected"]["anyOf"][0] == {
        "$ref": "#/components/schemas/SelectDateSelected"
    }
    assert components["SelectDateYear"] == {"minimum": 1, "maximum": 9999, "type": "integer"}
    assert components["SelectDateMonth"] == {"minimum": 1, "maximum": 12, "type": "integer"}
    assert components["SelectDateDay"] == {"minimum": 1, "maximum": 31, "type": "integer"}
    assert components["SelectDateMonthChoice"]["properties"]["value"] == {
        "$ref": "#/components/schemas/SelectDateMonth"
    }
    assert components["SelectDateEmptyChoice"]["properties"]["value"]["allOf"] == [
        {"$ref": "#/components/schemas/SelectDateEmptyChoiceValue"}
    ]
    assert components["SelectDateEmptyChoiceValue"] == {"anyOf": [{"const": "", "type": "string"}, {"type": "null"}]}
    assert components["SelectDateSelected"]["properties"]["year"]["anyOf"][0] == {
        "$ref": "#/components/schemas/SelectDateYear"
    }
    assert components["SelectDateSelected"]["properties"]["month"]["anyOf"][0] == {
        "$ref": "#/components/schemas/SelectDateMonth"
    }
    assert components["SelectDateSelected"]["properties"]["day"]["anyOf"][0] == {
        "$ref": "#/components/schemas/SelectDateDay"
    }
    selected_options_schema = field_attrs_props["selected_options"]["anyOf"][0]
    assert selected_options_schema["items"] == {"$ref": "#/components/schemas/SelectedOption"}
    assert components["SelectedOption"]["required"] == ["id", "text"]
    assert field_attrs_props["autocomplete"]["anyOf"][0] == {"$ref": "#/components/schemas/RelationWidgetMetadata"}
    assert field_attrs_props["raw_id"]["anyOf"][0] == {"$ref": "#/components/schemas/RelationWidgetMetadata"}
    assert field_attrs_props["filtered_select"]["anyOf"][0] == {"$ref": "#/components/schemas/FilteredSelectMetadata"}
    assert components["FilteredSelectMetadata"]["properties"]["selected_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert components["FilteredSelectMetadata"]["properties"]["available_count"]["anyOf"] == [
        {"minimum": 0, "type": "integer"},
        {"type": "null"},
    ]
    assert field_attrs_props["radio"]["anyOf"][0] == {"$ref": "#/components/schemas/RadioMetadata"}
    assert field_attrs_props["radio_orientation"]["anyOf"] == [
        {"enum": [1, 2], "type": "integer"},
        {"type": "null"},
    ]
    assert field_attrs_props["prepopulated"]["anyOf"][0] == {"$ref": "#/components/schemas/PrepopulatedMetadata"}
    assert field_attrs_props["input_schema_override"]["anyOf"][0] == {
        "$ref": "#/components/schemas/InputSchemaOverrideMetadata"
    }
    assert components["InputSchemaOverrideMetadata"]["additionalProperties"] is False
    assert components["InputSchemaOverrideMetadata"]["required"] == ["schema"]
    assert components["InputSchemaOverrideMetadata"]["properties"]["schema"] == {
        "$ref": "#/components/schemas/JsonSchemaValue"
    }
    assert {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/JsonSchemaValue"}} in components[
        "JsonSchemaValue"
    ]["anyOf"]
    assert components["RelationWidgetMetadata"]["additionalProperties"] is False
    assert components["RelationWidgetMetadata"]["properties"]["query"]["anyOf"][:2] == [
        {"$ref": "#/components/schemas/SourceFieldIdentity"},
        {"$ref": "#/components/schemas/ToFieldQuery"},
    ]
    assert components["ToFieldQuery"]["properties"]["_to_field"]["type"] == "string"
    assert components["FilteredSelectMetadata"]["properties"]["direction"]["enum"] == ["horizontal", "vertical"]
    assert components["FilteredSelectMetadata"]["properties"]["query"]["anyOf"] == [
        {"$ref": "#/components/schemas/ToFieldQuery"},
        {"type": "null"},
    ]
    assert components["FilteredSelectMetadata"]["required"] == ["field_name", "direction", "is_stacked"]
    assert components["RadioMetadata"]["properties"]["orientation"] == {
        "enum": [1, 2],
        "title": "Orientation",
        "type": "integer",
    }
    assert components["PrepopulatedMetadata"]["properties"]["sources"]["items"] == {
        "$ref": "#/components/schemas/PrepopulatedSourceMetadata"
    }
    assert components["PrepopulatedSourceMetadata"]["required"] == ["field_name"]
    error_examples = components["ErrorResponse"]["examples"]
    assert error_examples[0] == {"errors": [{"param": "name", "message": ["This field is required."]}]}
    assert error_examples[1]["errors"] == [{"param": "non_field_errors", "message": "Permission denied."}]
    assert error_examples[2]["deleted_objects"] == ["Nice camera"]
    assert error_examples[2]["protected"] == ["Protected review: Nice camera"]
    assert error_examples[2]["perms_needed"] == ["Can delete product review"]
    assert error_examples[2]["model_count"] == {"product reviews": 1}
    assert components["ErrorResponse"]["properties"]["model_count"]["anyOf"] == [
        {
            "additionalProperties": {"$ref": "#/components/schemas/NonNegativeCount"},
            "type": "object",
        },
        {"type": "null"},
    ]
    assert components["NonNegativeCount"] == {"minimum": 0, "type": "integer"}

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


def test_generated_admin_contract_schemas_reject_top_level_extra_fields(db):
    model_admin = site.get_model_admin(Product)
    create_payload_schema = model_admin.get_mutation_payload_schema(None, change=False, partial=False)
    partial_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=True)
    update_payload_schema = model_admin.get_mutation_payload_schema(None, change=True, partial=False)
    bulk_payload_schema = model_admin.get_bulk_payload_schema(None)
    mutation_response_schema = model_admin.get_mutation_response_schema(None)
    action_payload_schema = model_admin.get_action_payload_schema(None)

    for schema in [
        create_payload_schema,
        partial_payload_schema,
        update_payload_schema,
        bulk_payload_schema,
        mutation_response_schema,
    ]:
        payload = dict(schema.model_json_schema()["examples"][0])
        schema.model_validate(payload)
        payload["unexpected"] = True

        with pytest.raises(ValidationError) as exc_info:
            schema.model_validate(payload)

        assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
        assert exc_info.value.errors()[0]["loc"] == ("unexpected",)

    action_payload_schema.model_validate({"action": "mark_out_of_stock", "selected_ids": [1], "select_across": False})
    with pytest.raises(ValidationError) as exc_info:
        action_payload_schema.model_validate(
            {
                "action": "mark_out_of_stock",
                "selected_ids": [1],
                "select_across": False,
                "unexpected": True,
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
    assert exc_info.value.errors()[0]["loc"] == ("mark_out_of_stock", "unexpected")


def test_pagination_schema_is_shared_and_constrained(admin_client, sample):
    schema = admin_client.get("/admin-api/openapi.json").json()
    components = schema["components"]["schemas"]

    assert components["Pagination"]["properties"]["count"]["minimum"] == 0
    assert components["Pagination"]["properties"]["num_pages"]["minimum"] == 0
    assert components["Pagination"]["properties"]["page"]["minimum"] == 1
    assert components["Pagination"]["properties"]["per_page"]["minimum"] == 1
    assert components["ChangelistConfig"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    assert components["HistoryResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}
    assert components["AutocompleteResponse"]["properties"]["pagination"] == {"$ref": "#/components/schemas/Pagination"}

    changelist = admin_client.get("/admin-api/testapp/product")
    history = admin_client.get("/admin-api/history")
    autocomplete = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Cam",
        },
    )
    assert changelist.status_code == 200
    assert history.status_code == 200
    assert autocomplete.status_code == 200
    assert (
        set(changelist.json()["config"]["pagination"])
        == set(history.json()["pagination"])
        == set(autocomplete.json()["pagination"])
    )

    Pagination.model_validate({"count": 0, "num_pages": 0})
    with pytest.raises(ValidationError) as exc_info:
        Pagination.model_validate({"count": -1, "num_pages": 0})

    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("count",)


def test_disabled_action_payload_schema_rejects_arbitrary_data(db):
    class NoActionsProductAdmin(ModelAdmin):
        actions = None

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, NoActionsProductAdmin)
    action_payload_schema = admin_site.get_model_admin(Product).get_action_payload_schema(None)

    action_payload_schema.model_validate({"action": "delete_selected", "selected_ids": [1]})

    with pytest.raises(ValidationError) as exc_info:
        action_payload_schema.model_validate(
            {"action": "delete_selected", "selected_ids": [1], "data": {"unexpected": True}}
        )

    assert exc_info.value.errors()[0]["type"] == "none_required"
    assert exc_info.value.errors()[0]["loc"] == ("data",)


def test_disabled_action_response_schema_ignores_site_action_schemas(db):
    class GlobalActionResult(BaseModel):
        exported: int

    @action(response_schema=GlobalActionResult)
    def export_products(model_admin, request, queryset):
        return {"exported": queryset.count()}

    class NoActionsProductAdmin(ModelAdmin):
        actions = None

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.add_action(export_products)
    admin_site.register(Product, NoActionsProductAdmin)

    model_admin = admin_site.get_model_admin(Product)

    assert model_admin.has_registered_actions() is False
    assert model_admin.get_action_response_schema(None) is ActionResponse


def test_public_response_count_maps_reject_negative_values():
    ActionResponse.model_validate({"detail": "Action completed.", "deleted": {"products": 0}})
    ErrorResponse.model_validate(
        {
            "errors": [{"message": "Cannot delete selected objects.", "param": "delete"}],
            "model_count": {"products": 0},
        }
    )

    with pytest.raises(ValidationError) as action_exc_info:
        ActionResponse.model_validate({"detail": "Action completed.", "deleted": {"products": -1}})
    assert action_exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert action_exc_info.value.errors()[0]["loc"] == ("deleted", "products")

    with pytest.raises(ValidationError) as error_exc_info:
        ErrorResponse.model_validate(
            {
                "errors": [{"message": "Cannot delete selected objects.", "param": "delete"}],
                "model_count": {"products": -1},
            }
        )
    assert error_exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert error_exc_info.value.errors()[0]["loc"] == ("model_count", "products")


def test_changelist_action_form_schema_is_typed_and_closed(admin_client, sample):
    body = admin_client.get("/admin-api/testapp/product").json()

    ChangelistResponse.model_validate(body)
    assert {field["name"] for field in body["action_form"]} == {"action", "selected_ids", "select_across"}

    invalid_body = dict(body)
    invalid_body["action_form"] = [
        {
            "name": "action",
            "type": "ChoiceField",
            "attrs": {
                "required": True,
                "choices": [["delete_selected", "Delete selected products"]],
                "unexpected": True,
            },
        }
    ]
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_body)

    error = exc_info.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"][:2] == ("action_form", 0)
    assert error["loc"][-2:] == ("attrs", "unexpected")


def test_metadata_count_and_index_schemas_reject_impossible_values(admin_client, sample):
    changelist_body = admin_client.get("/admin-api/testapp/product").json()

    invalid_sort_priority = deepcopy(changelist_body)
    invalid_sort_priority["columns"][0]["sort_priority"] = 0
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_sort_priority)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("columns", 0, "sort_priority")

    invalid_ordering_index = deepcopy(changelist_body)
    invalid_ordering_index["columns"][0]["ordering_index"] = 0
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_ordering_index)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("columns", 0, "ordering_index")

    invalid_page_number = deepcopy(changelist_body["config"])
    invalid_page_number["page_range"] = [0]
    with pytest.raises(ValidationError) as exc_info:
        ChangelistConfig.model_validate(invalid_page_number)
    assert any(error["type"] == "greater_than_equal" for error in exc_info.value.errors())

    invalid_page_marker = deepcopy(changelist_body["config"])
    invalid_page_marker["page_range"] = ["more"]
    with pytest.raises(ValidationError) as exc_info:
        ChangelistConfig.model_validate(invalid_page_marker)
    assert any(error["type"] == "literal_error" for error in exc_info.value.errors())

    invalid_ordering_column = deepcopy(changelist_body["config"])
    invalid_ordering_column["ordering_field_columns"] = {"name": 0}
    with pytest.raises(ValidationError) as exc_info:
        ChangelistConfig.model_validate(invalid_ordering_column)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("ordering_field_columns", "name")

    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate(
            {
                "filtered_select": {
                    "field_name": "tags",
                    "direction": "vertical",
                    "is_stacked": True,
                    "selected_count": -1,
                }
            }
        )
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("filtered_select", "selected_count")

    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"combo_fields": [{"index": -1, "type": "CharField", "attrs": {}}]})
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("combo_fields", 0, "index")

    for field_name in ("max_length", "min_length", "decimal_places"):
        with pytest.raises(ValidationError) as exc_info:
            FieldAttributes.model_validate({field_name: -1})
        assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
        assert exc_info.value.errors()[0]["loc"] == (field_name,)

    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"max_digits": 0})
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("max_digits",)

    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"input_formats": [{"index": -1, "input_formats": ["%Y-%m-%d"]}]})
    assert any(
        error["type"] == "greater_than_equal" and error["loc"][-1] == "index" for error in exc_info.value.errors()
    )

    select_date_metadata = {
        "order": ["year", "month", "day"],
        "years": [2026],
        "months": [{"value": 1, "label": "January"}],
        "days": [1],
        "empty_choices": {
            "year": {"value": "", "label": "---"},
            "month": {"value": "", "label": "---"},
            "day": {"value": "", "label": "---"},
        },
        "selected": {"year": 2026, "month": 1, "day": 1},
    }
    FieldAttributes.model_validate({"select_date": select_date_metadata})

    invalid_select_date_days = deepcopy(select_date_metadata)
    invalid_select_date_days["days"] = [0]
    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"select_date": invalid_select_date_days})
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("select_date", "days", 0)

    invalid_select_date_years = deepcopy(select_date_metadata)
    invalid_select_date_years["years"] = [10000]
    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"select_date": invalid_select_date_years})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("select_date", "years", 0)

    invalid_select_date_month = deepcopy(select_date_metadata)
    invalid_select_date_month["months"] = [{"value": 13, "label": "Undecimber"}]
    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"select_date": invalid_select_date_month})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("select_date", "months", 0, "value")

    invalid_select_date_selected = deepcopy(select_date_metadata)
    invalid_select_date_selected["selected"]["day"] = 32
    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"select_date": invalid_select_date_selected})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("select_date", "selected", "day")

    invalid_select_date_empty = deepcopy(select_date_metadata)
    invalid_select_date_empty["empty_choices"]["year"]["value"] = "Year"
    with pytest.raises(ValidationError) as exc_info:
        FieldAttributes.model_validate({"select_date": invalid_select_date_empty})
    assert exc_info.value.errors()[0]["type"] == "literal_error"
    assert exc_info.value.errors()[0]["loc"] == ("select_date", "empty_choices", "year", "value")

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyParams.model_validate({"year": 2026, "month": 0})
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("month",)
    assert DateHierarchyParams.model_validate({"year": 2026}).model_dump(mode="json") == {"year": 2026}

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyParams.model_validate({"year": 10000})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("year",)

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyParams.model_validate({"month": 13})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("month",)

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyParams.model_validate({"day": 32})
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("day",)

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyParams.model_validate({"quarter": 1})
    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
    assert exc_info.value.errors()[0]["loc"] == ("quarter",)

    with pytest.raises(ValidationError) as exc_info:
        DateHierarchyChoice.model_validate(
            {
                "selected": False,
                "query_string": "?year=10000",
                "display": "10000",
                "level": "year",
                "value": 10000,
            }
        )
    assert exc_info.value.errors()[0]["type"] == "less_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("value",)


def test_formset_management_form_schemas_are_typed_and_closed(admin_client, sample):
    changelist_body = admin_client.get("/admin-api/testapp/product").json()
    form_body = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form").json()

    ChangelistResponse.model_validate(changelist_body)
    FormResponse.model_validate(form_body)
    assert {field["name"] for field in changelist_body["list_editing_management_form"]} == {
        "TOTAL_FORMS",
        "INITIAL_FORMS",
        "MIN_NUM_FORMS",
        "MAX_NUM_FORMS",
    }
    inline = next(item for item in form_body["inlines"] if item["model"] == "testapp.productimage")
    assert {field["name"] for field in inline["management_form"]} == {
        "TOTAL_FORMS",
        "INITIAL_FORMS",
        "MIN_NUM_FORMS",
        "MAX_NUM_FORMS",
    }

    invalid_changelist_count = deepcopy(changelist_body)
    invalid_changelist_count["list_editing_total_form_count"] = -1
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_changelist_count)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("list_editing_total_form_count",)

    invalid_changelist_row_index = deepcopy(changelist_body)
    invalid_changelist_row_index["rows"][0]["index"] = -1
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_changelist_row_index)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("rows", 0, "index")

    invalid_list_editing_row_index = deepcopy(changelist_body)
    invalid_list_editing_row_index["list_editing_rows"][0]["index"] = -1
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_list_editing_row_index)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("list_editing_rows", 0, "index")

    invalid_inline_count = deepcopy(form_body)
    invalid_inline_count["inlines"][0]["total_form_count"] = -1
    with pytest.raises(ValidationError) as exc_info:
        FormResponse.model_validate(invalid_inline_count)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("inlines", 0, "total_form_count")

    invalid_inline_extra = deepcopy(form_body)
    invalid_inline_extra["inlines"][0]["extra"] = -1
    with pytest.raises(ValidationError) as exc_info:
        FormResponse.model_validate(invalid_inline_extra)
    assert exc_info.value.errors()[0]["type"] == "greater_than_equal"
    assert exc_info.value.errors()[0]["loc"] == ("inlines", 0, "extra")

    invalid_changelist_body = dict(changelist_body)
    invalid_changelist_body["list_editing_management_form"] = [
        {
            "name": "TOTAL_FORMS",
            "type": "IntegerField",
            "attrs": {
                "required": True,
                "label": "Total Forms",
                "widget": "HiddenInput",
                "is_hidden": True,
                "is_localized": False,
                "multiple": False,
                "input_type": "hidden",
                "needs_multipart_form": False,
                "value": 2,
                "unexpected": True,
            },
        }
    ]
    with pytest.raises(ValidationError) as exc_info:
        ChangelistResponse.model_validate(invalid_changelist_body)

    error = exc_info.value.errors()[0]
    assert error["type"] == "extra_forbidden"
    assert error["loc"][:2] == ("list_editing_management_form", 0)
    assert error["loc"][-2:] == ("attrs", "unexpected")

    invalid_form_body = dict(form_body)
    invalid_inline = dict(inline)
    invalid_inline["management_form"] = [
        {
            "name": "UNKNOWN_FORMS",
            "type": "IntegerField",
            "attrs": {
                "required": True,
                "label": "Unknown Forms",
                "widget": "HiddenInput",
                "is_hidden": True,
                "is_localized": False,
                "multiple": False,
                "input_type": "hidden",
                "needs_multipart_form": False,
                "value": 1,
            },
        }
    ]
    invalid_form_body["inlines"] = [invalid_inline]
    with pytest.raises(ValidationError) as exc_info:
        FormResponse.model_validate(invalid_form_body)

    error = exc_info.value.errors()[0]
    assert error["type"] == "literal_error"
    assert error["loc"][:4] == ("inlines", 0, "management_form", 0)
    assert error["loc"][-1] == "name"


def _request_schema_ref(operation):
    return operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
