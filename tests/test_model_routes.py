import json

from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from django_ninja_admin import site
from tests.testapp.models import Category, Product, ProductReview


def assert_sample_deleted_objects_tree(body):
    assert body["deleted_objects"][0] == "Alpha"
    assert "Front" in body["deleted_objects"][1]
    assert any(item.startswith("Product_tags object") for item in body["deleted_objects"][1])


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
    body = response.json()
    assert body["errors"] == [{"message": "Permission denied.", "param": "object_id"}]
    assert_sample_deleted_objects_tree(body)
    assert body["perms_needed"] == ["product"]
    assert body["model_count"]["testapp.product"] == 1
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

    hidden_bad_category_field = admin_client.get(
        f"/admin-api/testapp/category/{sample.category_id}?_to_field=name&_to_field=id"
    )
    assert hidden_bad_category_field.status_code == 400
    assert hidden_bad_category_field.json()["errors"] == [
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

    hidden_bad_field = admin_client.get("/slug-autocomplete-admin/testapp/category?_to_field=name&_to_field=slug")
    assert hidden_bad_field.status_code == 400
    assert hidden_bad_field.json()["errors"] == [
        {"message": "The field 'name' cannot be referenced.", "param": "_to_field"}
    ]


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


def test_view_on_site_requires_model_access(staff_client, sample):
    content_type = ContentType.objects.get_for_model(Product)
    response = staff_client().get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert response.status_code == 403
