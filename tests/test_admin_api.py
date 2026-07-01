import json
from datetime import datetime

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone
from ninja.security import SessionAuthIsStaff

from django_ninja_admin import VERTICAL, ModelAdmin, NinjaAdminSite, TabularInline, site
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from tests.testapp.models import Category, Product, ProductImage, ProductReview, Tag


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_user("admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def staff_client(db):
    user_count = 0

    def make_client(*permission_codenames):
        nonlocal user_count
        user_count += 1
        user = get_user_model().objects.create_user(f"staff-{user_count}", password="pw", is_staff=True)
        user.user_permissions.set(Permission.objects.filter(codename__in=permission_codenames))
        client = Client()
        client.force_login(user)
        return client

    return make_client


@pytest.fixture
def sample(db):
    category = Category.objects.create(name="Cameras")
    featured = Tag.objects.create(name="Featured")
    compact = Tag.objects.create(name="Compact")
    product = Product.objects.create(
        name="Alpha",
        category=category,
        price="12.50",
        description="Nice camera",
        manual="manuals/alpha.pdf",
    )
    product.tags.set([featured, compact])
    Product.objects.create(name="Beta", category=category, price="3.00", stock_status="out_of_stock")
    ProductImage.objects.create(product=product, title="Front")
    return product


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
    assert {
        "ProductAdminCreateData",
        "ProductAdminCreatePayload",
        "ProductAdminPartialUpdateData",
        "ProductAdminPartialUpdatePayload",
        "ProductAdminBulkPayload",
        "ProductAdminBulkRow",
        "ProductAdminInlinePayload",
        "ProductImageInlineOperations",
        "ProductImageInlineAddRow",
        "ProductImageInlineChangeRow",
        "ProductAdminActionPayload",
        "FileFieldValue",
    } <= set(components)
    assert components["ProductAdminOut"]["properties"]["manual"] == {
        "anyOf": [{"$ref": "#/components/schemas/FileFieldValue"}, {"type": "null"}]
    }
    assert set(components["ProductAdminCreateData"]["required"]) == {"name", "category", "price", "stock_status"}
    assert "required" not in components["ProductAdminPartialUpdateData"]
    assert components["ProductAdminCreateData"]["properties"]["stock_status"]["type"] == "string"
    tags_options = components["ProductAdminCreateData"]["properties"]["tags"]["anyOf"]
    tags_schema = next(option for option in tags_options if option.get("type") == "array")
    assert {option["type"] for option in tags_schema["items"]["anyOf"]} == {"integer", "string"}
    price_options = components["ProductAdminCreateData"]["properties"]["price"]["anyOf"]
    assert any(option.get("type") == "number" for option in price_options)
    assert components["ProductAdminBulkRow"]["required"] == ["pk"]
    assert components["ProductAdminBulkRow"]["additionalProperties"] is False
    assert "testapp.productimage" in components["ProductAdminInlinePayload"]["properties"]
    assert components["ProductImageInlineAddRow"]["required"] == ["title"]
    assert components["ProductImageInlineChangeRow"]["required"] == ["pk"]
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
    action_response_schema = schema_body["paths"]["/admin-api/testapp/product/actions"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert {"$ref": "#/components/schemas/StockStatusActionResult"} in action_response_schema["anyOf"]


def test_openapi_model_route_contracts_are_semantic_and_stable(admin_client, sample):
    schema = admin_client.get("/admin-api/openapi.json").json()
    paths = schema["paths"]

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

    for path, method, statuses in [
        ("/admin-api/testapp/product", "get", {"400", "403", "404"}),
        ("/admin-api/testapp/product", "post", {"400", "403", "422"}),
        ("/admin-api/testapp/product/form", "get", {"403"}),
        ("/admin-api/testapp/product/actions", "post", {"400", "403", "409", "422"}),
        ("/admin-api/testapp/product/bulk", "put", {"400", "403", "422"}),
        ("/admin-api/testapp/product/{object_id}", "get", {"400", "403", "404"}),
        ("/admin-api/testapp/product/{object_id}", "patch", {"400", "403", "404", "422"}),
        ("/admin-api/testapp/product/{object_id}", "put", {"400", "403", "404", "422"}),
        ("/admin-api/testapp/product/{object_id}", "delete", {"400", "403", "404", "409"}),
        ("/admin-api/testapp/product/{object_id}/form", "get", {"400", "403", "404"}),
    ]:
        operation = paths[path][method]
        assert statuses <= set(operation["responses"])
        for status in statuses:
            assert _response_schema_ref(operation, status) == "#/components/schemas/ErrorResponse"
    delete_success_schema = (
        paths["/admin-api/testapp/product/{object_id}"]["delete"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
    )
    assert delete_success_schema["type"] == "object"
    assert delete_success_schema["additionalProperties"] is True


def _request_schema_ref(operation):
    return operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def test_admin_checks_accept_valid_test_admins(db):
    errors = site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert errors == []


def test_admin_checks_report_invalid_model_admin_configuration(db):
    class BadInline(TabularInline):
        model = Category

    class BadProductAdmin(ModelAdmin):
        list_display = ("missing", "name")
        list_display_links = ("name",)
        list_editable = ("name",)
        list_filter = ("missing_filter",)
        search_fields = ("category__missing",)
        ordering = ("missing_ordering",)
        date_hierarchy = "name"
        autocomplete_fields = ("stock_status",)
        actions = ["missing_action"]
        inlines = [BadInline]

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadProductAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])
    error_ids = {error.id for error in errors}

    assert {
        "django_ninja_admin.E004",
        "django_ninja_admin.E007",
        "django_ninja_admin.E019",
        "django_ninja_admin.E021",
        "django_ninja_admin.E025",
        "django_ninja_admin.E029",
        "django_ninja_admin.E030",
        "django_ninja_admin.E033",
    } <= error_ids


def test_admin_checks_report_form_widget_option_conflicts(db):
    class ConflictProductAdmin(ModelAdmin):
        autocomplete_fields = ("category",)
        raw_id_fields = ("category",)
        filter_horizontal = ("tags",)
        filter_vertical = ("tags",)
        radio_fields = {"category": 999, "price": VERTICAL}

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ConflictProductAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])
    error_ids = {error.id for error in errors}

    assert {
        "django_ninja_admin.E037",
        "django_ninja_admin.E038",
        "django_ninja_admin.E039",
        "django_ninja_admin.E040",
        "django_ninja_admin.E041",
        "django_ninja_admin.E042",
    } <= error_ids


