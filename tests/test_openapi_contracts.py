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
    assert mutation_response_schema["properties"]["inlines"]["anyOf"] == [
        {"$ref": "#/components/schemas/ProductAdminInlineResponse"},
        {"type": "null"},
    ]
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
    assert "additionalProperties" not in components["ProductAdminMutationData"]
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
    assert components["HistoryItem"]["properties"]["id"] == {"$ref": "#/components/schemas/FieldMetadataValue"}
    assert components["HistoryItem"]["properties"]["user_id"] == {"$ref": "#/components/schemas/FieldMetadataValue"}
    assert components["HistoryItem"]["properties"]["change_message"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
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
    assert components["Row"]["properties"]["id"] == {"$ref": "#/components/schemas/FieldMetadataValue"}
    assert components["Row"]["properties"]["cells"]["additionalProperties"] == {
        "$ref": "#/components/schemas/FieldMetadataValue"
    }
    cell_metadata_props = components["CellMetadata"]["properties"]
    assert cell_metadata_props["value"]["allOf"] == [{"$ref": "#/components/schemas/FieldMetadataValue"}]
    assert cell_metadata_props["display_value"]["allOf"] == [{"$ref": "#/components/schemas/FieldMetadataValue"}]
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
    assert list_editing_row_props["pk"] == {"$ref": "#/components/schemas/FieldMetadataValue"}
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
    assert {"type": "string"} in components["RadioFieldMap"]["additionalProperties"]["anyOf"]
    assert {"type": "integer"} in components["RadioFieldMap"]["additionalProperties"]["anyOf"]
    fieldset_description_props = components["FieldsetDescription"]["properties"]
    assert fieldset_description_props["name"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert fieldset_description_props["classes"]["items"] == {"type": "string"}
    assert fieldset_description_props["rows"]["items"] == {"$ref": "#/components/schemas/FieldsetRow"}
    assert components["FieldsetRow"]["properties"]["fields"]["items"] == {"type": "string"}
    inline_response_props = components["InlineDescription"]["properties"]
    assert "fieldsets" not in inline_response_props
    assert inline_response_props["fieldset_layout"]["items"] == {"$ref": "#/components/schemas/FieldsetDescription"}
    assert inline_response_props["prepopulated"] == {"$ref": "#/components/schemas/PrepopulatedFieldMap"}
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
    assert field_attrs_props["select_date"]["anyOf"][0] == {"$ref": "#/components/schemas/SelectDateMetadata"}
    assert components["SelectDateMetadata"]["additionalProperties"] is False
    assert components["SelectDateMetadata"]["properties"]["months"]["items"] == {
        "$ref": "#/components/schemas/SelectDateChoice"
    }
    assert components["SelectDateMetadata"]["properties"]["empty_choices"] == {
        "$ref": "#/components/schemas/SelectDateEmptyChoices"
    }
    selected_options_schema = field_attrs_props["selected_options"]["anyOf"][0]
    assert selected_options_schema["items"] == {"$ref": "#/components/schemas/SelectedOption"}
    assert components["SelectedOption"]["required"] == ["id", "text"]
    assert field_attrs_props["autocomplete"]["anyOf"][0] == {"$ref": "#/components/schemas/RelationWidgetMetadata"}
    assert field_attrs_props["raw_id"]["anyOf"][0] == {"$ref": "#/components/schemas/RelationWidgetMetadata"}
    assert field_attrs_props["filtered_select"]["anyOf"][0] == {"$ref": "#/components/schemas/FilteredSelectMetadata"}
    assert field_attrs_props["radio"]["anyOf"][0] == {"$ref": "#/components/schemas/RadioMetadata"}
    assert field_attrs_props["prepopulated"]["anyOf"][0] == {"$ref": "#/components/schemas/PrepopulatedMetadata"}
    assert components["RelationWidgetMetadata"]["additionalProperties"] is False
    assert components["RelationWidgetMetadata"]["properties"]["query"]["anyOf"][:2] == [
        {"$ref": "#/components/schemas/SourceFieldIdentity"},
        {"$ref": "#/components/schemas/ToFieldQuery"},
    ]
    assert components["ToFieldQuery"]["properties"]["_to_field"]["type"] == "string"
    assert components["FilteredSelectMetadata"]["properties"]["direction"]["enum"] == ["horizontal", "vertical"]
    assert components["FilteredSelectMetadata"]["required"] == ["field_name", "direction", "is_stacked"]
    assert components["RadioMetadata"]["properties"]["orientation"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]
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
