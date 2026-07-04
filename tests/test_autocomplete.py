import pytest
from django.core.paginator import Paginator
from django.db import connection, models
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from django_ninja_admin import site
from tests.testapp.models import Category, CategoryLimitedLink, CategorySlugLink, Product, Tag


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
            "per_page": 10,
        },
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["results"]) == 10
    assert first_page.json()["pagination"] == {
        "count": 25,
        "num_pages": 3,
        "page": 1,
        "per_page": 10,
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
            "per_page": 10,
        },
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["results"]) == 10
    assert second_page.json()["pagination"] == {
        "count": 25,
        "num_pages": 3,
        "page": 2,
        "per_page": 10,
        "has_next": True,
        "has_previous": True,
        "more": True,
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
    assert bad_page.status_code == 422
    assert bad_page.json()["errors"] == [
        {"message": "Input should be greater than or equal to 1", "param": "query.page"}
    ]

    bad_page_size = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "per_page": 0,
        },
    )
    assert bad_page_size.status_code == 422
    assert bad_page_size.json()["errors"] == [
        {"message": "Input should be greater than or equal to 1", "param": "query.per_page"}
    ]

    excessive_page_size = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "per_page": 101,
        },
    )
    assert excessive_page_size.status_code == 422
    assert excessive_page_size.json()["errors"] == [
        {"message": "Input should be less than or equal to 100", "param": "query.per_page"}
    ]


def test_autocomplete_query_count_is_bounded_by_requested_page(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "autocomplete_fields", ("tags",))
    Tag.objects.bulk_create(Tag(name=f"Bounded Tag {index:02d}") for index in range(80))

    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(
            "/admin-api/autocomplete",
            {
                "app_label": "testapp",
                "model_name": "product",
                "field_name": "tags",
                "term": "Bounded",
            },
        )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 20
    assert response.json()["pagination"]["count"] == 80
    assert len(queries) <= 8


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
            "per_page": 2,
        },
    )

    assert response.status_code == 200
    assert calls == {
        "path": "/admin-api/autocomplete",
        "model": Tag,
        "is_queryset": True,
        "per_page": 2,
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


@pytest.mark.parametrize(
    "limit_choices_to",
    [
        lambda: {"slug__startswith": "public"},
        models.Q(slug__startswith="public"),
    ],
    ids=["callable", "q-object"],
)
def test_autocomplete_applies_dynamic_source_field_limit_choices_to(
    admin_client, sample, monkeypatch, limit_choices_to
):
    public = sample.category
    public.name = "Public Cameras"
    public.slug = "public-cameras"
    public.save(update_fields=["name", "slug"])
    Category.objects.create(name="Private Cameras", slug="private-cameras")
    category_field = Product._meta.get_field("category")
    monkeypatch.setattr(category_field.remote_field, "limit_choices_to", limit_choices_to)

    response = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "category",
            "term": "Cameras",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [{"id": str(public.pk), "text": "Public Cameras"}]


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


def test_autocomplete_requires_source_model_access_and_declared_field(admin_client, staff_client, sample, monkeypatch):
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

    missing_field = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "missing",
            "term": "in",
        },
    )
    assert missing_field.status_code == 404

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "autocomplete_fields", ("name",))
    non_relation_field = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "name",
            "term": "Cam",
        },
    )
    assert non_relation_field.status_code == 404
