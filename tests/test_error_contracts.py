from django.test import Client

from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import ProductReview


def assert_sample_deleted_objects_tree(body):
    assert body["deleted_objects"][0] == "Alpha"
    assert "Front" in body["deleted_objects"][1]
    assert any(item.startswith("Product_tags object") for item in body["deleted_objects"][1])


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

    invalid_query_body = assert_error_body(admin_client.get("/admin-api/testapp/product?pp=not-an-int"), 422)
    assert invalid_query_body["errors"][0]["param"] == "query.pp"

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
