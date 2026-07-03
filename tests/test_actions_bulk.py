from django.test import override_settings
from ninja import Status

from django_ninja_admin import action, site
from django_ninja_admin.models import CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category, Product, ProductReview


def assert_sample_deleted_objects_tree(body):
    assert body["deleted_objects"][0] == "Alpha"
    assert "Front" in body["deleted_objects"][1]
    assert any(item.startswith("Product_tags object") for item in body["deleted_objects"][1])


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


def test_model_actions_require_model_access(staff_client, sample):
    client = staff_client()
    response = client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert response.status_code == 403