def test_admin_checks_validate_radio_fields_shape(db):
    class BadRadioShapeAdmin(ModelAdmin):
        radio_fields = ("stock_status",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadRadioShapeAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert {error.id for error in errors} == {"django_ninja_admin.E034"}


def test_changelist_search_filter_and_detail(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["result_count"] == 1
    assert body["rows"][0]["cells"]["name"] == "Alpha"

    filtered = admin_client.get("/admin-api/testapp/product?stock_status=out_of_stock")
    assert filtered.json()["config"]["result_count"] == 1

    exact_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert exact_filtered.status_code == 200
    assert exact_filtered.json()["rows"][0]["cells"]["name"] == "Beta"

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Alpha"
    assert detail.json()["category_label"] == "Cameras"
    assert detail.json()["manual"] == {
        "name": "manuals/alpha.pdf",
        "url": "/media/manuals/alpha.pdf",
    }
    assert set(detail.json()["tags"]) == set(sample.tags.values_list("pk", flat=True))


def test_changelist_filters_ordering_pagination_and_show_all(admin_client, sample):
    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=accessories, price="6.00", description="Stable")

    related_filtered = admin_client.get(f"/admin-api/testapp/product?category__id__exact={sample.category_id}")
    assert related_filtered.status_code == 200
    assert related_filtered.json()["config"]["result_count"] == 2

    simple_filtered = admin_client.get("/admin-api/testapp/product?price_band=cheap")
    assert simple_filtered.status_code == 200
    assert [row["cells"]["name"] for row in simple_filtered.json()["rows"]] == ["Beta", "Tripod"]

    choice_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    stock_filter = next(
        item for item in choice_filtered.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert any(choice["selected"] and choice["display"] == "Out of Stock" for choice in stock_filter["choices"])
    assert any("stock_status__exact=in_stock" in choice["query_string"] for choice in stock_filter["choices"])

    price_ordered = admin_client.get("/admin-api/testapp/product?o=3")
    assert [row["cells"]["name"] for row in price_ordered.json()["rows"]] == ["Beta", "Tripod", "Alpha"]

    display_ordered = admin_client.get("/admin-api/testapp/product?o=-5")
    assert [row["cells"]["name"] for row in display_ordered.json()["rows"]] == ["Tripod", "Beta", "Alpha"]

    paginated = admin_client.get("/admin-api/testapp/product?pp=1&page=2")
    assert paginated.status_code == 200
    assert paginated.json()["config"]["page"] == 2
    assert len(paginated.json()["rows"]) == 1

    show_all = admin_client.get("/admin-api/testapp/product?all=1")
    assert show_all.status_code == 200
    show_all_body = show_all.json()
    assert len(show_all_body["rows"]) == show_all_body["config"]["result_count"]
    assert show_all_body["config"]["show_all"] is True
    assert show_all_body["config"]["can_show_all"] is True
    assert show_all_body["config"]["list_display_links"] == ["name"]
    assert show_all_body["columns"][0]["display_link"] is True
    assert show_all_body["columns"][2]["sortable"] is True
    assert show_all_body["config"]["search_fields"] == ["name", "description", "category__name"]
    price_column = next(column for column in show_all_body["columns"] if column["field"] == "price")
    assert price_column["ascending_query_string"] == "?all=1&o=3"
    assert price_column["descending_query_string"] == "?all=1&o=-3"
    assert price_column["remove_sorting_query_string"] == "?all=1"
    columns_by_field = {column["field"]: column for column in show_all_body["columns"]}
    assert columns_by_field["has_description"]["boolean"] is True
    assert columns_by_field["tagline"]["empty_value_display"] == "No description"
    rows_by_name = {row["cells"]["name"]: row for row in show_all_body["rows"]}
    assert rows_by_name["Alpha"]["cells"]["has_description"] is True
    assert rows_by_name["Alpha"]["cells"]["tagline"] == "Nice camera"
    assert rows_by_name["Beta"]["cells"]["has_description"] is False
    assert rows_by_name["Beta"]["cells"]["tagline"] == "No description"


def test_changelist_auto_selects_related_list_display_fields(db):
    user = get_user_model().objects.create_user("query-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, site.get_model_admin(Product))

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related


def test_changelist_route_uses_model_admin_hook(admin_client, sample, monkeypatch):
    class CustomChangeList(ChangeList):
        def filter_descriptions(self):
            return []

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "get_changelist", lambda request, **kwargs: CustomChangeList)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_custom_site_and_model_admin_views_are_registered_and_permissioned(admin_client, staff_client, sample):
    site_response = admin_client.get("/custom-admin/status")
    assert site_response.status_code == 200
    assert site_response.json() == {"site": "ok"}

    public_response = Client().get("/custom-admin/public-status")
    assert public_response.status_code == 200
    assert public_response.json() == {"public": "ok"}

    hidden_response = admin_client.get("/custom-admin/hidden-status")
    assert hidden_response.status_code == 200
    assert hidden_response.json() == {"hidden": "ok"}

    stats = admin_client.get("/custom-admin/testapp/product/stats")
    assert stats.status_code == 200
    assert stats.json() == {"count": 2}

    denied = staff_client().get("/custom-admin/testapp/product/stats")
    assert denied.status_code == 403

    schema = admin_client.get("/custom-admin/openapi.json").json()
    status_operation = schema["paths"]["/custom-admin/status"]["get"]
    public_operation = schema["paths"]["/custom-admin/public-status"]["get"]
    stats_operation = schema["paths"]["/custom-admin/testapp/product/stats"]["get"]
    assert status_operation["operationId"] == "custom_site_status"
    assert status_operation["tags"] == ["custom.site"]
    assert public_operation["operationId"] == "custom_public_status"
    assert public_operation["tags"] == ["custom.public"]
    assert "security" not in public_operation
    assert stats_operation["operationId"] == "custom_product_stats"
    assert stats_operation["tags"] == ["custom.product"]
    assert stats_operation["summary"] == "Product stats"
    assert stats_operation["description"] == "Custom product statistics."
    assert "/custom-admin/hidden-status" not in schema["paths"]


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_custom_form_class_drives_schema_metadata_and_validation(admin_client, sample):
    schema = admin_client.get("/custom-form-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "manual" not in create_data_schema["properties"]
    assert set(create_data_schema["required"]) == {"name", "category", "price", "stock_status"}

    form = admin_client.get("/custom-form-admin/testapp/product/form")
    assert form.status_code == 200
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["widget_attrs"]["data-admin"] == "custom"
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
    assert invalid.json()["errors"]["form"][0]["param"] == "name"
    assert invalid.json()["errors"]["form"][0]["message"] == ["Forbidden product name."]

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
    assert created_body["data"]["description"] == "Created through custom form [add:save_model]"
    assert created_body["data"]["response_hook"] == "add"
    assert set(created_body["data"]["tags"]) == {*tag_ids, hooked_tag.pk}
    assert set(Product.objects.get(pk=created_id).tags.values_list("pk", flat=True)) == {*tag_ids, hooked_tag.pk}

    changed = admin_client.patch(
        f"/custom-form-admin/testapp/product/{created_id}",
        data={"data": {"description": "Changed through custom form"}},
        content_type="application/json",
    )
    assert changed.status_code == 200
    changed_body = changed.json()
    assert changed_body["data"]["description"] == "Changed through custom form [change:save_model]"
    assert changed_body["data"]["response_hook"] == "change"
    assert set(changed_body["data"]["tags"]) == {*tag_ids, hooked_tag.pk}
    assert Product.objects.get(pk=created_id).description == "Changed through custom form [change:save_model]"

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


def test_changelist_facets_and_date_hierarchy(admin_client, sample):
    alpha_date = timezone.make_aware(datetime(2024, 1, 15, 10, 0))
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=alpha_date)
    Product.objects.filter(pk=beta.pk).update(created_at=timezone.make_aware(datetime(2024, 2, 20, 10, 0)))
    Product.objects.create(
        name="Tripod",
        category=sample.category,
        price="6.00",
        description="Stable",
        created_at=timezone.make_aware(datetime(2025, 3, 5, 10, 0)),
    )

    response = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["show_facets"] is True
    stock_filter = next(item for item in body["config"]["filters"] if item["parameter_name"] == "stock_status__exact")
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["In Stock"] == 2
    assert body["config"]["date_hierarchy"]["level"] == "year"
    assert [choice["value"] for choice in body["config"]["date_hierarchy"]["choices"]] == [2024, 2025]

    by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2024&_facets=1")
    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == 2
    assert by_year.json()["config"]["date_hierarchy"]["level"] == "month"
    assert [choice["value"] for choice in by_year.json()["config"]["date_hierarchy"]["choices"]] == [1, 2]

    by_month = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1")
    assert by_month.status_code == 200
    assert by_month.json()["config"]["result_count"] == 1
    assert by_month.json()["config"]["date_hierarchy"]["level"] == "day"
    assert by_month.json()["config"]["date_hierarchy"]["choices"][0]["value"] == 15


def test_changelist_rejects_bad_lookup_page_and_ordering(admin_client, sample):
    bad_lookup = admin_client.get("/admin-api/testapp/product?category__name=Cameras")
    assert bad_lookup.status_code == 400

    bad_page = admin_client.get("/admin-api/testapp/product?page=0")
    assert bad_page.status_code == 404

    bad_ordering = admin_client.get("/admin-api/testapp/product?o=999")
    assert bad_ordering.status_code == 400

    bad_date_hierarchy = admin_client.get("/admin-api/testapp/product?created_at__month=2")
    assert bad_date_hierarchy.status_code == 400


def test_forms_create_update_delete_and_history(admin_client, sample):
    category = sample.category
    form = admin_client.get("/admin-api/testapp/product/form")
    assert form.status_code == 200
    assert form.json()["form"]["model"] == "testapp.product"
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["category"]["attrs"]["related_model"] == "testapp.category"
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "id"
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
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
    assert fields_by_name["category"]["attrs"]["admin_widget"] == "autocomplete"
    assert fields_by_name["description"]["attrs"]["blank"] is True
    assert fields_by_name["description"]["attrs"]["null"] is False
    assert fields_by_name["description"]["attrs"]["prepopulated_from"] == ["name"]
    assert fields_by_name["manual"]["type"] == "FileField"
    assert fields_by_name["manual"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["manual"]["attrs"]["blank"] is True
    assert fields_by_name["manual"]["attrs"]["upload_to"] == "manuals"
    assert fields_by_name["tags"]["type"] == "ModelMultipleChoiceField"
    assert fields_by_name["tags"]["attrs"]["related_model"] == "testapp.tag"
    assert fields_by_name["tags"]["attrs"]["multiple"] is True
    assert fields_by_name["tags"]["attrs"]["blank"] is True
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"
    assert form.json()["form"]["filter_horizontal"] == ["tags"]

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    assert change_form.status_code == 200
    change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
    assert set(change_fields_by_name["tags"]["attrs"]["value"]) == set(sample.tags.values_list("pk", flat=True))
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

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")
    assert deleted.status_code == 204


def test_form_description_marks_raw_id_and_filter_vertical_widget_modes(db):
    user = get_user_model().objects.create_user("widget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form")
    request.user = user

    class RawWidgetProductAdmin(ModelAdmin):
        raw_id_fields = ("category",)
        filter_vertical = ("tags",)

    model_admin = RawWidgetProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert fields_by_name["category"]["attrs"]["admin_widget"] == "raw_id"
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_vertical"


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


def test_direct_delete_returns_protected_object_details(admin_client, sample):
    ProductReview.objects.create(product=sample, note="Pinned review")

    response = admin_client.delete(f"/admin-api/testapp/product/{sample.pk}")

    assert response.status_code == 409
    body = response.json()
    assert body["errors"][0]["param"] == "object_id"
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


def test_create_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product",
        data={"data": {"category": sample.category_id, "price": "9.00", "stock_status": "in_stock"}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "data.name"


def test_inline_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{}]}}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title"


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
    assert onsite.json()["url"].endswith(f"/products/{sample.pk}/")


def test_actions_use_filtered_changelist_queryset(admin_client, sample):
    response = admin_client.post(
        "/admin-api/testapp/product/actions?stock_status__exact=out_of_stock",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert response.status_code == 200
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
    assert body["protected"] == ["Pinned review"]
    assert Product.objects.filter(pk=sample.pk).exists()


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


def test_inline_mutations_check_inline_permissions(staff_client, sample):
    client = staff_client("change_product")
    image = ProductImage.objects.get(product=sample)

    add_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}}},
        content_type="application/json",
    )
    assert add_response.status_code == 403
    assert ProductImage.objects.filter(product=sample).count() == 1

    change_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert change_response.status_code == 403
    image.refresh_from_db()
    assert image.title == "Front"

    delete_response = client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert delete_response.status_code == 403
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_formset_enforces_max_num(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "add": [
                        {"title": "Side"},
                        {"title": "Back"},
                        {"title": "Detail"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(product=sample).count() == 1


def test_inline_formset_honors_can_delete(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    monkeypatch.setattr(ProductImageInline, "can_delete", False)
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk]}}},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_change_message_includes_inline_operations(admin_client, sample):
    image = sample.images.get()
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Profile"}],
                    "add": [{"title": "Side"}],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    inline_response = response.json()["inlines"]["testapp.productimage"]
    assert "_changed_fields" not in inline_response["change"][0]
    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    change_message = json.loads(change_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in change_message
    assert {"changed": {"name": "product image", "object": "Profile", "fields": ["title"]}} in change_message


def test_inline_mutation_rejects_duplicate_and_conflicting_rows(admin_client, sample):
    image = sample.images.get()

    duplicate_change = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Front A"},
                        {"pk": image.pk, "title": "Front B"},
                    ]
                }
            },
        },
        content_type="application/json",
    )
    assert duplicate_change.status_code == 400
    assert ProductImage.objects.get(pk=image.pk).title == "Front"

    changed_and_deleted = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Front A"}],
                    "delete": [image.pk],
                }
            },
        },
        content_type="application/json",
    )
    assert changed_and_deleted.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk, title="Front").exists()

    duplicate_delete = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"delete": [image.pk, image.pk]}}},
        content_type="application/json",
    )
    assert duplicate_delete.status_code == 400
    assert ProductImage.objects.filter(pk=image.pk).exists()


