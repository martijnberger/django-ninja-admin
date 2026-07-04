import json
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from django_ninja_admin import site
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category, Product


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
    filtered_item = filtered.json()["results"][0]
    assert filtered_item["id"] == product_addition.pk
    assert filtered_item["user_id"] == actor.pk
    assert filtered_item["content_type_id"] == product_ct.pk
    assert filtered_item["change_message"] == [{"added": {}}]
    assert filtered_item["change_message_text"] == "Added."

    forbidden = client.get("/admin-api/history", {"app_label": "testapp", "model": "category"})
    assert forbidden.status_code == 403

    missing_app_label = client.get("/admin-api/history", {"model": "product"})
    assert missing_app_label.status_code == 400
    assert missing_app_label.json()["errors"] == [
        {"message": "app_label is required when model is provided.", "param": "app_label"}
    ]

    bad_page = client.get("/admin-api/history", {"page": 0})
    assert bad_page.status_code == 422
    assert bad_page.json()["errors"] == [
        {"message": "Input should be greater than or equal to 1", "param": "query.page"}
    ]

    bad_page_size = client.get("/admin-api/history", {"per_page": 0})
    assert bad_page_size.status_code == 422
    assert bad_page_size.json()["errors"] == [
        {"message": "Input should be greater than or equal to 1", "param": "query.per_page"}
    ]

    excessive_page_size = client.get("/admin-api/history", {"per_page": 101})
    assert excessive_page_size.status_code == 422
    assert excessive_page_size.json()["errors"] == [
        {"message": "Input should be less than or equal to 100", "param": "query.per_page"}
    ]

    invalid_ordering = client.get("/admin-api/history", {"o": "object_repr"})
    assert invalid_ordering.status_code == 422
    ErrorResponse.model_validate(invalid_ordering.json())
    assert invalid_ordering.json()["errors"][0]["param"] == "query.o"

    invalid_action_flag = client.get("/admin-api/history", {"action_flag": 99})
    assert invalid_action_flag.status_code == 422
    ErrorResponse.model_validate(invalid_action_flag.json())
    assert invalid_action_flag.json()["errors"][0]["param"] == "query.action_flag"


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


def test_history_query_count_is_bounded_by_requested_page(admin_client, sample):
    actor = get_user_model().objects.create_user("history-count-actor", password="pw", is_staff=True)
    product_ct = ContentType.objects.get_for_model(Product, for_concrete_model=False)
    now = timezone.now()
    for index in range(80):
        LogEntry.objects.create(
            user=actor,
            content_type=product_ct,
            object_id=str(sample.pk),
            object_repr=f"{sample}:{index}",
            action_flag=CHANGE,
            action_time=now + timedelta(seconds=index),
            change_message=json.dumps([{"changed": {"fields": ["Name"]}}]),
        )

    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin-api/history", {"app_label": "testapp", "model": "product", "per_page": 2})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert response.json()["pagination"]["count"] == 80
    assert len(queries) <= 8


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
