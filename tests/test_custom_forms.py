from django.test import override_settings

from django_ninja_admin import VERTICAL
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category, Product, Tag

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


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


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
        _response_schema_ref(paths["/status-hook-admin/testapp/product"]["post"], "200")
        == "#/components/schemas/ProductAddImmediateHookResponse"
    )
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product"]["post"], "202")
        == "#/components/schemas/ProductAddHookResponse"
    )
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product/{object_id}"]["patch"], "202")
        == "#/components/schemas/ProductChangeHookResponse"
    )
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product/{object_id}"]["patch"], "200")
        == "#/components/schemas/ProductChangeHookResponse"
    )
    assert "201" not in paths["/status-hook-admin/testapp/product/{object_id}"]["patch"]["responses"]
    assert (
        _response_schema_ref(paths["/status-hook-admin/testapp/product/{object_id}"]["delete"], "200")
        == "#/components/schemas/ProductDeleteImmediateHookResponse"
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

    immediate_created = admin_client.post(
        "/status-hook-admin/testapp/product",
        data={
            "data": {
                "name": "Immediate Status Hook",
                "category": sample.category_id,
                "price": "8.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert immediate_created.status_code == 200
    immediate_created_body = immediate_created.json()
    assert immediate_created_body["hook"] == "add"
    assert immediate_created_body["immediate"] is True
    assert isinstance(immediate_created_body["product_id"], int)
    immediate_created_id = immediate_created_body["product_id"]
    assert Product.objects.filter(pk=immediate_created_id, name="Immediate Status Hook").exists()

    changed = admin_client.patch(
        f"/status-hook-admin/testapp/product/{created_id}",
        data={"data": {"description": "Custom status response"}},
        content_type="application/json",
    )

    assert changed.status_code == 200
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

    immediate_deleted = admin_client.delete(f"/status-hook-admin/testapp/product/{immediate_created_id}")

    assert immediate_deleted.status_code == 200
    assert immediate_deleted.json() == {
        "hook": "delete",
        "deleted_id": str(immediate_created_id),
        "immediate": True,
    }
    assert not Product.objects.filter(pk=immediate_created_id).exists()


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_invalid_response_hooks_are_validated_inside_mutation_transaction(admin_client, sample):
    created = admin_client.post(
        "/invalid-response-hook-admin/testapp/product",
        data={
            "data": {
                "name": "Invalid Add Hook",
                "category": sample.category_id,
                "price": "8.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 400
    ErrorResponse.model_validate(created.json())
    assert not Product.objects.filter(name="Invalid Add Hook").exists()

    original_description = sample.description
    changed = admin_client.patch(
        f"/invalid-response-hook-admin/testapp/product/{sample.pk}",
        data={"data": {"description": "Invalid change hook"}},
        content_type="application/json",
    )

    assert changed.status_code == 400
    ErrorResponse.model_validate(changed.json())
    sample.refresh_from_db()
    assert sample.description == original_description

    delete_target = Product.objects.create(
        name="Invalid Delete Hook",
        category=sample.category,
        price="8.00",
        stock_status="in_stock",
    )
    deleted = admin_client.delete(f"/invalid-response-hook-admin/testapp/product/{delete_target.pk}")

    assert deleted.status_code == 400
    ErrorResponse.model_validate(deleted.json())
    assert Product.objects.filter(pk=delete_target.pk).exists()


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_response_hooks_can_return_no_content_status(admin_client, sample):
    schema = admin_client.get("/no-content-hook-admin/openapi.json").json()
    paths = schema["paths"]
    assert "content" not in paths["/no-content-hook-admin/testapp/product"]["post"]["responses"]["204"]
    assert "content" not in paths["/no-content-hook-admin/testapp/product/{object_id}"]["patch"]["responses"]["204"]
    assert "content" not in paths["/no-content-hook-admin/testapp/product/{object_id}"]["delete"]["responses"]["204"]

    created = admin_client.post(
        "/no-content-hook-admin/testapp/product",
        data={
            "data": {
                "name": "No Content Hook",
                "category": sample.category_id,
                "price": "8.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 204
    product = Product.objects.get(name="No Content Hook")

    changed = admin_client.patch(
        f"/no-content-hook-admin/testapp/product/{product.pk}",
        data={"data": {"description": "No content change"}},
        content_type="application/json",
    )

    assert changed.status_code == 204
    product.refresh_from_db()
    assert product.description == "No content change"

    deleted = admin_client.delete(f"/no-content-hook-admin/testapp/product/{product.pk}")

    assert deleted.status_code == 204
    assert not Product.objects.filter(pk=product.pk).exists()


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_response_hooks_reject_no_content_bodies_inside_transaction(admin_client, sample):
    created = admin_client.post(
        "/invalid-no-content-hook-admin/testapp/product",
        data={
            "data": {
                "name": "Invalid No Content Hook",
                "category": sample.category_id,
                "price": "8.00",
                "stock_status": "in_stock",
            }
        },
        content_type="application/json",
    )

    assert created.status_code == 400
    assert created.json()["errors"] == [{"message": "Response status does not allow a body.", "param": "response_add"}]
    assert not Product.objects.filter(name="Invalid No Content Hook").exists()


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
