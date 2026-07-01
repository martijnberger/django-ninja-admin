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

from django_ninja_admin import ModelAdmin, NinjaAdminSite, TabularInline, site
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from tests.testapp.models import Category, Product, ProductImage, ProductReview


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
    product = Product.objects.create(name="Alpha", category=category, price="12.50", description="Nice camera")
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
    } <= set(components)
    assert set(components["ProductAdminCreateData"]["required"]) == {"name", "category", "price", "stock_status"}
    assert "required" not in components["ProductAdminPartialUpdateData"]
    assert components["ProductAdminCreateData"]["properties"]["stock_status"]["type"] == "string"
    price_options = components["ProductAdminCreateData"]["properties"]["price"]["anyOf"]
    assert any(option.get("type") == "number" for option in price_options)
    assert components["ProductAdminBulkRow"]["required"] == ["pk"]
    assert components["ProductAdminBulkRow"]["additionalProperties"] is False
    assert "testapp.productimage" in components["ProductAdminInlinePayload"]["properties"]
    assert components["ProductImageInlineAddRow"]["required"] == ["title"]
    assert components["ProductImageInlineChangeRow"]["required"] == ["pk"]
    assert components["ProductAdminActionPayload"]["properties"]["action"]["enum"] == [
        "delete_selected",
        "mark_out_of_stock",
        "report_names",
    ]


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

    stats = admin_client.get("/custom-admin/testapp/product/stats")
    assert stats.status_code == 200
    assert stats.json() == {"count": 2}

    denied = staff_client().get("/custom-admin/testapp/product/stats")
    assert denied.status_code == 403

    schema = admin_client.get("/custom-admin/openapi.json").json()
    assert schema["paths"]["/custom-admin/status"]["get"]["operationId"] == "custom_site_status"
    assert schema["paths"]["/custom-admin/testapp/product/stats"]["get"]["operationId"] == "custom_product_stats"


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
    assert fields_by_name["price"]["attrs"]["max_digits"] == 8
    assert fields_by_name["price"]["attrs"]["decimal_places"] == 2
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]
    assert fields_by_name["upper_name"]["attrs"]["read_only"] is True

    created = admin_client.post(
        "/admin-api/testapp/product",
        data={
            "data": {
                "name": "Gamma",
                "category": category.pk,
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
    change_entry = LogEntry.objects.filter(object_id=str(created_id), action_flag=CHANGE).latest("action_time")
    assert json.loads(change_entry.change_message) == [{"changed": {"fields": ["Price"]}}]

    history = admin_client.get("/admin-api/history?app_label=testapp&model=product")
    assert history.status_code == 200
    assert history.json()["pagination"]["count"] >= 2

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")
    assert deleted.status_code == 204


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