def test_inline_mutation_rolls_back_parent_save_for_unknown_inline_object(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {"testapp.productimage": {"change": [{"pk": 999999, "title": "Ghost"}]}},
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["errors"]["testapp.productimage"]["change"][0]["message"] == "Unknown inline object."
    sample.refresh_from_db()
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_schema_field_overrides_are_included():
    class ProductAdminWithOverride(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None)}

    admin_site = NinjaAdminSite(include_auth=False)
    model_admin = ProductAdminWithOverride(Product, admin_site)

    assert "custom_note" in model_admin.get_output_schema().model_fields


def test_model_actions_require_model_access(staff_client, sample):
    client = staff_client()
    response = client.post(
        "/admin-api/testapp/product/actions",
        data={"action": "mark_out_of_stock", "selected_ids": [sample.pk]},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_autocomplete_requires_source_model_access_and_declared_field(admin_client, staff_client, sample):
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


def test_view_on_site_requires_model_access(staff_client, sample):
    content_type = ContentType.objects.get_for_model(Product)
    response = staff_client().get(f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}")
    assert response.status_code == 403


def test_unauthenticated_is_rejected(db):
    response = Client().get("/admin-api/apps")
    assert response.status_code in {401, 403}


def test_admin_site_auth_contracts():
    default_site = NinjaAdminSite(include_auth=False)
    assert isinstance(default_site.auth, SessionAuthIsStaff)

    no_auth_site = NinjaAdminSite(auth=None, include_auth=False)
    assert no_auth_site.auth is None

    def custom_auth(request):
        return "token"

    custom_auth_site = NinjaAdminSite(auth=custom_auth, include_auth=False)
    assert custom_auth_site.auth is custom_auth


def test_no_drf_imports():
    import django_ninja_admin

    assert django_ninja_admin.site is not None
    assert LogEntry._meta.db_table == "django_ninja_admin_log"
