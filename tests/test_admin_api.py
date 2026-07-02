import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID

import pytest
from django import forms
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import Storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.core.validators import RegexValidator
from django.db import connection, models
from django.forms.models import BaseInlineFormSet
from django.http import QueryDict
from django.test import Client, RequestFactory, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import CaptureQueriesContext, isolate_apps
from django.utils import timezone
from ninja import Status
from ninja.security import SessionAuthIsStaff
from PIL import Image
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin import (
    VERTICAL,
    AllValuesFieldListFilter,
    EmptyFieldListFilter,
    ModelAdmin,
    NinjaAdminSite,
    RelatedOnlyFieldListFilter,
    ShowFacets,
    SimpleListFilter,
    TabularInline,
    action,
    display,
    register,
    site,
)
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.exceptions import AlreadyRegistered, NotRegistered
from django_ninja_admin.filters import build_filter_spec
from django_ninja_admin.models import ADDITION, CHANGE, LogEntry
from tests.testapp.models import Category, CategorySlugLink, Product, ProductImage, ProductReview, Tag


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
        "ListEditingRow",
        "ProductAdminInlinePayload",
        "ProductImageInlineOperations",
        "ProductImageInlineAddRow",
        "ProductImageInlineChangeRow",
        "ProductAdminActionPayload",
        "FileFieldValue",
        "ImageFieldValue",
    } <= set(components)
    assert components["ProductAdminOut"]["properties"]["manual"] == {
        "anyOf": [{"$ref": "#/components/schemas/FileFieldValue"}, {"type": "null"}]
    }
    assert components["ProductAdminOut"]["properties"]["photo"] == {
        "anyOf": [{"$ref": "#/components/schemas/ImageFieldValue"}, {"type": "null"}]
    }
    mutation_response_schema = components["ProductAdminMutationResponse"]
    assert mutation_response_schema["required"] == ["data"]
    mutation_data_options = mutation_response_schema["properties"]["data"]["anyOf"]
    assert {"$ref": "#/components/schemas/ProductAdminMutationData"} in mutation_data_options
    assert any(option.get("type") == "object" for option in mutation_data_options)
    assert components["ProductAdminMutationData"]["properties"]["name"] == components["ProductAdminOut"]["properties"][
        "name"
    ]
    assert components["ProductAdminMutationData"].get("additionalProperties") is True
    assert schema_body["paths"]["/admin-api/testapp/product"]["post"]["responses"]["201"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminMutationResponse"}
    create_accepted_schema = schema_body["paths"]["/admin-api/testapp/product"]["post"]["responses"]["202"]["content"][
        "application/json"
    ]["schema"]
    assert create_accepted_schema["type"] == "object"
    assert create_accepted_schema["additionalProperties"] is True
    assert schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["patch"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminMutationResponse"}
    update_accepted_schema = schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["patch"]["responses"][
        "202"
    ]["content"]["application/json"]["schema"]
    assert update_accepted_schema["type"] == "object"
    assert update_accepted_schema["additionalProperties"] is True
    delete_accepted_schema = schema_body["paths"]["/admin-api/testapp/product/{object_id}"]["delete"]["responses"][
        "202"
    ]["content"]["application/json"]["schema"]
    assert delete_accepted_schema["type"] == "object"
    assert delete_accepted_schema["additionalProperties"] is True
    assert set(components["ProductAdminCreateData"]["required"]) == {"name", "category", "price", "stock_status"}
    assert "required" not in components["ProductAdminPartialUpdateData"]
    assert components["ProductAdminCreateData"]["properties"]["stock_status"]["type"] == "string"
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
    assert {option["type"] for option in tags_schema["items"]["anyOf"]} == {"integer", "string"}
    price_options = components["ProductAdminCreateData"]["properties"]["price"]["anyOf"]
    assert any(option.get("type") == "number" for option in price_options)
    assert components["ProductAdminBulkRow"]["required"] == ["pk"]
    assert components["ProductAdminBulkRow"]["additionalProperties"] is False
    bulk_response_schema = components["ProductAdminBulkResponse"]
    assert bulk_response_schema["required"] == ["data"]
    assert bulk_response_schema["properties"]["data"]["additionalProperties"] == {
        "$ref": "#/components/schemas/ProductAdminOut"
    }
    assert schema_body["paths"]["/admin-api/testapp/product/bulk"]["put"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/ProductAdminBulkResponse"}
    assert "testapp.productimage" in components["ProductAdminInlinePayload"]["properties"]
    assert components["ProductAdminInlinePayload"]["additionalProperties"] is False
    assert components["ProductImageInlineOperations"]["additionalProperties"] is False
    assert components["ProductImageInlineAddRow"]["required"] == ["title"]
    assert components["ProductImageInlineAddRow"]["additionalProperties"] is False
    assert components["ProductImageInlineChangeRow"]["required"] == ["pk"]
    assert components["ProductImageInlineChangeRow"]["additionalProperties"] is False
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


def test_site_routes_return_typed_auth_errors(db):
    response = Client().get("/admin-api/apps")

    assert response.status_code in {401, 403}
    body = response.json()
    assert set(body) == {"errors"}
    assert body["errors"][0]["param"] == "non_field_errors"


def test_permissions_route_reports_site_permission(admin_client):
    staff_response = admin_client.get("/admin-api/permissions")

    assert staff_response.status_code == 200
    assert staff_response.json() == {
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "has_permission": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_permissions_route_supports_auth_none_sites():
    public_response = Client().get("/public-permissions-admin/permissions")

    assert public_response.status_code == 200
    assert public_response.json() == {
        "is_authenticated": False,
        "is_active": False,
        "is_staff": False,
        "is_superuser": False,
        "has_permission": False,
    }

    schema = Client().get("/public-permissions-admin/openapi.json").json()
    operation = schema["paths"]["/public-permissions-admin/permissions"]["get"]
    assert "security" not in operation
    assert "401" not in operation["responses"]
    assert "403" not in operation["responses"]


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
    assert _response_schema_ref(paths["/admin-api/context"]["get"], "200") == "#/components/schemas/SiteContext"
    permissions_schema = paths["/admin-api/permissions"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert permissions_schema["type"] == "object"
    assert permissions_schema["additionalProperties"] == {"type": "boolean"}
    assert _response_schema_ref(paths["/admin-api/history"]["get"], "200") == "#/components/schemas/HistoryResponse"
    assert components["HistoryItem"]["properties"]["change_message_text"]["type"] == "string"
    assert components["HistoryItem"]["properties"]["model"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert components["HistoryItem"]["properties"]["detail_url"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert _response_schema_ref(paths["/admin-api/autocomplete"]["get"], "200") == (
        "#/components/schemas/AutocompleteResponse"
    )
    assert _response_schema_ref(paths["/admin-api/view-on-site/{content_type_id}/{object_id}"]["get"], "200") == (
        "#/components/schemas/ViewOnSiteResponse"
    )

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


def _uploaded_png(name="photo.png", *, size=(2, 3), color=(255, 0, 0)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/png")


def test_admin_checks_accept_valid_test_admins(db):
    errors = site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert errors == []


def test_site_registration_contracts_and_decorator(db):
    admin_site = NinjaAdminSite(include_auth=False)

    admin_site.register(Category, list_display=("name",))
    assert admin_site.is_registered(Category) is True
    assert admin_site.get_model_admin(Category).list_display == ("name",)

    with pytest.raises(AlreadyRegistered):
        admin_site.register(Category)

    admin_site.unregister(Category)
    assert admin_site.is_registered(Category) is False

    with pytest.raises(NotRegistered):
        admin_site.unregister(Category)

    class AbstractThing(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            abstract = True
            app_label = "testapp"

    with pytest.raises(ImproperlyConfigured):
        admin_site.register(AbstractThing)

    @register(Tag, site=admin_site)
    class RegisteredTagAdmin(ModelAdmin):
        list_display = ("name",)

    assert isinstance(admin_site.get_model_admin(Tag), RegisteredTagAdmin)


@isolate_apps("tests.testapp")
@override_settings(TESTAPP_SWAPPED_MODEL="testapp.ReplacementThing")
def test_site_registration_skips_swapped_models(db):
    class SwappedThing(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"
            swappable = "TESTAPP_SWAPPED_MODEL"

    admin_site = NinjaAdminSite(include_auth=False)

    admin_site.register(SwappedThing)

    assert SwappedThing._meta.swapped == "testapp.ReplacementThing"
    assert admin_site.is_registered(SwappedThing) is False
    with pytest.raises(NotRegistered):
        admin_site.get_model_admin(SwappedThing)


def test_site_action_changes_invalidate_openapi_schema(db):
    admin_site = NinjaAdminSite(include_auth=False, name="action_cache")
    admin_site.register(Product, ModelAdmin)

    def action_mapping():
        schema = admin_site.api.get_openapi_schema(path_prefix="/action-cache")
        return schema["components"]["schemas"]["ProductAdminActionPayload"]["discriminator"]["mapping"]

    before_mapping = action_mapping()
    assert "cache_probe" not in before_mapping

    def cache_probe(model_admin, request, queryset):
        return {"count": queryset.count()}

    cache_probe.short_description = "Cache probe"

    admin_site.add_action(cache_probe)

    after_add_mapping = action_mapping()
    assert "cache_probe" in after_add_mapping
    assert after_add_mapping["cache_probe"] == "#/components/schemas/ProductAdminCacheProbeActionPayload"

    admin_site.disable_action("cache_probe")

    after_disable_mapping = action_mapping()
    assert "cache_probe" not in after_disable_mapping


def test_autodiscover_rolls_back_partial_admin_imports(monkeypatch):
    from django_ninja_admin.utils import module_loading

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Category)
    admin_site._api = object()

    class BrokenAppConfig:
        name = "broken_app"
        module = object()

    def broken_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    def import_broken_admin(module_name):
        assert module_name == "broken_app.admin"
        admin_site.register(Product)
        admin_site.add_action(broken_action)
        raise RuntimeError("broken admin module")

    monkeypatch.setattr(module_loading.apps, "get_app_configs", lambda: [BrokenAppConfig()])
    monkeypatch.setattr(module_loading, "import_module", import_broken_admin)
    monkeypatch.setattr(module_loading, "module_has_submodule", lambda module, module_name: True)

    with pytest.raises(RuntimeError, match="broken admin module"):
        module_loading.autodiscover_modules("admin", register_to=admin_site)

    assert admin_site.is_registered(Category) is True
    assert admin_site.is_registered(Product) is False
    assert "broken_action" not in dict(admin_site.actions)
    assert "broken_action" not in admin_site._global_actions
    assert admin_site._api is None


def test_admin_checks_report_invalid_model_admin_configuration(db):
    class BadInline(TabularInline):
        model = Category

    class BadProductAdmin(ModelAdmin):
        list_display = ("missing", "name", "tags")
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
        "django_ninja_admin.E043",
    } <= error_ids


def test_admin_checks_reject_empty_list_display(db):
    class EmptyListDisplayProductAdmin(ModelAdmin):
        list_display = ()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, EmptyListDisplayProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E091"}
    assert "list_display" in errors[0].msg


def test_admin_checks_validate_inline_count_options(db):
    class ValidInline(TabularInline):
        model = ProductImage
        extra = 2
        min_num = None
        max_num = 5

    class BadInline(TabularInline):
        model = ProductImage
        extra = "2"
        min_num = "0"
        max_num = "5"

    class BadBooleanInline(TabularInline):
        model = ProductImage
        extra = True
        min_num = False
        max_num = True

    class BadRangeInline(TabularInline):
        model = ProductImage
        extra = -1
        min_num = -1
        max_num = -1

    class BadMinMaxInline(TabularInline):
        model = ProductImage
        extra = 0
        min_num = 3
        max_num = 1

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    class BadBooleanInlineProductAdmin(ModelAdmin):
        inlines = [BadBooleanInline]

    class BadRangeInlineProductAdmin(ModelAdmin):
        inlines = [BadRangeInline]

    class BadMinMaxInlineProductAdmin(ModelAdmin):
        inlines = [BadMinMaxInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)
    bad_boolean_site = NinjaAdminSite(include_auth=False)
    bad_boolean_site.register(Product, BadBooleanInlineProductAdmin)
    bad_range_site = NinjaAdminSite(include_auth=False)
    bad_range_site.register(Product, BadRangeInlineProductAdmin)
    bad_min_max_site = NinjaAdminSite(include_auth=False)
    bad_min_max_site.register(Product, BadMinMaxInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    bad_boolean_ids = {error.id for error in bad_boolean_site.get_model_admin(Product).check()}
    bad_range_ids = {error.id for error in bad_range_site.get_model_admin(Product).check()}
    bad_min_max_ids = {error.id for error in bad_min_max_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E073",
            "django_ninja_admin.E074",
            "django_ninja_admin.E075",
            "django_ninja_admin.E106",
            "django_ninja_admin.E107",
            "django_ninja_admin.E108",
            "django_ninja_admin.E109",
        }
    )
    assert bad_ids == {"django_ninja_admin.E073", "django_ninja_admin.E074", "django_ninja_admin.E075"}
    assert bad_boolean_ids == {"django_ninja_admin.E073", "django_ninja_admin.E074", "django_ninja_admin.E075"}
    assert bad_range_ids == {"django_ninja_admin.E106", "django_ninja_admin.E107", "django_ninja_admin.E108"}
    assert bad_min_max_ids == {"django_ninja_admin.E109"}


def test_admin_checks_reject_non_sequence_inlines_option(db):
    class BadInlineShapeProductAdmin(ModelAdmin):
        inlines = "not-a-sequence"

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadInlineShapeProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E081"}


def test_admin_checks_validate_inline_boolean_options(db):
    class ValidInline(TabularInline):
        model = ProductImage
        can_delete = False
        show_change_link = True

    class BadInline(TabularInline):
        model = ProductImage
        can_delete = "no"
        show_change_link = "yes"

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E110", "django_ninja_admin.E111"})
    assert bad_ids == {"django_ninja_admin.E110", "django_ninja_admin.E111"}


def test_admin_checks_validate_inline_form_layout_option_shapes(db):
    class ValidInline(TabularInline):
        model = ProductImage
        fields = ("title",)
        exclude = ()
        readonly_fields = ()
        fieldsets = (("Main", {"fields": ("title",)}),)

    class BadInline(TabularInline):
        model = ProductImage
        fields = "title"
        exclude = "title"
        readonly_fields = "title"
        fieldsets = "main"

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_errors = bad_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E112" not in valid_ids
    assert [error.id for error in bad_errors] == ["django_ninja_admin.E112"] * 4
    assert {error.msg for error in bad_errors} == {
        "The value of 'fields' must be a list or tuple.",
        "The value of 'exclude' must be a list or tuple.",
        "The value of 'readonly_fields' must be a list or tuple.",
        "The value of 'fieldsets' must be a list or tuple.",
    }


def test_admin_checks_validate_inline_form_layout_option_items(db):
    class ValidInline(TabularInline):
        model = ProductImage
        fields = ("title",)
        exclude = ()
        readonly_fields = ()

    class BadItemInline(TabularInline):
        model = ProductImage
        fields = (123,)
        exclude = (123,)
        readonly_fields = (123,)

    class BadUnknownInline(TabularInline):
        model = ProductImage
        fields = ("missing",)
        exclude = ("missing",)
        readonly_fields = ("missing",)

    class BadDuplicateInline(TabularInline):
        model = ProductImage
        fields = ("title", "title")
        exclude = ("title", "title")
        readonly_fields = ("title", "title")

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadItemInlineProductAdmin(ModelAdmin):
        inlines = [BadItemInline]

    class BadUnknownInlineProductAdmin(ModelAdmin):
        inlines = [BadUnknownInline]

    class BadDuplicateInlineProductAdmin(ModelAdmin):
        inlines = [BadDuplicateInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_item_site = NinjaAdminSite(include_auth=False)
    bad_item_site.register(Product, BadItemInlineProductAdmin)
    bad_unknown_site = NinjaAdminSite(include_auth=False)
    bad_unknown_site.register(Product, BadUnknownInlineProductAdmin)
    bad_duplicate_site = NinjaAdminSite(include_auth=False)
    bad_duplicate_site.register(Product, BadDuplicateInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_item_ids = [error.id for error in bad_item_site.get_model_admin(Product).check()]
    bad_unknown_ids = [error.id for error in bad_unknown_site.get_model_admin(Product).check()]
    bad_duplicate_ids = [error.id for error in bad_duplicate_site.get_model_admin(Product).check()]

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E113",
            "django_ninja_admin.E114",
            "django_ninja_admin.E115",
            "django_ninja_admin.E116",
        }
    )
    assert bad_item_ids == ["django_ninja_admin.E113", "django_ninja_admin.E113", "django_ninja_admin.E116"]
    assert bad_unknown_ids == ["django_ninja_admin.E114", "django_ninja_admin.E114", "django_ninja_admin.E116"]
    assert bad_duplicate_ids == ["django_ninja_admin.E115", "django_ninja_admin.E115", "django_ninja_admin.E115"]


def test_admin_checks_validate_inline_fieldsets_items(db):
    class ValidInline(TabularInline):
        model = ProductImage
        fieldsets = (("Main", {"fields": ("title",)}),)

    class BadInline(TabularInline):
        model = ProductImage
        fieldsets = (
            ("MissingFields", {}),
            ("BadOptions", []),
            ("BadFields", {"fields": "title"}),
            ("BadItem", {"fields": (123,)}),
            ("Unknown", {"fields": ("missing",)}),
            ("Duplicate", {"fields": ("title", "title")}),
        )

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = [error.id for error in bad_site.get_model_admin(Product).check()]

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E113",
            "django_ninja_admin.E114",
            "django_ninja_admin.E115",
            "django_ninja_admin.E117",
        }
    )
    assert bad_ids == [
        "django_ninja_admin.E117",
        "django_ninja_admin.E117",
        "django_ninja_admin.E117",
        "django_ninja_admin.E113",
        "django_ninja_admin.E114",
        "django_ninja_admin.E115",
    ]


def test_inline_admin_supports_custom_formset_classes(db):
    class CustomInlineFormSet(BaseInlineFormSet):
        pass

    class ValidInline(TabularInline):
        model = ProductImage
        formset = CustomInlineFormSet

    class BadInline(TabularInline):
        model = ProductImage
        formset = forms.Form

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    inline = valid_site.get_model_admin(Product).get_inline_instances(None, check_permissions=False)[0]
    formset_class = inline.get_formset(RequestFactory().get("/"))
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert issubclass(formset_class, CustomInlineFormSet)
    assert "django_ninja_admin.E076" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E076"}


def test_admin_checks_reject_inline_excluding_parent_foreign_key(db):
    class ValidInline(TabularInline):
        model = ProductImage
        exclude = ("title",)

    class BadInline(TabularInline):
        model = ProductImage
        exclude = ("product",)

    class ValidInlineProductAdmin(ModelAdmin):
        inlines = [ValidInline]

    class BadInlineProductAdmin(ModelAdmin):
        inlines = [BadInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidInlineProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadInlineProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_errors = bad_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E077" not in valid_ids
    assert {error.id for error in bad_errors} == {"django_ninja_admin.E077"}
    assert "parent foreign key field 'product'" in bad_errors[0].msg


def test_admin_checks_reject_reverse_relation_in_list_display(db):
    class ReverseRelationProductAdmin(ModelAdmin):
        list_display = ("name", "reviews")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ReverseRelationProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E043"}
    assert "many-to-many or reverse field" in errors[0].msg


def test_admin_checks_allow_single_valued_relation_path_in_list_display(db):
    class RelationPathProductAdmin(ModelAdmin):
        list_display = ("name", "category__name")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelationPathProductAdmin)

    error_ids = {error.id for error in admin_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E003", "django_ninja_admin.E004", "django_ninja_admin.E043"})


def test_admin_checks_validate_action_permission_hooks(db):
    @action(permissions=["change"])
    def valid_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    @action(permissions=["publish"])
    def custom_permission_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    @action(permissions=["typo"])
    def bad_action(model_admin, request, queryset):
        return {"count": queryset.count()}

    class ValidActionProductAdmin(ModelAdmin):
        actions = [valid_action, custom_permission_action]

        def has_publish_permission(self, request):
            return True

    class BadActionProductAdmin(ModelAdmin):
        actions = [bad_action]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidActionProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadActionProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E064" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E064"}


def test_admin_checks_reject_non_sequence_actions_option(db):
    class BadActionsShapeProductAdmin(ModelAdmin):
        actions = "delete_selected"

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadActionsShapeProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E082"}


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


def test_admin_checks_validate_list_select_related(db):
    class ValidProductAdmin(ModelAdmin):
        list_select_related = ("category",)

    class BadTypeProductAdmin(ModelAdmin):
        list_select_related = "category"

    class BadPathProductAdmin(ModelAdmin):
        list_select_related = ("tags", "price", "missing")

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidProductAdmin)
    valid_errors = valid_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E045", "django_ninja_admin.E046"})

    bad_type_site = NinjaAdminSite(include_auth=False)
    bad_type_site.register(Product, BadTypeProductAdmin)
    bad_type_errors = bad_type_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_type_errors} == {"django_ninja_admin.E045"}

    bad_path_site = NinjaAdminSite(include_auth=False)
    bad_path_site.register(Product, BadPathProductAdmin)
    bad_path_errors = bad_path_site.check(app_configs=[django_apps.get_app_config("testapp")])
    assert {error.id for error in bad_path_errors} == {"django_ninja_admin.E046"}
    assert len(bad_path_errors) == 3


def test_admin_checks_validate_sortable_by(db):
    class ValidSortableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        sortable_by = ("name",)

    class BadShapeProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = "name"

    class BadItemsProductAdmin(ModelAdmin):
        list_display = ("name",)
        sortable_by = (123, "price")

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSortableProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_items_site = NinjaAdminSite(include_auth=False)
    bad_items_site.register(Product, BadItemsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_items_ids = {error.id for error in bad_items_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E055", "django_ninja_admin.E056", "django_ninja_admin.E057"})
    assert bad_shape_ids == {"django_ninja_admin.E055"}
    assert bad_items_ids == {"django_ninja_admin.E056", "django_ninja_admin.E057"}


def test_admin_checks_validate_pagination_options(db):
    class ValidPaginationProductAdmin(ModelAdmin):
        list_per_page = 25
        list_max_show_all = 250

    class BadPaginationProductAdmin(ModelAdmin):
        list_per_page = "25"
        list_max_show_all = "250"

    class BadBooleanPaginationProductAdmin(ModelAdmin):
        list_per_page = True
        list_max_show_all = False

    class BadRangePaginationProductAdmin(ModelAdmin):
        list_per_page = 0
        list_max_show_all = -1

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPaginationProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadPaginationProductAdmin)
    bad_boolean_site = NinjaAdminSite(include_auth=False)
    bad_boolean_site.register(Product, BadBooleanPaginationProductAdmin)
    bad_range_site = NinjaAdminSite(include_auth=False)
    bad_range_site.register(Product, BadRangePaginationProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    bad_boolean_ids = {error.id for error in bad_boolean_site.get_model_admin(Product).check()}
    bad_range_ids = {error.id for error in bad_range_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E067",
            "django_ninja_admin.E068",
            "django_ninja_admin.E104",
            "django_ninja_admin.E105",
        }
    )
    assert bad_ids == {"django_ninja_admin.E067", "django_ninja_admin.E068"}
    assert bad_boolean_ids == {"django_ninja_admin.E067", "django_ninja_admin.E068"}
    assert bad_range_ids == {"django_ninja_admin.E104", "django_ninja_admin.E105"}


def test_admin_checks_validate_paginator_class(db):
    class CustomPaginator(Paginator):
        pass

    class ValidPaginatorProductAdmin(ModelAdmin):
        paginator = CustomPaginator

    class BadPaginatorProductAdmin(ModelAdmin):
        paginator = object()

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPaginatorProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadPaginatorProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E090" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E090"}


def test_admin_checks_validate_boolean_options(db):
    class CallableViewOnSiteProductAdmin(ModelAdmin):
        save_as = True
        save_as_continue = True
        save_on_top = False
        actions_on_top = True
        actions_on_bottom = False
        actions_selection_counter = True
        show_full_result_count = True
        view_on_site = staticmethod(lambda obj: f"/products/{obj.pk}/")

    class BadBooleanOptionsProductAdmin(ModelAdmin):
        save_as = "yes"
        save_as_continue = "yes"
        save_on_top = "no"
        actions_on_top = "yes"
        actions_on_bottom = "no"
        actions_selection_counter = "yes"
        show_full_result_count = "no"
        view_on_site = "/products/{pk}/"

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, CallableViewOnSiteProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadBooleanOptionsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E069",
            "django_ninja_admin.E070",
            "django_ninja_admin.E071",
            "django_ninja_admin.E083",
            "django_ninja_admin.E084",
            "django_ninja_admin.E085",
            "django_ninja_admin.E086",
            "django_ninja_admin.E087",
        }
    )
    assert bad_ids == {
        "django_ninja_admin.E069",
        "django_ninja_admin.E070",
        "django_ninja_admin.E071",
        "django_ninja_admin.E083",
        "django_ninja_admin.E084",
        "django_ninja_admin.E085",
        "django_ninja_admin.E086",
        "django_ninja_admin.E087",
    }


def test_admin_checks_reject_mixed_random_ordering(db):
    class RandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?",)

    class MixedRandomOrderingProductAdmin(ModelAdmin):
        ordering = ("?", "name")

    random_site = NinjaAdminSite(include_auth=False)
    random_site.register(Product, RandomOrderingProductAdmin)
    mixed_site = NinjaAdminSite(include_auth=False)
    mixed_site.register(Product, MixedRandomOrderingProductAdmin)

    random_ids = {error.id for error in random_site.get_model_admin(Product).check()}
    mixed_errors = mixed_site.get_model_admin(Product).check()

    assert "django_ninja_admin.E072" not in random_ids
    assert {error.id for error in mixed_errors} == {"django_ninja_admin.E072"}
    assert mixed_errors[0].hint == 'Either remove the "?", or remove the other fields.'


def test_admin_checks_validate_show_facets_option(db):
    class ValidFacetsProductAdmin(ModelAdmin):
        show_facets = ShowFacets.ALWAYS

    class BadFacetsProductAdmin(ModelAdmin):
        show_facets = "ALWAYS"

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFacetsProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadFacetsProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E088" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E088"}


def test_admin_checks_validate_search_help_text_option(db):
    class ValidSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = "Search by product name."

    class BadSearchHelpTextProductAdmin(ModelAdmin):
        search_help_text = 123

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSearchHelpTextProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadSearchHelpTextProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E089" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E089"}


def test_admin_checks_validate_empty_value_display_option(db):
    class ValidEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = "No value"

    class BadEmptyValueProductAdmin(ModelAdmin):
        empty_value_display = 123

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidEmptyValueProductAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadEmptyValueProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E097" not in valid_ids
    assert bad_ids == {"django_ninja_admin.E097"}


def test_admin_checks_allow_relation_path_date_hierarchy(db):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"

    class BadDateHierarchyProductAdmin(ModelAdmin):
        date_hierarchy = 123

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(ProductImage, RelatedDateHierarchyImageAdmin)
    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadDateHierarchyProductAdmin)

    error_ids = {error.id for error in admin_site.get_model_admin(ProductImage).check()}
    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}

    assert error_ids.isdisjoint({"django_ninja_admin.E028", "django_ninja_admin.E029"})
    assert bad_ids == {"django_ninja_admin.E096"}


def test_admin_checks_allow_expression_ordering(db):
    class ExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("name").asc(),)

    class MissingExpressionOrderingProductAdmin(ModelAdmin):
        ordering = (models.F("missing").desc(),)

    expression_site = NinjaAdminSite(include_auth=False)
    expression_site.register(Product, ExpressionOrderingProductAdmin)
    missing_site = NinjaAdminSite(include_auth=False)
    missing_site.register(Product, MissingExpressionOrderingProductAdmin)

    expression_ids = {error.id for error in expression_site.get_model_admin(Product).check()}
    missing_ids = {error.id for error in missing_site.get_model_admin(Product).check()}

    assert expression_ids.isdisjoint({"django_ninja_admin.E020", "django_ninja_admin.E021"})
    assert missing_ids == {"django_ninja_admin.E021"}


def test_admin_checks_validate_field_based_list_filter_classes(db):
    class TupleSimpleFilter(SimpleListFilter):
        title = "tuple simple"
        parameter_name = "tuple_simple"

        def lookups(self, request, model_admin):
            return (("yes", "Yes"),)

    class ValidFieldFilterProductAdmin(ModelAdmin):
        list_filter = (("description", EmptyFieldListFilter),)

    class BadTupleShapeProductAdmin(ModelAdmin):
        list_filter = (("description", EmptyFieldListFilter, "extra"),)

    class BadTupleFilterProductAdmin(ModelAdmin):
        list_filter = (("description", TupleSimpleFilter),)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFieldFilterProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadTupleShapeProductAdmin)
    bad_filter_site = NinjaAdminSite(include_auth=False)
    bad_filter_site.register(Product, BadTupleFilterProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_filter_ids = {error.id for error in bad_filter_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E017" not in valid_ids
    assert bad_shape_ids == {"django_ninja_admin.E017"}
    assert bad_filter_ids == {"django_ninja_admin.E017"}

    model_admin = valid_site.get_model_admin(Product)
    request = RequestFactory().get("/")
    with pytest.raises(ImproperlyConfigured, match="must subclass FieldListFilter"):
        build_filter_spec(("description", TupleSimpleFilter), request, request.GET, Product, model_admin)


def test_admin_checks_validate_form_class(db):
    class ProductAdminForm(forms.ModelForm):
        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class ProductImageAdminForm(forms.ModelForm):
        class Meta:
            model = ProductImage
            fields = ("title",)

    class CategoryAdminForm(forms.ModelForm):
        class Meta:
            model = Category
            fields = ("name",)

    class PlainForm(forms.Form):
        name = forms.CharField()

    class ValidFormProductAdmin(ModelAdmin):
        form_class = ProductAdminForm

    class PlainFormProductAdmin(ModelAdmin):
        form_class = PlainForm

    class WrongModelFormProductAdmin(ModelAdmin):
        form_class = CategoryAdminForm

    class ValidFormInline(TabularInline):
        model = ProductImage
        form_class = ProductImageAdminForm

    class PlainFormInline(TabularInline):
        model = ProductImage
        form_class = PlainForm

    class WrongModelFormInline(TabularInline):
        model = ProductImage
        form_class = ProductAdminForm

    class ValidInlineFormProductAdmin(ModelAdmin):
        inlines = [ValidFormInline]

    class PlainInlineFormProductAdmin(ModelAdmin):
        inlines = [PlainFormInline]

    class WrongModelInlineFormProductAdmin(ModelAdmin):
        inlines = [WrongModelFormInline]

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFormProductAdmin)
    plain_site = NinjaAdminSite(include_auth=False)
    plain_site.register(Product, PlainFormProductAdmin)
    wrong_model_site = NinjaAdminSite(include_auth=False)
    wrong_model_site.register(Product, WrongModelFormProductAdmin)
    valid_inline_site = NinjaAdminSite(include_auth=False)
    valid_inline_site.register(Product, ValidInlineFormProductAdmin)
    plain_inline_site = NinjaAdminSite(include_auth=False)
    plain_inline_site.register(Product, PlainInlineFormProductAdmin)
    wrong_model_inline_site = NinjaAdminSite(include_auth=False)
    wrong_model_inline_site.register(Product, WrongModelInlineFormProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    plain_ids = {error.id for error in plain_site.get_model_admin(Product).check()}
    wrong_model_ids = {error.id for error in wrong_model_site.get_model_admin(Product).check()}
    valid_inline_ids = {error.id for error in valid_inline_site.get_model_admin(Product).check()}
    plain_inline_ids = {error.id for error in plain_inline_site.get_model_admin(Product).check()}
    wrong_model_inline_ids = {error.id for error in wrong_model_inline_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E058", "django_ninja_admin.E059"})
    assert plain_ids == {"django_ninja_admin.E058"}
    assert wrong_model_ids == {"django_ninja_admin.E059"}
    assert valid_inline_ids.isdisjoint({"django_ninja_admin.E058", "django_ninja_admin.E059"})
    assert plain_inline_ids == {"django_ninja_admin.E058"}
    assert wrong_model_inline_ids == {"django_ninja_admin.E059"}


def test_admin_checks_validate_formfield_overrides(db):
    class ValidOverrideProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: {"help_text": "Custom help."}}

    class BadShapeProductAdmin(ModelAdmin):
        formfield_overrides = [(models.TextField, {"help_text": "Custom help."})]

    class BadFieldKeyProductAdmin(ModelAdmin):
        formfield_overrides = {"description": {"help_text": "Custom help."}}

    class BadOverrideValueProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: ["help_text", "Custom help."]}

    class BadOverrideKeyProductAdmin(ModelAdmin):
        formfield_overrides = {models.TextField: {123: "Custom help."}}

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidOverrideProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_field_key_site = NinjaAdminSite(include_auth=False)
    bad_field_key_site.register(Product, BadFieldKeyProductAdmin)
    bad_override_value_site = NinjaAdminSite(include_auth=False)
    bad_override_value_site.register(Product, BadOverrideValueProductAdmin)
    bad_override_key_site = NinjaAdminSite(include_auth=False)
    bad_override_key_site.register(Product, BadOverrideKeyProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_field_key_ids = {error.id for error in bad_field_key_site.get_model_admin(Product).check()}
    bad_override_value_ids = {error.id for error in bad_override_value_site.get_model_admin(Product).check()}
    bad_override_key_ids = {error.id for error in bad_override_key_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E060",
            "django_ninja_admin.E061",
            "django_ninja_admin.E062",
            "django_ninja_admin.E063",
        }
    )
    assert bad_shape_ids == {"django_ninja_admin.E060"}
    assert bad_field_key_ids == {"django_ninja_admin.E061"}
    assert bad_override_value_ids == {"django_ninja_admin.E062"}
    assert bad_override_key_ids == {"django_ninja_admin.E063"}


def test_admin_checks_reject_reverse_relation_widget_fields(db):
    class ReviewAdmin(ModelAdmin):
        search_fields = ("note",)

    class ReverseAutocompleteProductAdmin(ModelAdmin):
        autocomplete_fields = ("reviews",)

    class ReverseRawIdProductAdmin(ModelAdmin):
        raw_id_fields = ("reviews",)

    autocomplete_site = NinjaAdminSite(include_auth=False)
    autocomplete_site.register(Product, ReverseAutocompleteProductAdmin)
    autocomplete_site.register(ProductReview, ReviewAdmin)
    raw_id_site = NinjaAdminSite(include_auth=False)
    raw_id_site.register(Product, ReverseRawIdProductAdmin)

    autocomplete_errors = autocomplete_site.get_model_admin(Product).check()
    raw_id_errors = raw_id_site.get_model_admin(Product).check()

    assert {error.id for error in autocomplete_errors} == {"django_ninja_admin.E025"}
    assert {error.id for error in raw_id_errors} == {"django_ninja_admin.E025"}


def test_admin_checks_require_registered_searchable_autocomplete_targets(db):
    class ProductAutocompleteAdmin(ModelAdmin):
        autocomplete_fields = ("category",)

    unregistered_site = NinjaAdminSite(include_auth=False)
    unregistered_site.register(Product, ProductAutocompleteAdmin)

    class UnsearchableCategoryAdmin(ModelAdmin):
        pass

    unsearchable_site = NinjaAdminSite(include_auth=False)
    unsearchable_site.register(Product, ProductAutocompleteAdmin)
    unsearchable_site.register(Category, UnsearchableCategoryAdmin)

    class SearchableCategoryAdmin(ModelAdmin):
        search_fields = ("name",)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ProductAutocompleteAdmin)
    valid_site.register(Category, SearchableCategoryAdmin)

    unregistered_errors = unregistered_site.get_model_admin(Product).check()
    unsearchable_errors = unsearchable_site.get_model_admin(Product).check()
    valid_errors = valid_site.get_model_admin(Product).check()

    assert {error.id for error in unregistered_errors} == {"django_ninja_admin.E026"}
    assert {error.id for error in unsearchable_errors} == {"django_ninja_admin.E027"}
    assert {error.id for error in valid_errors}.isdisjoint({"django_ninja_admin.E026", "django_ninja_admin.E027"})


def test_admin_checks_validate_prepopulated_fields(db):
    class ValidPrepopulatedProductAdmin(ModelAdmin):
        prepopulated_fields = {"description": ("name",)}

    class BadShapeProductAdmin(ModelAdmin):
        prepopulated_fields = [("description", ("name",))]

    class BadTargetProductAdmin(ModelAdmin):
        prepopulated_fields = {
            123: ("name",),
            "missing": ("name",),
            "category": ("name",),
            "created_at": ("name",),
        }

    class BadSourceProductAdmin(ModelAdmin):
        prepopulated_fields = {
            "description": "name",
            "name": (123, "missing"),
        }

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidPrepopulatedProductAdmin)
    bad_shape_site = NinjaAdminSite(include_auth=False)
    bad_shape_site.register(Product, BadShapeProductAdmin)
    bad_target_site = NinjaAdminSite(include_auth=False)
    bad_target_site.register(Product, BadTargetProductAdmin)
    bad_source_site = NinjaAdminSite(include_auth=False)
    bad_source_site.register(Product, BadSourceProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_shape_ids = {error.id for error in bad_shape_site.get_model_admin(Product).check()}
    bad_target_ids = {error.id for error in bad_target_site.get_model_admin(Product).check()}
    bad_source_ids = {error.id for error in bad_source_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {
            "django_ninja_admin.E050",
            "django_ninja_admin.E051",
            "django_ninja_admin.E052",
            "django_ninja_admin.E053",
            "django_ninja_admin.E054",
        }
    )
    assert bad_shape_ids == {"django_ninja_admin.E050"}
    assert bad_target_ids == {"django_ninja_admin.E051", "django_ninja_admin.E052"}
    assert bad_source_ids == {"django_ninja_admin.E053", "django_ninja_admin.E054"}


def test_admin_checks_reject_list_editable_fields_missing_from_generated_form(db):
    class MissingFromFieldsProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        fields = ("name", "category", "price")

    class ExcludedProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        exclude = ("stock_status",)

    class MissingFromFieldsetsProductAdmin(ModelAdmin):
        list_display = ("name", "stock_status")
        list_display_links = ("name",)
        list_editable = ("stock_status",)
        fieldsets = ((None, {"fields": ("name", "category", "price")}),)

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, MissingFromFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, ExcludedProductAdmin)
    fieldsets_site = NinjaAdminSite(include_auth=False)
    fieldsets_site.register(Product, MissingFromFieldsetsProductAdmin)

    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])
    fieldsets_errors = fieldsets_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert "django_ninja_admin.E044" in {error.id for error in fields_errors}
    assert "django_ninja_admin.E044" in {error.id for error in exclude_errors}
    assert "django_ninja_admin.E044" in {error.id for error in fieldsets_errors}


def test_admin_checks_reject_first_list_editable_without_explicit_display_link(db):
    class BadFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_editable = ("stock_status",)

    class ValidFirstEditableProductAdmin(ModelAdmin):
        list_display = ("stock_status", "name")
        list_display_links = ("name",)
        list_editable = ("stock_status",)

    bad_site = NinjaAdminSite(include_auth=False)
    bad_site.register(Product, BadFirstEditableProductAdmin)
    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFirstEditableProductAdmin)

    bad_ids = {error.id for error in bad_site.get_model_admin(Product).check()}
    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}

    assert bad_ids == {"django_ninja_admin.E066"}
    assert valid_ids.isdisjoint({"django_ninja_admin.E007", "django_ninja_admin.E066"})


def test_admin_checks_reject_duplicate_list_editable_fields(db):
    class DuplicateEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = ("price", "price")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, DuplicateEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E093"}


def test_admin_checks_reject_non_string_list_editable_fields(db):
    class BadEditableProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)
        list_editable = (123,)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadEditableProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E094"}


def test_admin_checks_reject_duplicate_list_display_links(db):
    class DuplicateLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name", "name")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, DuplicateLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E079"}


def test_admin_checks_reject_non_string_list_display_links(db):
    class BadLinksProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = (123,)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadLinksProductAdmin)

    errors = admin_site.get_model_admin(Product).check()

    assert {error.id for error in errors} == {"django_ninja_admin.E095"}


def test_admin_checks_validate_fields_and_exclude_items(db):
    class RowFieldsProductAdmin(ModelAdmin):
        fields = (("name", "price"), "category")

    class BadFieldsProductAdmin(ModelAdmin):
        fields = ("name", 123)

    class DuplicateFieldsProductAdmin(ModelAdmin):
        fields = ("name", ("price", "name"))

    class BadExcludeProductAdmin(ModelAdmin):
        exclude = ("missing", 123)

    class DuplicateExcludeProductAdmin(ModelAdmin):
        exclude = ("name", "name")

    row_fields_site = NinjaAdminSite(include_auth=False)
    row_fields_site.register(Product, RowFieldsProductAdmin)
    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, BadFieldsProductAdmin)
    duplicate_fields_site = NinjaAdminSite(include_auth=False)
    duplicate_fields_site.register(Product, DuplicateFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, BadExcludeProductAdmin)
    duplicate_exclude_site = NinjaAdminSite(include_auth=False)
    duplicate_exclude_site.register(Product, DuplicateExcludeProductAdmin)

    row_fields_errors = row_fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    duplicate_fields_errors = duplicate_fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])
    duplicate_exclude_errors = duplicate_exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert row_fields_errors == []
    assert list(row_fields_site.get_model_admin(Product).get_form_class(None).base_fields) == [
        "name",
        "price",
        "category",
    ]
    assert {error.id for error in fields_errors} == {"django_ninja_admin.E048"}
    assert {error.id for error in duplicate_fields_errors} == {"django_ninja_admin.E065"}
    assert {error.id for error in exclude_errors} == {"django_ninja_admin.E048", "django_ninja_admin.E049"}
    assert {error.id for error in duplicate_exclude_errors} == {"django_ninja_admin.E080"}


def test_admin_checks_reject_duplicate_readonly_fields(db):
    def readonly_summary(obj):
        return obj.name

    class ValidReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", readonly_summary)

    class DuplicateNameReadonlyProductAdmin(ModelAdmin):
        readonly_fields = ("name", "name")

    class DuplicateCallableReadonlyProductAdmin(ModelAdmin):
        readonly_fields = (readonly_summary, readonly_summary)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidReadonlyProductAdmin)
    duplicate_name_site = NinjaAdminSite(include_auth=False)
    duplicate_name_site.register(Product, DuplicateNameReadonlyProductAdmin)
    duplicate_callable_site = NinjaAdminSite(include_auth=False)
    duplicate_callable_site.register(Product, DuplicateCallableReadonlyProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    duplicate_name_ids = {error.id for error in duplicate_name_site.get_model_admin(Product).check()}
    duplicate_callable_ids = {error.id for error in duplicate_callable_site.get_model_admin(Product).check()}

    assert "django_ninja_admin.E092" not in valid_ids
    assert duplicate_name_ids == {"django_ninja_admin.E092"}
    assert duplicate_callable_ids == {"django_ninja_admin.E092"}


def test_admin_checks_validate_fieldsets_shape_and_duplicates(db):
    class ValidFieldsetsProductAdmin(ModelAdmin):
        fieldsets = (
            (None, {"fields": (("name", "price"), "category")}),
            ("Advanced", {"fields": ("description",)}),
        )

    class MissingFieldsOptionProductAdmin(ModelAdmin):
        fieldsets = ((None, {"classes": ("collapse",)}),)

    class StringFieldsProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": "name"}),)

    class BadFieldItemProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("name", 123)}),)

    class DuplicateFieldProductAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("name", ("price", "name"))}),)

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFieldsetsProductAdmin)
    missing_site = NinjaAdminSite(include_auth=False)
    missing_site.register(Product, MissingFieldsOptionProductAdmin)
    string_site = NinjaAdminSite(include_auth=False)
    string_site.register(Product, StringFieldsProductAdmin)
    bad_item_site = NinjaAdminSite(include_auth=False)
    bad_item_site.register(Product, BadFieldItemProductAdmin)
    duplicate_site = NinjaAdminSite(include_auth=False)
    duplicate_site.register(Product, DuplicateFieldProductAdmin)

    assert valid_site.check(app_configs=[django_apps.get_app_config("testapp")]) == []
    assert list(valid_site.get_model_admin(Product).get_form_class(None).base_fields) == [
        "name",
        "price",
        "category",
        "description",
    ]
    assert {error.id for error in missing_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in string_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in bad_item_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E013"
    }
    assert {error.id for error in duplicate_site.check(app_configs=[django_apps.get_app_config("testapp")])} == {
        "django_ninja_admin.E064"
    }


def test_admin_checks_validate_radio_fields_shape(db):
    class BadRadioShapeAdmin(ModelAdmin):
        radio_fields = ("stock_status",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, BadRadioShapeAdmin)

    errors = admin_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert {error.id for error in errors} == {"django_ninja_admin.E034"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_widget_modes(db):
    class Article(models.Model):
        title = models.CharField(max_length=100)
        tags = models.ManyToManyField("ArticleTag", through="ArticleTagging")

        class Meta:
            app_label = "testapp"

    class ArticleTag(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "testapp"

    class ArticleTagging(models.Model):
        article = models.ForeignKey(Article, on_delete=models.CASCADE)
        tag = models.ForeignKey(ArticleTag, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class HorizontalArticleAdmin(ModelAdmin):
        filter_horizontal = ("tags",)

    class VerticalArticleAdmin(ModelAdmin):
        filter_vertical = ("tags",)

    horizontal_site = NinjaAdminSite(include_auth=False)
    horizontal_site.register(Article, HorizontalArticleAdmin)
    vertical_site = NinjaAdminSite(include_auth=False)
    vertical_site.register(Article, VerticalArticleAdmin)

    horizontal_errors = horizontal_site.get_model_admin(Article).check()
    vertical_errors = vertical_site.get_model_admin(Article).check()

    assert {error.id for error in horizontal_errors} == {"django_ninja_admin.E047"}
    assert {error.id for error in vertical_errors} == {"django_ninja_admin.E047"}


@isolate_apps("tests.testapp")
def test_admin_checks_reject_manual_through_many_to_many_form_layouts(db):
    class ArticleTag(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "testapp"

    class Article(models.Model):
        title = models.CharField(max_length=20)
        tags = models.ManyToManyField(ArticleTag, through="ArticleTagging")

        class Meta:
            app_label = "testapp"

    class ArticleTagging(models.Model):
        article = models.ForeignKey(Article, on_delete=models.CASCADE)
        tag = models.ForeignKey(ArticleTag, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class FieldsArticleAdmin(ModelAdmin):
        fields = ("title", "tags")

    class FieldsetsArticleAdmin(ModelAdmin):
        fieldsets = ((None, {"fields": ("title", "tags")}),)

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Article, FieldsArticleAdmin)
    fieldsets_site = NinjaAdminSite(include_auth=False)
    fieldsets_site.register(Article, FieldsetsArticleAdmin)

    fields_errors = fields_site.get_model_admin(Article).check()
    fieldsets_errors = fieldsets_site.get_model_admin(Article).check()

    assert {error.id for error in fields_errors} == {"django_ninja_admin.E078"}
    assert {error.id for error in fieldsets_errors} == {"django_ninja_admin.E078"}


def test_changelist_search_filter_and_detail(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["result_count"] == 1
    assert body["config"]["search_term"] == "Alpha"
    assert body["config"]["has_search"] is True
    assert body["config"]["clear_search_query_string"] == "?"
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
    initial = admin_client.get("/admin-api/testapp/product")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert {
        item["parameter_name"] for item in initial_body["config"]["filters"]
    } == {"stock_status__exact", "price_band"}
    assert initial_body["config"]["has_filters"] is True
    assert initial_body["config"]["has_active_filters"] is False
    assert initial_body["config"]["clear_all_filters_query_string"] is None
    assert initial_body["config"]["facets_optional"] is True
    assert initial_body["config"]["add_facets_query_string"] == "?_facets=1"
    assert initial_body["config"]["remove_facets_query_string"] is None
    assert initial_body["config"]["ordering"] == ["name", "-pk"]
    initial_name_column = next(column for column in initial_body["columns"] if column["field"] == "name")
    assert initial_name_column["sorted"] is True
    assert initial_name_column["ascending"] is True
    assert initial_name_column["sort_priority"] == 1
    assert initial_name_column["ascending_query_string"] == "?o=1"
    assert initial_name_column["descending_query_string"] == "?o=-1"
    assert initial_name_column["remove_sorting_query_string"] is None

    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=accessories, price="6.00", description="Stable")

    related_filtered = admin_client.get(f"/admin-api/testapp/product?category__id__exact={sample.category_id}")
    assert related_filtered.status_code == 200
    assert related_filtered.json()["config"]["result_count"] == 2
    assert "category__id__exact" in {
        item["parameter_name"] for item in related_filtered.json()["config"]["filters"]
    }

    simple_filtered = admin_client.get("/admin-api/testapp/product?price_band=cheap")
    assert simple_filtered.status_code == 200
    assert [row["cells"]["name"] for row in simple_filtered.json()["rows"]] == ["Beta", "Tripod"]

    choice_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert choice_filtered.json()["config"]["has_active_filters"] is True
    assert choice_filtered.json()["config"]["clear_all_filters_query_string"] == "?"
    assert choice_filtered.json()["config"]["add_facets_query_string"] == "?stock_status__exact=out_of_stock&_facets=1"
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
    paginated_body = paginated.json()
    assert paginated_body["config"]["page"] == 2
    assert paginated_body["config"]["page_count"] == 3
    assert paginated_body["config"]["has_next"] is True
    assert paginated_body["config"]["has_previous"] is True
    assert paginated_body["config"]["multi_page"] is True
    assert paginated_body["config"]["pagination_required"] is True
    assert paginated_body["config"]["page_range"] == [1, 2, 3]
    assert paginated_body["config"]["page_choices"] == [
        {"display": "1", "page": 1, "selected": False, "query_string": "?pp=1"},
        {"display": "2", "page": 2, "selected": True, "query_string": "?pp=1&p=2"},
        {"display": "3", "page": 3, "selected": False, "query_string": "?pp=1&p=3"},
    ]
    assert len(paginated_body["rows"]) == 1
    assert paginated_body["config"]["page_result_count"] == 1
    assert paginated_body["config"]["result_start_index"] == 2
    assert paginated_body["config"]["result_end_index"] == 2
    assert paginated_body["rows"][0]["index"] == 0
    assert paginated_body["rows"][0]["result_index"] == 2
    assert paginated_body["config"]["first_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["previous_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["next_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["last_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["show_all_query_string"] == "?pp=1&all=1"
    assert paginated_body["config"]["clear_show_all_query_string"] is None

    generated_query_strings = []
    for filter_description in paginated_body["config"]["filters"]:
        generated_query_strings.extend(choice["query_string"] for choice in filter_description["choices"])
    generated_query_strings.extend(
        column["ascending_query_string"]
        for column in paginated_body["columns"]
        if column["ascending_query_string"]
    )
    generated_query_strings.extend(
        choice["query_string"] for choice in paginated_body["config"]["date_hierarchy"]["choices"]
    )
    generated_query_strings.append(paginated_body["config"]["date_hierarchy"]["clear_query_string"])
    for query_string in generated_query_strings:
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params
        assert "p" not in params
    for query_string in (
        paginated_body["config"]["first_page_query_string"],
        paginated_body["config"]["previous_page_query_string"],
        paginated_body["config"]["next_page_query_string"],
        paginated_body["config"]["last_page_query_string"],
        paginated_body["config"]["show_all_query_string"],
        *(choice["query_string"] for choice in paginated_body["config"]["page_choices"] if choice["query_string"]),
    ):
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params

    prefixed_filter = admin_client.get("/admin-api/testapp/product?price__gte=1&pp=1&page=2&o=3")
    assert prefixed_filter.status_code == 200
    prefixed_body = prefixed_filter.json()
    prefixed_price_column = next(column for column in prefixed_body["columns"] if column["field"] == "price")
    assert prefixed_body["config"]["previous_page_query_string"] == "?price__gte=1&pp=1&o=3"
    assert prefixed_body["config"]["next_page_query_string"] == "?price__gte=1&pp=1&o=3&p=3"
    assert prefixed_body["config"]["show_all_query_string"] == "?price__gte=1&pp=1&o=3&all=1"
    assert prefixed_body["config"]["has_active_filters"] is True
    assert prefixed_body["config"]["clear_all_filters_query_string"] == "?pp=1&o=3"
    assert prefixed_body["config"]["search_term"] == ""
    assert prefixed_body["config"]["has_search"] is False
    assert prefixed_body["config"]["clear_search_query_string"] is None
    assert prefixed_price_column["descending_query_string"] == "?price__gte=1&pp=1&o=-3"
    assert prefixed_price_column["remove_sorting_query_string"] == "?price__gte=1&pp=1"
    prefixed_stock_filter = next(
        item for item in prefixed_body["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    prefixed_stock_choice = next(
        choice for choice in prefixed_stock_filter["choices"] if choice["display"] == "In Stock"
    )
    assert prefixed_stock_choice["query_string"] == "?price__gte=1&pp=1&o=3&stock_status__exact=in_stock"

    searched_with_state = admin_client.get("/admin-api/testapp/product?price__gte=1&q=a&pp=1&page=2&o=3")
    assert searched_with_state.status_code == 200
    assert searched_with_state.json()["config"]["search_term"] == "a"
    assert searched_with_state.json()["config"]["has_search"] is True
    assert searched_with_state.json()["config"]["clear_search_query_string"] == "?price__gte=1&pp=1&o=3"

    last_page = admin_client.get("/admin-api/testapp/product?pp=1&page=last")
    assert last_page.status_code == 200
    assert last_page.json()["config"]["page"] == 3
    assert last_page.json()["rows"][0]["cells"]["name"] == "Tripod"

    show_all = admin_client.get("/admin-api/testapp/product?all=1")
    assert show_all.status_code == 200
    show_all_body = show_all.json()
    assert len(show_all_body["rows"]) == show_all_body["config"]["result_count"]
    assert show_all_body["config"]["full_count"] == 3
    assert show_all_body["config"]["page_result_count"] == 3
    assert show_all_body["config"]["result_start_index"] == 1
    assert show_all_body["config"]["result_end_index"] == 3
    assert show_all_body["config"]["show_all"] is True
    assert show_all_body["config"]["can_show_all"] is True
    assert show_all_body["config"]["pagination_required"] is False
    assert show_all_body["config"]["page_range"] == []
    assert show_all_body["config"]["page_choices"] == []
    assert show_all_body["config"]["first_page_query_string"] is None
    assert show_all_body["config"]["previous_page_query_string"] is None
    assert show_all_body["config"]["next_page_query_string"] is None
    assert show_all_body["config"]["last_page_query_string"] is None
    assert show_all_body["config"]["show_all_query_string"] is None
    assert show_all_body["config"]["clear_show_all_query_string"] == "?"
    assert show_all_body["config"]["list_display_links"] == ["name"]
    assert show_all_body["config"]["actions_on_top"] is True
    assert show_all_body["config"]["actions_on_bottom"] is False
    assert show_all_body["config"]["actions_selection_counter"] is True
    assert show_all_body["config"]["show_full_result_count"] is True
    assert show_all_body["config"]["show_admin_actions"] is True
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
    assert columns_by_field["is_expensive"]["headerName"] == "Expensive"
    assert columns_by_field["is_expensive"]["boolean"] is True
    assert columns_by_field["subtitle"]["headerName"] == "Subtitle"
    assert columns_by_field["subtitle"]["empty_value_display"] == "No subtitle"
    rows_by_name = {row["cells"]["name"]: row for row in show_all_body["rows"]}
    assert [row["index"] for row in show_all_body["rows"]] == [0, 1, 2]
    assert [row["result_index"] for row in show_all_body["rows"]] == [1, 2, 3]

    show_all_by_presence = admin_client.get("/admin-api/testapp/product?all=0")
    assert show_all_by_presence.status_code == 200
    show_all_by_presence_body = show_all_by_presence.json()
    assert show_all_by_presence_body["config"]["show_all"] is True
    assert show_all_by_presence_body["config"]["pagination_required"] is False
    assert len(show_all_by_presence_body["rows"]) == show_all_by_presence_body["config"]["result_count"]

    alpha_row = rows_by_name["Alpha"]
    content_type = ContentType.objects.get_for_model(Product)
    assert alpha_row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert alpha_row["delete_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["view_on_site_url"] == f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}"
    assert alpha_row["permissions"] == {
        "has_add_permission": True,
        "has_change_permission": True,
        "has_delete_permission": True,
        "has_view_permission": True,
    }
    assert rows_by_name["Alpha"]["cells"]["has_description"] is True
    assert rows_by_name["Alpha"]["cells"]["tagline"] == "Nice camera"
    assert rows_by_name["Alpha"]["cells"]["is_expensive"] is True
    assert rows_by_name["Alpha"]["cells"]["subtitle"] == "Nice camera"
    assert rows_by_name["Beta"]["cells"]["has_description"] is False
    assert rows_by_name["Beta"]["cells"]["tagline"] == "No description"
    assert rows_by_name["Beta"]["cells"]["is_expensive"] is False
    assert rows_by_name["Beta"]["cells"]["subtitle"] == "No subtitle"

    empty = admin_client.get("/admin-api/testapp/product?q=missing")
    assert empty.status_code == 200
    assert empty.json()["config"]["search_term"] == "missing"
    assert empty.json()["config"]["has_search"] is True
    assert empty.json()["config"]["clear_search_query_string"] == "?"
    assert empty.json()["config"]["result_count"] == 0
    assert empty.json()["config"]["page_result_count"] == 0
    assert empty.json()["config"]["result_start_index"] == 0
    assert empty.json()["config"]["result_end_index"] == 0


def test_changelist_supports_callable_list_display(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    @display(description="Stock badge", ordering="stock_status", boolean=True)
    def stock_badge(obj):
        return obj.stock_status == "in_stock"

    monkeypatch.setattr(product_admin, "list_display", ("name", stock_badge))
    monkeypatch.setattr(product_admin, "sortable_by", (stock_badge,))

    response = admin_client.get("/admin-api/testapp/product?o=-2")

    assert response.status_code == 200
    error_ids = {error.id for error in product_admin.check()}
    assert "django_ninja_admin.E002" not in error_ids
    assert "django_ninja_admin.E057" not in error_ids
    body = response.json()
    stock_column = next(column for column in body["columns"] if column["field"] == "stock_badge")
    assert stock_column["headerName"] == "Stock badge"
    assert stock_column["boolean"] is True
    assert stock_column["sortable"] is True
    assert stock_column["ordering_field"] == "stock_status"
    assert body["config"]["ordering_field_columns"] == {"stock_badge": "2"}
    assert body["rows"][0]["cells"]["name"] == "Beta"
    assert body["rows"][0]["cells"]["stock_badge"] is False
    assert body["rows"][1]["cells"]["name"] == "Alpha"
    assert body["rows"][1]["cells"]["stock_badge"] is True


def test_changelist_supports_relation_path_list_display(admin_client, sample, monkeypatch):
    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Omega", category=accessories, price="1.00")
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_display", ("name", "category__name"))

    response = admin_client.get("/admin-api/testapp/product?o=2")

    assert response.status_code == 200
    body = response.json()
    category_column = next(column for column in body["columns"] if column["field"] == "category__name")
    assert category_column["headerName"] == "Name"
    assert category_column["sortable"] is True
    assert category_column["ordering_field"] == "category__name"
    assert category_column["ordering_index"] == "2"
    assert body["config"]["ordering"] == ["category__name", "-pk"]
    assert body["config"]["ordering_field_columns"] == {"name": "1", "category__name": "2"}
    assert body["rows"][0]["cells"] == {"name": "Omega", "category__name": "Accessories"}
    assert body["rows"][1]["cells"]["category__name"] == "Cameras"


def test_changelist_ordering_adds_deterministic_pk_fallback(admin_client, sample, monkeypatch):
    duplicate = Product.objects.create(name="Alpha", category=sample.category, price="6.00")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["name", "-pk"]
    alpha_ids = [row["id"] for row in body["rows"] if row["cells"]["name"] == "Alpha"]
    assert alpha_ids == [duplicate.pk, sample.pk]

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "ordering", ("id",))

    unique_ordering = admin_client.get("/admin-api/testapp/product")

    assert unique_ordering.status_code == 200
    assert unique_ordering.json()["config"]["ordering"] == ["id"]


def test_changelist_preserves_custom_queryset_ordering(db, sample):
    class QuerysetOrderedProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)

        def get_queryset(self, request):
            return super().get_queryset(request).order_by("-price")

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, QuerysetOrderedProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    user = get_user_model().objects.create_user("queryset-ordering-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, model_admin)

    assert changelist.ordering == ["-price", "-pk"]
    assert [obj.name for obj in changelist.result_list] == ["Alpha", "Gamma", "Beta"]
    price_sort = changelist.column_sort_query_strings("price")
    assert price_sort["sorted"] is True
    assert price_sort["ascending"] is False
    assert price_sort["sort_priority"] == 1
    assert price_sort["remove_sorting_query_string"] is None


def test_changelist_row_metadata_honors_object_permissions(staff_client, sample):
    response = staff_client("view_product").get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["index"] == 0
    assert row["result_index"] == 1
    assert row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert row["delete_url"] is None
    assert row["permissions"] == {
        "has_add_permission": False,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_changelist_action_ui_metadata_follows_model_admin(admin_client, staff_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "actions_on_top", False)
    monkeypatch.setattr(product_admin, "actions_on_bottom", True)
    monkeypatch.setattr(product_admin, "actions_selection_counter", False)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["actions_on_top"] is False
    assert config["actions_on_bottom"] is True
    assert config["actions_selection_counter"] is False
    choices_by_action = {choice["action"]: choice for choice in config["action_choices"]}
    assert choices_by_action["delete_selected"]["permissions"] == ["delete"]
    assert choices_by_action["mark_out_of_stock"]["permissions"] == ["change"]
    assert choices_by_action["report_names"]["permissions"] == ["view"]
    assert choices_by_action["set_stock_status"]["permissions"] == ["change"]
    assert {field["name"] for field in response.json()["action_form"]} == {"action", "selected_ids", "select_across"}

    view_only = staff_client("view_product").get("/admin-api/testapp/product")
    assert view_only.status_code == 200
    assert view_only.json()["config"]["action_choices"] == [
        {"action": "report_names", "description": "Report names", "permissions": ["view"]}
    ]
    action_field = next(field for field in view_only.json()["action_form"] if field["name"] == "action")
    assert action_field["attrs"]["choices"] == [["report_names", "Report names"]]


def test_changelist_exposes_list_editing_row_metadata(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    rows = body["list_editing_rows"]
    legacy_formset = body["list_editing_formset"]

    assert [row["index"] for row in rows] == [0, 1]
    assert [row["pk"] for row in rows] == [row["id"] for row in body["rows"]]
    assert {row["pk_name"] for row in rows} == {"id"}
    assert [[field["name"] for field in row["fields"]] for row in rows] == [["stock_status"], ["stock_status"]]
    assert legacy_formset == [row["fields"] for row in rows]
    assert rows[0]["fields"][0]["attrs"]["value"] == "in_stock"
    assert rows[1]["fields"][0]["attrs"]["value"] == "out_of_stock"
    assert rows[0]["fields"][0]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]


def test_changelist_can_skip_full_result_count(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "show_full_result_count", False)

    response = admin_client.get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["result_count"] == 1
    assert config["full_count"] is None
    assert config["show_full_result_count"] is False
    assert config["show_admin_actions"] is True


def test_choices_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    Product.objects.filter(pk=sample.pk).update(condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["Unspecified"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["New"]["query_string"] == "?condition__exact=new"

    unspecified = admin_client.get("/admin-api/testapp/product?condition__isnull=1")
    assert unspecified.status_code == 200
    unspecified_body = unspecified.json()
    assert unspecified_body["config"]["result_count"] == 1
    assert unspecified_body["rows"][0]["cells"]["name"] == "Beta"
    condition_filter = next(
        item for item in unspecified_body["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    selected_unspecified = next(choice for choice in condition_filter["choices"] if choice["display"] == "Unspecified")
    assert selected_unspecified["selected"] is True

    concrete = admin_client.get("/admin-api/testapp/product?condition__exact=new")
    assert concrete.status_code == 200
    assert concrete.json()["config"]["result_count"] == 1
    assert concrete.json()["rows"][0]["cells"]["name"] == "Alpha"


def test_all_values_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    Product.objects.filter(pk=sample.pk).update(condition="used")
    Product.objects.create(name="Tripod", category=sample.category, price="6.00", condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "condition")
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["-"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["-"]["query_string"] != choices_by_display["All"]["query_string"]

    null_response = admin_client.get(f"/admin-api/testapp/product{choices_by_display['-']['query_string']}")

    assert null_response.status_code == 200
    assert null_response.json()["config"]["result_count"] == 1
    condition_filter = next(item for item in null_response.json()["config"]["filters"] if item["title"] == "condition")
    null_choice = next(choice for choice in condition_filter["choices"] if choice["display"] == "-")
    assert null_choice["selected"] is True


def test_list_filters_reject_invalid_isnull_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    choices_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert choices_response.status_code == 400
    assert choices_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", ("category",))
    related_response = admin_client.get("/admin-api/testapp/product?category__isnull=maybe")
    assert related_response.status_code == 400
    assert related_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "category__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    all_values_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert all_values_response.status_code == 400
    assert all_values_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]


def test_changelist_direct_lookup_params_prepare_in_and_isnull_values(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(condition="new")

    in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk},{beta.pk}")

    assert in_lookup.status_code == 200
    assert in_lookup.json()["config"]["result_count"] == 2

    repeated_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk}")
    assert repeated_in_lookup.status_code == 200
    assert repeated_in_lookup.json()["config"]["result_count"] == 2

    mixed_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk},999999")
    assert mixed_in_lookup.status_code == 200
    assert mixed_in_lookup.json()["config"]["result_count"] == 2

    non_null = admin_client.get("/admin-api/testapp/product?condition__isnull=0")
    assert non_null.status_code == 200
    assert non_null.json()["config"]["result_count"] == 1
    assert non_null.json()["rows"][0]["cells"]["name"] == "Alpha"

    null = admin_client.get("/admin-api/testapp/product?condition__isnull=true")
    assert null.status_code == 200
    assert null.json()["config"]["result_count"] == 1
    assert null.json()["rows"][0]["cells"]["name"] == "Beta"

    invalid_in = admin_client.get("/admin-api/testapp/product?id__in=not-a-number")
    assert invalid_in.status_code == 400
    assert invalid_in.json()["errors"] == [{"message": "Invalid lookup value.", "param": "id__in"}]

    invalid_isnull = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert invalid_isnull.status_code == 400
    assert invalid_isnull.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]


def test_empty_field_list_filter_validates_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("description", EmptyFieldListFilter),))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    description_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "description__isempty"
    )
    choices_by_display = {choice["display"]: choice for choice in description_filter["choices"]}
    assert choices_by_display["Empty"]["query_string"] == "?description__isempty=1"
    assert choices_by_display["Not empty"]["query_string"] == "?description__isempty=0"

    empty = admin_client.get("/admin-api/testapp/product?description__isempty=1")
    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"

    not_empty = admin_client.get("/admin-api/testapp/product?description__isempty=0")
    assert not_empty.status_code == 200
    assert not_empty.json()["config"]["result_count"] == 1
    assert not_empty.json()["rows"][0]["cells"]["name"] == "Alpha"

    invalid = admin_client.get("/admin-api/testapp/product?description__isempty=maybe")
    assert invalid.status_code == 400
    assert invalid.json()["errors"] == [{"message": "Invalid lookup value.", "param": "description__isempty"}]


def test_simple_list_filter_without_lookups_is_hidden(admin_client, sample, monkeypatch):
    class HiddenFilter(SimpleListFilter):
        title = "hidden"
        parameter_name = "hidden"

        def lookups(self, request, model_admin):
            return ()

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (HiddenFilter,))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_related_field_list_filter_includes_many_to_many_empty_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("tags",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    tag_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in tag_filter["choices"]}
    assert choices_by_display["None"]["query_string"] == "?tags__isnull=1"

    empty = admin_client.get("/admin-api/testapp/product?tags__isnull=1")

    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"
    tag_filter = next(item for item in empty.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact")
    selected_none = next(choice for choice in tag_filter["choices"] if choice["display"] == "None")
    assert selected_none["selected"] is True


def test_related_only_list_filter_honors_related_admin_ordering(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    category_admin = site.get_model_admin(Category)
    zooms = Category.objects.create(name="Zooms")
    Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=zooms, price="6.00", description="Stable")
    monkeypatch.setattr(product_admin, "list_filter", (("category", RelatedOnlyFieldListFilter),))
    monkeypatch.setattr(category_admin, "ordering", ("-name",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    category_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "category__id__exact"
    )
    choices = [choice["display"] for choice in category_filter["choices"] if choice["display"] != "All"]
    assert choices == ["Zooms", "Cameras"]


def test_changelist_search_distincts_duplicate_many_to_many_matches(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    match_one = Tag.objects.create(name="Search Match One")
    match_two = Tag.objects.create(name="Search Match Two")
    sample.tags.add(match_one, match_two)
    monkeypatch.setattr(product_admin, "search_fields", ("tags__name",))

    response = admin_client.get("/admin-api/testapp/product?q=Search")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert [row["cells"]["name"] for row in response.json()["rows"]] == ["Alpha"]


def test_changelist_multi_column_ordering_metadata(admin_client, sample):
    Product.objects.create(name="Gamma", category=sample.category, price="3.00")

    response = admin_client.get("/admin-api/testapp/product?o=3,-1")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["price", "-name", "-pk"]
    assert [row["cells"]["name"] for row in body["rows"]][:2] == ["Gamma", "Beta"]

    columns_by_field = {column["field"]: column for column in body["columns"]}
    price_column = columns_by_field["price"]
    name_column = columns_by_field["name"]
    stock_column = columns_by_field["stock_status"]
    assert price_column["sorted"] is True
    assert price_column["ascending"] is True
    assert price_column["sort_priority"] == 1
    assert price_column["ascending_query_string"] == "?o=3,-1"
    assert price_column["descending_query_string"] == "?o=-3,-1"
    assert price_column["remove_sorting_query_string"] == "?o=-1"
    assert name_column["sorted"] is True
    assert name_column["ascending"] is False
    assert name_column["sort_priority"] == 2
    assert name_column["ascending_query_string"] == "?o=1,3"
    assert name_column["descending_query_string"] == "?o=-1,3"
    assert name_column["remove_sorting_query_string"] == "?o=3"
    assert stock_column["sorted"] is False
    assert stock_column["sort_priority"] is None


def test_changelist_search_supports_lookup_suffixes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(
        name="Alphabet",
        category=sample.category,
        price="14.00",
        description="Starts the same",
    )
    Product.objects.create(
        name="Beta Alpha",
        category=sample.category,
        price="5.00",
        description="Contains the word later",
    )

    monkeypatch.setattr(product_admin, "search_fields", ("^name",))
    startswith = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert startswith.status_code == 200
    assert [row["cells"]["name"] for row in startswith.json()["rows"]] == ["Alpha", "Alphabet"]

    monkeypatch.setattr(product_admin, "search_fields", ("=name",))
    iexact = admin_client.get("/admin-api/testapp/product?q=alpha")
    assert iexact.status_code == 200
    assert [row["cells"]["name"] for row in iexact.json()["rows"]] == ["Alpha"]

    monkeypatch.setattr(product_admin, "search_fields", ("category__id__exact",))
    category_exact = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id}")
    assert category_exact.status_code == 200
    assert category_exact.json()["config"]["result_count"] == 4

    padded_category = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id:03d}")
    assert padded_category.status_code == 200
    assert padded_category.json()["config"]["result_count"] == 0


def test_changelist_auto_selects_related_list_display_fields(db):
    user = get_user_model().objects.create_user("query-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, site.get_model_admin(Product))

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related


def test_changelist_auto_selects_related_display_ordering_paths(db, sample):
    @display(description="Category label", ordering="category__name")
    def category_label(obj):
        return obj.category.name

    class RelatedOrderingProductAdmin(ModelAdmin):
        list_display = ("name", category_label)
        ordering = ("name",)

    Category.objects.create(name="Accessories")
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelatedOrderingProductAdmin)
    user = get_user_model().objects.create_user("query-admin-callable", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [category_label(obj) for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_auto_selects_relation_path_list_display_fields(db, sample):
    class RelationPathProductAdmin(ModelAdmin):
        list_display = ("name", "category__name")
        sortable_by = ("name",)
        ordering = ("name",)

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelationPathProductAdmin)
    user = get_user_model().objects.create_user("query-admin-relation-path", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [obj.category.name for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_route_uses_model_admin_hook(admin_client, sample, monkeypatch):
    class CustomChangeList(ChangeList):
        def filter_descriptions(self):
            return []

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "get_changelist", lambda request, **kwargs: CustomChangeList)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_changelist_route_uses_model_admin_paginator_hook(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    calls = {}

    def get_paginator(request, queryset, per_page, orphans=0, allow_empty_first_page=True):
        calls["path"] = request.path
        calls["model"] = queryset.model
        calls["per_page"] = per_page
        calls["orphans"] = orphans
        calls["allow_empty_first_page"] = allow_empty_first_page
        return Paginator(
            queryset,
            per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    monkeypatch.setattr(product_admin, "get_paginator", get_paginator)

    response = admin_client.get("/admin-api/testapp/product?pp=1")

    assert response.status_code == 200
    assert response.json()["config"]["page_count"] == 3
    assert calls == {
        "path": "/admin-api/testapp/product",
        "model": Product,
        "per_page": 1,
        "orphans": 0,
        "allow_empty_first_page": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_custom_site_and_model_admin_views_are_registered_and_permissioned(admin_client, staff_client, sample):
    site_response = admin_client.get("/custom-admin/status")
    assert site_response.status_code == 200
    assert site_response.json() == {"site": "ok"}

    decorated_site_response = admin_client.get("/custom-admin/decorated-status")
    assert decorated_site_response.status_code == 200
    assert decorated_site_response.json() == {"site": "decorated"}

    auto_site_response = admin_client.get("/custom-admin/auto-status")
    assert auto_site_response.status_code == 200
    assert auto_site_response.json() == {"site": "auto"}

    mapped_site_response = admin_client.get("/custom-admin/mapped-status")
    assert mapped_site_response.status_code == 200
    assert mapped_site_response.json() == {"site": "mapped"}

    explicit_multi_get = admin_client.get("/custom-admin/explicit-multi-status")
    explicit_multi_post = admin_client.post("/custom-admin/explicit-multi-status")
    assert explicit_multi_get.status_code == 200
    assert explicit_multi_get.json() == {"site": "explicit-multi"}
    assert explicit_multi_post.status_code == 200
    assert explicit_multi_post.json() == {"site": "explicit-multi"}

    decorated_auto_site_response = admin_client.get("/custom-admin/decorated-auto-status")
    assert decorated_auto_site_response.status_code == 200
    assert decorated_auto_site_response.json() == {"site": "decorated-auto"}

    token_primary = Client().get("/custom-admin/token-status", headers={"X-Primary-Token": "primary"})
    token_secondary = Client().get("/custom-admin/token-status", headers={"X-Secondary-Token": "secondary"})
    token_denied = Client().get("/custom-admin/token-status")
    assert token_primary.status_code == 200
    assert token_primary.json() == {"auth": "primary"}
    assert token_secondary.status_code == 200
    assert token_secondary.json() == {"auth": "secondary"}
    assert token_denied.status_code == 401

    public_response = Client().get("/custom-admin/public-status")
    assert public_response.status_code == 200
    assert public_response.json() == {"public": "ok"}

    hidden_response = admin_client.get("/custom-admin/hidden-status")
    assert hidden_response.status_code == 200
    assert hidden_response.json() == {"hidden": "ok"}

    stats = admin_client.get("/custom-admin/testapp/product/stats")
    assert stats.status_code == 200
    assert stats.json() == {"count": 2}

    decorated_stats = admin_client.get("/custom-admin/testapp/product/decorated-stats")
    assert decorated_stats.status_code == 200
    assert decorated_stats.json() == {"count": 2}

    auto_stats = admin_client.get("/custom-admin/testapp/product/auto-stats")
    assert auto_stats.status_code == 200
    assert auto_stats.json() == {"count": 2}

    auto_multi_get = admin_client.get("/custom-admin/testapp/product/auto-multi-stats")
    auto_multi_post = admin_client.post("/custom-admin/testapp/product/auto-multi-stats")
    assert auto_multi_get.status_code == 200
    assert auto_multi_get.json() == {"count": 2}
    assert auto_multi_post.status_code == 200
    assert auto_multi_post.json() == {"count": 2}

    denied = staff_client().get("/custom-admin/testapp/product/stats")
    assert denied.status_code == 403

    decorated_denied = staff_client().get("/custom-admin/testapp/product/decorated-stats")
    assert decorated_denied.status_code == 403

    schema = admin_client.get("/custom-admin/openapi.json").json()
    status_operation = schema["paths"]["/custom-admin/status"]["get"]
    decorated_status_operation = schema["paths"]["/custom-admin/decorated-status"]["get"]
    auto_status_operation = schema["paths"]["/custom-admin/auto-status"]["get"]
    mapped_status_operation = schema["paths"]["/custom-admin/mapped-status"]["get"]
    explicit_multi_get_operation = schema["paths"]["/custom-admin/explicit-multi-status"]["get"]
    explicit_multi_post_operation = schema["paths"]["/custom-admin/explicit-multi-status"]["post"]
    decorated_auto_status_operation = schema["paths"]["/custom-admin/decorated-auto-status"]["get"]
    token_operation = schema["paths"]["/custom-admin/token-status"]["get"]
    public_operation = schema["paths"]["/custom-admin/public-status"]["get"]
    stats_operation = schema["paths"]["/custom-admin/testapp/product/stats"]["get"]
    decorated_stats_operation = schema["paths"]["/custom-admin/testapp/product/decorated-stats"]["get"]
    auto_stats_operation = schema["paths"]["/custom-admin/testapp/product/auto-stats"]["get"]
    auto_multi_get_operation = schema["paths"]["/custom-admin/testapp/product/auto-multi-stats"]["get"]
    auto_multi_post_operation = schema["paths"]["/custom-admin/testapp/product/auto-multi-stats"]["post"]

    def assert_custom_route_error_responses(operation, *, include_401=True):
        expected_statuses = {"400", "403", "404", "422"}
        if include_401:
            expected_statuses.add("401")
        for status in expected_statuses:
            assert _response_schema_ref(operation, status) == "#/components/schemas/ErrorResponse"

    operation_ids = [
        operation["operationId"]
        for path_item in schema["paths"].values()
        for operation in path_item.values()
        if "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))

    assert status_operation["operationId"] == "custom_site_status"
    assert status_operation["tags"] == ["custom.site"]
    assert status_operation["security"] == [{"SessionAuthIsStaff": []}]
    assert _response_schema_ref(status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(status_operation)
    assert decorated_status_operation["operationId"] == "custom_site_decorated_status"
    assert decorated_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(decorated_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(decorated_status_operation)
    assert auto_status_operation["operationId"] == "custom_get_auto_status"
    assert auto_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(auto_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(auto_status_operation)
    assert mapped_status_operation["operationId"] == "custom_mapped_status"
    assert mapped_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(mapped_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert _response_schema_ref(mapped_status_operation, "418") == "#/components/schemas/ErrorResponse"
    assert_custom_route_error_responses(mapped_status_operation)
    assert explicit_multi_get_operation["operationId"] == "custom_explicit_multi_status_get"
    assert explicit_multi_get_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(explicit_multi_get_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(explicit_multi_get_operation)
    assert explicit_multi_post_operation["operationId"] == "custom_explicit_multi_status_post"
    assert explicit_multi_post_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(explicit_multi_post_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(explicit_multi_post_operation)
    assert decorated_auto_status_operation["operationId"] == "custom_get_decorated_auto_status"
    assert decorated_auto_status_operation["tags"] == ["custom.site"]
    assert _response_schema_ref(decorated_auto_status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert_custom_route_error_responses(decorated_auto_status_operation)
    assert token_operation["operationId"] == "custom_token_status"
    assert token_operation["tags"] == ["custom.auth"]
    assert {"PrimaryTokenAuth": []} in token_operation["security"]
    assert {"SecondaryTokenAuth": []} in token_operation["security"]
    assert _response_schema_ref(token_operation, "200") == "#/components/schemas/AuthStatusResponse"
    assert_custom_route_error_responses(token_operation)
    assert public_operation["operationId"] == "custom_public_status"
    assert public_operation["tags"] == ["custom.public"]
    assert "security" not in public_operation
    assert _response_schema_ref(public_operation, "200") == "#/components/schemas/PublicStatusResponse"
    assert "401" not in public_operation["responses"]
    assert_custom_route_error_responses(public_operation, include_401=False)
    assert stats_operation["operationId"] == "custom_product_stats"
    assert stats_operation["tags"] == ["custom.product"]
    assert stats_operation["summary"] == "Product stats"
    assert stats_operation["description"] == "Custom product statistics."
    assert _response_schema_ref(stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(stats_operation)
    assert decorated_stats_operation["operationId"] == "custom_product_decorated_stats"
    assert decorated_stats_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(decorated_stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(decorated_stats_operation)
    assert auto_stats_operation["operationId"] == "custom_get_testapp_product_auto_stats"
    assert auto_stats_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_stats_operation)
    assert auto_multi_get_operation["operationId"] == "custom_get_testapp_product_auto_multi_stats"
    assert auto_multi_get_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_multi_get_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_multi_get_operation)
    assert auto_multi_post_operation["operationId"] == "custom_post_testapp_product_auto_multi_stats"
    assert auto_multi_post_operation["tags"] == ["custom.product"]
    assert _response_schema_ref(auto_multi_post_operation, "200") == "#/components/schemas/ProductStatsResponse"
    assert_custom_route_error_responses(auto_multi_post_operation)
    assert "/custom-admin/hidden-status" not in schema["paths"]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_site_auth_accepts_ninja_auth_sequences():
    client = Client()

    assert client.get("/multi-auth-admin/whoami").status_code == 401
    primary = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "primary"})
    secondary = client.get("/multi-auth-admin/whoami", headers={"X-Secondary-Token": "secondary"})
    invalid = client.get("/multi-auth-admin/whoami", headers={"X-Primary-Token": "wrong"})

    assert primary.status_code == 200
    assert primary.json() == {"auth": "primary"}
    assert secondary.status_code == 200
    assert secondary.json() == {"auth": "secondary"}
    assert invalid.status_code == 401

    schema = client.get("/multi-auth-admin/openapi.json").json()
    operation = schema["paths"]["/multi-auth-admin/whoami"]["get"]
    assert operation["operationId"] == "multi_auth_whoami"
    assert {"PrimaryTokenAuth": []} in operation["security"]
    assert {"SecondaryTokenAuth": []} in operation["security"]
    assert schema["components"]["securitySchemes"]["PrimaryTokenAuth"]["in"] == "header"
    assert schema["components"]["securitySchemes"]["SecondaryTokenAuth"]["name"] == "X-Secondary-Token"


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_context_uses_site_customization_and_permission_hook(admin_client):
    response = admin_client.get("/context-admin/context")

    assert response.status_code == 200
    body = response.json()
    assert body["site_title"] == "Custom Context Title"
    assert body["site_header"] == "Custom Context Header"
    assert body["site_url"] == "/dashboard/"
    assert body["is_nav_sidebar_enabled"] is False
    assert body["has_permission"] is True
    assert [app["app_label"] for app in body["available_apps"]] == ["testapp"]
    assert [model["model_name"] for model in body["available_apps"][0]["models"]] == ["category"]

    locked_response = admin_client.get("/locked-context-admin/context")

    assert locked_response.status_code == 200
    assert locked_response.json()["has_permission"] is False


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_custom_form_class_drives_schema_metadata_and_validation(admin_client, sample):
    schema = admin_client.get("/custom-form-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "manual" not in create_data_schema["properties"]
    assert set(create_data_schema["required"]) == {"name", "category", "price", "stock_status"}

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
    assert created_body["data"]["description"] == "Created through custom form [add:save_form] [add:save_model]"
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
    assert changed_body["data"]["description"] == "Changed through custom form [change:save_form] [change:save_model]"
    assert changed_body["data"]["response_hook"] == "change"
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


def test_response_hooks_can_return_custom_status(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def response_add(request, obj, form, inline_results):
        return Status(202, {"hook": "add", "id": obj.pk, "name": obj.name})

    def response_change(request, obj, form, inline_results):
        return Status(202, {"hook": "change", "id": obj.pk, "description": obj.description})

    def response_delete(request, obj_display, obj_id):
        return Status(202, {"hook": "delete", "id": obj_id, "display": obj_display})

    monkeypatch.setattr(product_admin, "response_add", response_add)
    monkeypatch.setattr(product_admin, "response_change", response_change)
    monkeypatch.setattr(product_admin, "response_delete", response_delete)

    created = admin_client.post(
        "/admin-api/testapp/product",
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

    changed = admin_client.patch(
        f"/admin-api/testapp/product/{created_id}",
        data={"data": {"description": "Custom status response"}},
        content_type="application/json",
    )

    assert changed.status_code == 202
    assert changed.json() == {
        "hook": "change",
        "id": created_id,
        "description": "Custom status response",
    }
    assert Product.objects.get(pk=created_id).description == "Custom status response"

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")

    assert deleted.status_code == 202
    assert deleted.json() == {"hook": "delete", "id": str(created_id), "display": "Status Hook"}
    assert not Product.objects.filter(pk=created_id).exists()


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
    assert invalid_category.json()["errors"]["form"][0]["param"] == "category"

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


def test_write_schema_uses_richer_pydantic_types_for_form_fields(sample, tmp_path):
    fixture_file = tmp_path / "choice.txt"
    fixture_file.write_text("ok")

    class RichPayloadProductForm(forms.ModelForm):
        metadata = forms.JSONField(required=False)
        tracking_id = forms.UUIDField(required=False)
        host = forms.GenericIPAddressField(required=False)
        contact_email = forms.EmailField(required=False)
        homepage = forms.URLField(required=False)
        file_path = forms.FilePathField(path=str(tmp_path), match=r".*\.txt$", required=False)
        combo_code = forms.ComboField(
            fields=[
                forms.CharField(max_length=5),
                forms.RegexField(regex=r"^[A-Z]+$"),
            ],
            required=False,
        )
        custom_date = forms.DateField(required=False, input_formats=["%d/%m/%Y"])
        custom_time = forms.TimeField(required=False, input_formats=["%H.%M"])
        custom_datetime = forms.DateTimeField(required=False, input_formats=["%d/%m/%Y %H.%M"])
        duration = forms.DurationField(required=False)
        review_required = forms.NullBooleanField(required=False)
        optional_reference = forms.CharField(required=False, empty_value=None)
        release_window = forms.SplitDateTimeField(
            required=False,
            input_date_formats=["%Y-%m-%d"],
            input_time_formats=["%H:%M"],
        )
        bounded_name = forms.CharField(required=False, min_length=3, max_length=8)
        bounded_count = forms.IntegerField(required=False, min_value=2, max_value=5)
        stepped_count = forms.IntegerField(required=False, step_size=2)
        offset_count = forms.IntegerField(required=False, min_value=1, step_size=2)
        bounded_price = forms.DecimalField(
            required=False,
            min_value=Decimal("1.00"),
            max_value=Decimal("9.99"),
            max_digits=4,
            decimal_places=2,
        )
        stepped_price = forms.DecimalField(required=False, step_size=Decimal("0.25"), max_digits=4, decimal_places=2)
        product_code = forms.CharField(
            required=False,
            min_length=3,
            max_length=3,
            validators=[RegexValidator(r"^[A-Z]{3}$")],
        )
        tracked_label = forms.CharField(required=False, show_hidden_initial=True)
        unstripped_code = forms.CharField(
            required=False,
            validators=[RegexValidator(r"^[A-Z]{3}$")],
            strip=False,
        )
        sku = forms.CharField(required=False, validators=[RegexValidator(r"^SKU-[0-9]+$")])
        slug = forms.SlugField(required=False)

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class RichPayloadProductAdmin(ModelAdmin):
        form_class = RichPayloadProductForm

    model_admin = RichPayloadProductAdmin(Product, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_write_schema(None)
    tracking_id = "550e8400-e29b-41d4-a716-446655440000"

    validated = schema.model_validate(
        {
            "name": "Typed payload",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": "in_stock",
            "metadata": {"nested": [1, "two"]},
            "tracking_id": tracking_id,
            "host": "2001:db8::1",
            "contact_email": "buyer@example.com",
            "homepage": "https://example.com/products",
            "file_path": str(fixture_file),
            "combo_code": "ABCDE",
            "custom_date": "01/07/2026",
            "custom_time": "09.30",
            "custom_datetime": "01/07/2026 09.30",
            "duration": "1 02:03:04",
            "review_required": "unknown",
            "optional_reference": "REF-1",
            "release_window": ["2026-07-01", "09:30"],
            "bounded_name": "Camera",
            "bounded_count": 3,
            "stepped_count": 4,
            "offset_count": 3,
            "bounded_price": "4.50",
            "stepped_price": "1.25",
            "product_code": " ABC ",
            "tracked_label": "Camera label",
            "unstripped_code": "XYZ",
            "sku": "SKU-123",
            "slug": "camera-case",
        }
    )

    assert validated.metadata == {"nested": [1, "two"]}
    assert validated.tracking_id.hex == "550e8400e29b41d4a716446655440000"
    assert str(validated.host) == "2001:db8::1"
    assert validated.contact_email == "buyer@example.com"
    assert str(validated.homepage) == "https://example.com/products"
    assert validated.file_path == str(fixture_file)
    assert validated.combo_code == "ABCDE"
    assert validated.custom_date == date(2026, 7, 1)
    assert validated.custom_time == time(9, 30)
    assert validated.custom_datetime.year == 2026
    assert validated.custom_datetime.month == 7
    assert validated.custom_datetime.day == 1
    assert validated.custom_datetime.hour == 9
    assert validated.custom_datetime.minute == 30
    assert validated.custom_datetime.tzinfo is not None
    assert validated.duration == timedelta(days=1, hours=2, minutes=3, seconds=4)
    assert validated.review_required is None
    assert validated.optional_reference == "REF-1"
    assert validated.release_window == (date(2026, 7, 1), time(9, 30))
    assert validated.bounded_name == "Camera"
    assert validated.bounded_count == 3
    assert validated.stepped_count == 4
    assert validated.offset_count == 3
    assert validated.bounded_price == Decimal("4.50")
    assert validated.stepped_price == Decimal("1.25")
    assert validated.product_code == "ABC"
    assert validated.tracked_label == "Camera label"
    assert validated.unstripped_code == "XYZ"
    assert validated.sku == "SKU-123"
    assert validated.slug == "camera-case"

    json_schema = schema.model_json_schema()["properties"]
    assert json_schema["bounded_name"]["anyOf"][0]["maxLength"] == 8
    assert json_schema["bounded_name"]["anyOf"][0]["minLength"] == 3
    assert json_schema["bounded_count"]["anyOf"][0]["maximum"] == 5
    assert json_schema["bounded_count"]["anyOf"][0]["minimum"] == 2
    assert json_schema["stepped_count"]["anyOf"][0]["multipleOf"] == 2
    assert json_schema["offset_count"]["anyOf"][0]["minimum"] == 1
    assert "multipleOf" not in json_schema["offset_count"]["anyOf"][0]
    assert json_schema["contact_email"]["anyOf"][0]["format"] == "email"
    assert json_schema["homepage"]["anyOf"][0]["format"] == "uri"
    assert json_schema["file_path"]["anyOf"][0]["const"] == str(fixture_file)
    assert json_schema["combo_code"]["anyOf"][0]["maxLength"] == 5
    assert json_schema["combo_code"]["anyOf"][0]["pattern"] == "^[A-Z]+$"
    assert json_schema["custom_date"]["anyOf"][0]["format"] == "date"
    assert json_schema["custom_time"]["anyOf"][0]["format"] == "time"
    assert json_schema["custom_datetime"]["anyOf"][0]["format"] == "date-time"
    assert {option["type"] for option in json_schema["review_required"]["anyOf"]} == {"boolean", "null"}
    assert json_schema["release_window"]["anyOf"][0]["prefixItems"] == [
        {"format": "date", "type": "string"},
        {"format": "time", "type": "string"},
    ]
    assert json_schema["bounded_price"]["anyOf"][0]["maximum"] == 9.99
    assert json_schema["bounded_price"]["anyOf"][0]["minimum"] == 1.0
    assert json_schema["bounded_price"]["anyOf"][1]["pattern"]
    assert json_schema["stepped_price"]["anyOf"][0]["multipleOf"] == 0.25
    assert json_schema["product_code"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"
    assert json_schema["unstripped_code"]["anyOf"][0]["pattern"] == "^[A-Z]{3}$"
    assert json_schema["sku"]["anyOf"][0]["pattern"] == "^SKU-[0-9]+$"
    assert json_schema["slug"]["anyOf"][0]["pattern"].endswith(r"\z")

    fields_by_name = {
        field["name"]: field
        for field in model_admin.get_form_fields_description(RequestFactory().get("/"))
    }
    assert fields_by_name["review_required"]["type"] == "NullBooleanField"
    assert fields_by_name["review_required"]["attrs"]["null_boolean"] is True
    assert fields_by_name["review_required"]["attrs"]["widget"] == "NullBooleanSelect"
    name_attrs = fields_by_name["name"]["attrs"]
    assert name_attrs["html_name"] == "name"
    assert name_attrs["auto_id"] == "id_name"
    assert name_attrs["id_for_label"] == "id_name"
    assert fields_by_name["optional_reference"]["attrs"]["empty_value"] is None
    assert fields_by_name["product_code"]["attrs"]["strip"] is True
    tracked_label_attrs = fields_by_name["tracked_label"]["attrs"]
    assert tracked_label_attrs["html_name"] == "tracked_label"
    assert tracked_label_attrs["auto_id"] == "id_tracked_label"
    assert tracked_label_attrs["id_for_label"] == "id_tracked_label"
    assert tracked_label_attrs["html_initial_name"] == "initial-tracked_label"
    assert tracked_label_attrs["html_initial_id"] == "initial-id_tracked_label"
    assert tracked_label_attrs["show_hidden_initial"] is True
    assert tracked_label_attrs["hidden_initial_name"] == "initial-tracked_label"
    assert tracked_label_attrs["hidden_initial_id"] == "initial-id_tracked_label"
    assert tracked_label_attrs["hidden_initial_widget"]["widget"] == "HiddenInput"
    assert tracked_label_attrs["hidden_initial_widget"]["input_type"] == "hidden"
    assert tracked_label_attrs["hidden_initial_widget"]["is_hidden"] is True
    assert fields_by_name["unstripped_code"]["attrs"]["strip"] is False

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "review_required": "maybe",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "unstripped_code": "XYZ",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": "not-a-uuid",
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "custom_date": "2026-07-01",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "stepped_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "offset_count": 4,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "combo_code": "abc",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "stepped_price": "1.30",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "file_path": str(tmp_path / "missing.txt"),
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "release_window": ["2026-07-01", "not-a-time"],
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "contact_email": "not-an-email",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "homepage": "not-a-url",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "not-an-ip",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "not-a-duration",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "No",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 6,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "123.45",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "abc",
                "sku": "SKU-123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "123",
                "slug": "camera-case",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {},
                "tracking_id": tracking_id,
                "host": "2001:db8::1",
                "duration": "1 02:03:04",
                "bounded_name": "Camera",
                "bounded_count": 3,
                "bounded_price": "4.50",
                "product_code": "ABC",
                "sku": "SKU-123",
                "slug": "not a slug",
            }
        )


def test_form_schema_field_overrides_drive_parent_bulk_and_inline_schemas(sample):
    class OverridePayloadProductForm(forms.ModelForm):
        metadata = forms.CharField(required=False)

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status", "metadata")

    class OverridePayloadImageForm(forms.ModelForm):
        details = forms.CharField(required=False)

        class Meta:
            model = ProductImage
            fields = ("title", "details")

    class OverridePayloadInline(TabularInline):
        model = ProductImage
        form_class = OverridePayloadImageForm
        form_schema_field_overrides = {"details": dict[str, int]}

    class OverridePayloadProductAdmin(ModelAdmin):
        form_class = OverridePayloadProductForm
        list_display = ("name", "stock_status")
        list_editable = ("stock_status",)
        form_schema_field_overrides = {"metadata": dict[str, int], "stock_status": bool}
        inlines = [OverridePayloadInline]

    model_admin = OverridePayloadProductAdmin(Product, NinjaAdminSite(include_auth=False))
    create_schema = model_admin.get_write_schema(None)
    validated = create_schema.model_validate(
        {
            "name": "Override payload",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": True,
            "metadata": {"priority": 3},
        }
    )

    assert validated.stock_status is True
    assert validated.metadata == {"priority": 3}
    create_properties = create_schema.model_json_schema()["properties"]
    assert create_properties["stock_status"]["type"] == "boolean"
    assert create_properties["metadata"]["anyOf"][0]["additionalProperties"]["type"] == "integer"

    with pytest.raises(PydanticValidationError):
        create_schema.model_validate(
            {
                "name": "Override payload",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "metadata": {"priority": "high"},
            }
        )

    bulk_schema = model_admin.get_bulk_payload_schema(None)
    bulk_payload = bulk_schema.model_validate({"data": [{"pk": sample.pk, "stock_status": False}]})
    assert bulk_payload.data[0].stock_status is False
    with pytest.raises(PydanticValidationError):
        bulk_schema.model_validate({"data": [{"pk": sample.pk, "stock_status": "in_stock"}]})

    inline = model_admin.get_inline_instances(None, check_permissions=False)[0]
    inline_row_schema = inline.get_inline_row_schema(None)
    inline_row = inline_row_schema.model_validate({"title": "Front", "details": {"priority": 1}})
    assert inline_row.details == {"priority": 1}
    inline_properties = inline_row_schema.model_json_schema()["properties"]
    assert inline_properties["details"]["anyOf"][0]["additionalProperties"]["type"] == "integer"
    with pytest.raises(PydanticValidationError):
        inline_row_schema.model_validate({"title": "Front", "details": {"priority": "high"}})

    request = RequestFactory().get("/")
    fields_by_name = {field["name"]: field for field in model_admin.get_form_fields_description(request)}
    assert fields_by_name["metadata"]["attrs"]["input_schema_override"]["schema"]["additionalProperties"][
        "type"
    ] == "integer"
    assert fields_by_name["stock_status"]["attrs"]["input_schema_override"]["schema"]["type"] == "boolean"
    assert "input_schema_override" not in fields_by_name["name"]["attrs"]

    changelist_fields_by_name = {
        field["name"]: field
        for field in model_admin.get_changelist_form_fields_description(request)
    }
    assert changelist_fields_by_name["stock_status"]["attrs"]["input_schema_override"]["schema"]["type"] == "boolean"

    inline_fields_by_name = {
        field["name"]: field
        for field in inline.get_form_fields_description(request, None)
    }
    assert inline_fields_by_name["details"]["attrs"]["input_schema_override"]["schema"]["additionalProperties"][
        "type"
    ] == "integer"


def test_write_schema_uses_choice_types_for_multiple_choice_fields(sample):
    uuid_choice = "550e8400-e29b-41d4-a716-446655440000"
    other_uuid_choice = "550e8400-e29b-41d4-a716-446655440001"

    class MultiChoiceProductForm(forms.ModelForm):
        status_override = forms.ChoiceField(
            required=False,
            choices=(("draft", "Draft"), ("live", "Live")),
        )
        grouped_status = forms.ChoiceField(
            required=False,
            choices=(
                ("Publishing", (("draft", "Draft"), ("live", "Live"))),
                ("Archive", (("archived", "Archived"),)),
            ),
        )
        numeric_flags = forms.MultipleChoiceField(
            required=False,
            choices=((1, "One"), (2, "Two")),
        )
        mixed_flags = forms.MultipleChoiceField(
            required=False,
            choices=((1, "One"), ("two", "Two")),
        )
        typed_number = forms.TypedChoiceField(
            required=False,
            choices=(("1", "One"), ("2", "Two")),
            coerce=int,
        )
        typed_numbers = forms.TypedMultipleChoiceField(
            required=False,
            choices=(("1", "One"), ("2", "Two")),
            coerce=int,
        )
        typed_decimal = forms.TypedChoiceField(
            required=False,
            choices=(("1.25", "One"), ("2.50", "Two")),
            coerce=Decimal,
        )
        typed_floats = forms.TypedMultipleChoiceField(
            required=False,
            choices=(("1.5", "One"), ("2.5", "Two")),
            coerce=float,
        )
        typed_uuid = forms.TypedChoiceField(
            required=False,
            choices=((uuid_choice, "One"), (other_uuid_choice, "Two")),
            coerce=UUID,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class MultiChoiceProductAdmin(ModelAdmin):
        form_class = MultiChoiceProductForm

    model_admin = MultiChoiceProductAdmin(Product, NinjaAdminSite(include_auth=False))
    schema = model_admin.get_write_schema(None)

    validated = schema.model_validate(
        {
            "name": "Typed choices",
            "category": sample.category_id,
            "price": "9.00",
            "stock_status": "in_stock",
            "status_override": "draft",
            "grouped_status": "archived",
            "numeric_flags": [1, 2],
            "mixed_flags": [1, "two"],
            "typed_number": "1",
            "typed_numbers": ["1", "2"],
            "typed_decimal": "1.25",
            "typed_floats": ["1.5", "2.5"],
            "typed_uuid": uuid_choice,
        }
    )

    json_schema = schema.model_json_schema()["properties"]
    assert json_schema["status_override"]["anyOf"][0]["enum"] == ["draft", "live"]
    assert json_schema["grouped_status"]["anyOf"][0]["enum"] == ["draft", "live", "archived"]
    assert json_schema["numeric_flags"]["anyOf"][0]["items"]["enum"] == [1, 2]
    assert json_schema["mixed_flags"]["anyOf"][0]["items"]["enum"] == [1, "two"]
    assert json_schema["typed_number"]["anyOf"][0]["enum"] == [1, 2]
    assert json_schema["typed_numbers"]["anyOf"][0]["items"]["enum"] == [1, 2]
    assert json_schema["typed_decimal"]["anyOf"][0]["enum"] == ["1.25", "2.50"]
    assert json_schema["typed_floats"]["anyOf"][0]["items"]["enum"] == [1.5, 2.5]
    assert json_schema["typed_uuid"]["anyOf"][0]["enum"] == [uuid_choice, other_uuid_choice]

    fields_by_name = {
        field["name"]: field
        for field in model_admin.get_form_fields_description(RequestFactory().get("/"))
    }
    assert fields_by_name["status_override"]["attrs"]["choices"] == [("draft", "Draft"), ("live", "Live")]
    assert fields_by_name["status_override"]["attrs"]["choice_options"] == [
        {"value": "draft", "raw_value": "draft", "label": "Draft"},
        {"value": "live", "raw_value": "live", "label": "Live"},
    ]
    assert "choice_groups" not in fields_by_name["status_override"]["attrs"]
    assert fields_by_name["grouped_status"]["attrs"]["choices"] == [
        ("draft", "Draft"),
        ("live", "Live"),
        ("archived", "Archived"),
    ]
    assert fields_by_name["grouped_status"]["attrs"]["choice_groups"] == [
        {
            "label": "Publishing",
            "options": [
                {"value": "draft", "raw_value": "draft", "label": "Draft"},
                {"value": "live", "raw_value": "live", "label": "Live"},
            ],
        },
        {
            "label": "Archive",
            "options": [{"value": "archived", "raw_value": "archived", "label": "Archived"}],
        },
    ]
    assert fields_by_name["numeric_flags"]["attrs"]["choices"] == [("1", "One"), ("2", "Two")]
    assert fields_by_name["numeric_flags"]["attrs"]["choice_options"] == [
        {"value": "1", "raw_value": 1, "label": "One"},
        {"value": "2", "raw_value": 2, "label": "Two"},
    ]
    assert fields_by_name["typed_decimal"]["attrs"]["choice_options"] == [
        {"value": "1.25", "raw_value": "1.25", "label": "One"},
        {"value": "2.50", "raw_value": "2.50", "label": "Two"},
    ]

    assert validated.status_override == "draft"
    assert validated.grouped_status == "archived"
    assert validated.numeric_flags == [1, 2]
    assert validated.mixed_flags == [1, "two"]
    assert validated.typed_number == 1
    assert validated.typed_numbers == [1, 2]
    assert validated.typed_decimal == Decimal("1.25")
    assert validated.typed_floats == [1.5, 2.5]
    assert validated.typed_uuid == UUID(uuid_choice)

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": ["one"],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "deleted",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "3",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["3"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "archived",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [3],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": ["three"],
                "typed_number": "1",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "one",
                "typed_numbers": ["1", "2"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "status_override": "draft",
                "grouped_status": "archived",
                "numeric_flags": [1, 2],
                "mixed_flags": [1, "two"],
                "typed_number": "1",
                "typed_numbers": ["one"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_decimal": "3.75",
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_floats": ["3.5"],
            }
        )

    with pytest.raises(PydanticValidationError):
        schema.model_validate(
            {
                "name": "Typed choices",
                "category": sample.category_id,
                "price": "9.00",
                "stock_status": "in_stock",
                "typed_uuid": "550e8400-e29b-41d4-a716-446655440099",
            }
        )


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
    assert body["config"]["facets_optional"] is True
    assert body["config"]["add_facets_query_string"] is None
    assert body["config"]["remove_facets_query_string"] == "?"
    assert body["config"]["has_filters"] is True
    assert body["config"]["has_active_filters"] is False
    assert body["config"]["clear_all_filters_query_string"] is None
    stock_filter = next(item for item in body["config"]["filters"] if item["parameter_name"] == "stock_status__exact")
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["In Stock"] == 2
    assert body["config"]["date_hierarchy"]["level"] == "year"
    assert body["config"]["date_hierarchy"]["field_type"] == "DateTimeField"
    assert body["config"]["date_hierarchy"]["timezone"] == timezone.get_current_timezone_name()
    assert body["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert body["config"]["date_hierarchy"]["back_query_string"] is None
    assert [choice["value"] for choice in body["config"]["date_hierarchy"]["choices"]] == [2024, 2025]

    by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2024&_facets=1")
    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == 2
    assert by_year.json()["config"]["has_active_filters"] is True
    assert by_year.json()["config"]["clear_all_filters_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["remove_facets_query_string"] == "?created_at__year=2024"
    assert by_year.json()["config"]["date_hierarchy"]["level"] == "month"
    assert by_year.json()["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["date_hierarchy"]["back_query_string"] == "?_facets=1"
    assert [choice["value"] for choice in by_year.json()["config"]["date_hierarchy"]["choices"]] == [1, 2]

    by_month = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1")
    assert by_month.status_code == 200
    assert by_month.json()["config"]["result_count"] == 1
    assert by_month.json()["config"]["date_hierarchy"]["level"] == "day"
    assert by_month.json()["config"]["date_hierarchy"]["clear_query_string"] == "?"
    assert by_month.json()["config"]["date_hierarchy"]["back_query_string"] == "?created_at__year=2024"
    assert by_month.json()["config"]["date_hierarchy"]["choices"][0]["value"] == 15

    by_day = admin_client.get(
        "/admin-api/testapp/product?created_at__year=2024&created_at__month=1&created_at__day=15"
    )
    assert by_day.status_code == 200
    assert by_day.json()["config"]["date_hierarchy"]["back_query_string"] == (
        "?created_at__year=2024&created_at__month=1"
    )
    assert by_day.json()["config"]["date_hierarchy"]["choices"][0]["selected"] is True

    bad_day = admin_client.get(
        "/admin-api/testapp/product?created_at__year=2024&created_at__month=2&created_at__day=31"
    )
    assert bad_day.status_code == 400
    assert bad_day.json()["errors"] == [{"message": "Invalid day.", "param": "created_at__day"}]


def test_changelist_date_hierarchy_selects_lowest_useful_initial_level(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=timezone.make_aware(datetime(2024, 1, 15, 10, 0)))
    Product.objects.filter(pk=beta.pk).update(created_at=timezone.make_aware(datetime(2024, 2, 20, 10, 0)))

    same_year = admin_client.get("/admin-api/testapp/product")

    assert same_year.status_code == 200
    same_year_hierarchy = same_year.json()["config"]["date_hierarchy"]
    assert same_year_hierarchy["level"] == "month"
    assert same_year_hierarchy["params"] == {"year": 2024}
    assert same_year_hierarchy["clear_query_string"] == "?"
    assert same_year_hierarchy["back_query_string"] == "?"
    assert [
        (choice["value"], choice["query_string"]) for choice in same_year_hierarchy["choices"]
    ] == [
        (1, "?created_at__year=2024&created_at__month=1"),
        (2, "?created_at__year=2024&created_at__month=2"),
    ]

    Product.objects.filter(pk=beta.pk).update(created_at=timezone.make_aware(datetime(2024, 1, 20, 10, 0)))
    same_month = admin_client.get("/admin-api/testapp/product")

    assert same_month.status_code == 200
    same_month_hierarchy = same_month.json()["config"]["date_hierarchy"]
    assert same_month_hierarchy["level"] == "day"
    assert same_month_hierarchy["params"] == {"year": 2024, "month": 1}
    assert same_month_hierarchy["clear_query_string"] == "?"
    assert same_month_hierarchy["back_query_string"] == "?created_at__year=2024"
    assert [
        (choice["value"], choice["query_string"]) for choice in same_month_hierarchy["choices"]
    ] == [
        (15, "?created_at__year=2024&created_at__month=1&created_at__day=15"),
        (20, "?created_at__year=2024&created_at__month=1&created_at__day=20"),
    ]


def test_changelist_date_hierarchy_uses_active_timezone(admin_client, sample):
    boundary = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
    Product.objects.all().update(created_at=boundary)

    with timezone.override("America/Los_Angeles"):
        response = admin_client.get("/admin-api/testapp/product")
        by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2023")
        request = RequestFactory().get("/admin-api/testapp/product?created_at__year=2023")
        request.user = get_user_model().objects.get(username="admin")
        changelist = ChangeList(request, site.get_model_admin(Product))
        start, end = changelist.date_hierarchy_bounds({"year": 2023})

    assert response.status_code == 200
    hierarchy = response.json()["config"]["date_hierarchy"]
    assert hierarchy["field_type"] == "DateTimeField"
    assert hierarchy["timezone"] == "America/Los_Angeles"
    assert hierarchy["level"] == "day"
    assert hierarchy["params"] == {"year": 2023, "month": 12}
    assert [choice["value"] for choice in hierarchy["choices"]] == [31]

    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == Product.objects.count()
    by_year_hierarchy = by_year.json()["config"]["date_hierarchy"]
    assert by_year_hierarchy["timezone"] == "America/Los_Angeles"
    assert by_year_hierarchy["level"] == "month"
    assert [choice["value"] for choice in by_year_hierarchy["choices"]] == [12]
    assert start.isoformat() == "2023-01-01T00:00:00-08:00"
    assert end.isoformat() == "2024-01-01T00:00:00-08:00"


def test_changelist_date_hierarchy_handles_max_year_bounds(admin_client, sample):
    year = admin_client.get("/admin-api/testapp/product?created_at__year=9999")
    day = admin_client.get(
        "/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31"
    )

    assert year.status_code == 200
    assert year.json()["config"]["result_count"] == 0
    assert day.status_code == 200
    assert day.json()["config"]["result_count"] == 0

    request = RequestFactory().get(
        "/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31"
    )
    request.user = get_user_model().objects.get(username="admin")
    changelist = ChangeList(request, site.get_model_admin(Product))
    start, end = changelist.date_hierarchy_bounds({"year": 9999, "month": 12, "day": 31})

    assert start.isoformat().startswith("9999-12-31T00:00:00")
    assert end is None


def test_changelist_show_facets_modes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.NEVER)
    never = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert never.status_code == 200
    assert never.json()["config"]["show_facets"] is False
    assert never.json()["config"]["facets_optional"] is False
    assert never.json()["config"]["add_facets_query_string"] is None
    assert never.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in never.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert all(choice["count"] is None for choice in stock_filter["choices"])

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.ALWAYS)
    always = admin_client.get("/admin-api/testapp/product")
    assert always.status_code == 200
    assert always.json()["config"]["show_facets"] is True
    assert always.json()["config"]["facets_optional"] is False
    assert always.json()["config"]["add_facets_query_string"] is None
    assert always.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in always.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1


def test_changelist_date_hierarchy_supports_relation_paths(admin_client, sample):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"
        ordering = ("title",)

    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=timezone.make_aware(datetime(2024, 1, 15, 10, 0)))
    Product.objects.filter(pk=beta.pk).update(created_at=timezone.make_aware(datetime(2025, 2, 20, 10, 0)))
    ProductImage.objects.create(product=beta, title="Beta image")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(ProductImage, RelatedDateHierarchyImageAdmin)
    model_admin = admin_site.get_model_admin(ProductImage)
    user = get_user_model().objects.get(username="admin")

    request = RequestFactory().get("/admin-api/testapp/productimage")
    request.user = user
    changelist = ChangeList(request, model_admin)

    description = changelist.date_hierarchy_description()
    assert description["field"] == "product__created_at"
    assert description["field_type"] == "DateTimeField"
    assert description["timezone"] == timezone.get_current_timezone_name()
    assert description["level"] == "year"
    assert [choice["value"] for choice in description["choices"]] == [2024, 2025]

    by_year_request = RequestFactory().get("/admin-api/testapp/productimage?product__created_at__year=2024")
    by_year_request.user = user
    by_year = ChangeList(by_year_request, model_admin)
    by_year_description = by_year.date_hierarchy_description()

    assert by_year.result_count == 1
    assert by_year_description["level"] == "month"
    assert by_year_description["choices"][0]["query_string"] == (
        "?product__created_at__year=2024&product__created_at__month=1"
    )


def test_date_field_list_filter_uses_bounded_ranges(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("created_at",))
    monkeypatch.setattr(
        "django_ninja_admin.filters.timezone.now",
        lambda: timezone.make_aware(datetime(2024, 1, 15, 12, 0)),
    )
    Product.objects.all().update(created_at=timezone.make_aware(datetime(2024, 1, 15, 10, 0)))
    Product.objects.create(
        name="Future",
        category=sample.category,
        price="7.00",
        created_at=timezone.make_aware(datetime(2024, 2, 1, 10, 0)),
    )

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    date_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "created at")
    this_month = next(choice for choice in date_filter["choices"] if choice["display"] == "This month")
    assert "created_at__gte=" in this_month["query_string"]
    assert "created_at__lt=" in this_month["query_string"]

    filtered = admin_client.get(f"/admin-api/testapp/product{this_month['query_string']}")
    assert filtered.status_code == 200
    assert filtered.json()["config"]["result_count"] == 2
    assert [row["cells"]["name"] for row in filtered.json()["rows"]] == ["Alpha", "Beta"]

    stale_response = admin_client.get(
        "/admin-api/testapp/product",
        {
            "created_at__gte": "2023-01-01 00:00:00+00:00",
            "created_at__lt": "2023-02-01 00:00:00+00:00",
        },
    )
    stale_filter = next(item for item in stale_response.json()["config"]["filters"] if item["title"] == "created at")
    stale_any_date = next(choice for choice in stale_filter["choices"] if choice["display"] == "Any date")
    stale_this_month = next(choice for choice in stale_filter["choices"] if choice["display"] == "This month")
    assert stale_any_date["query_string"] == "?"
    assert "2023" not in stale_this_month["query_string"]


def test_changelist_allows_local_field_lookup_suffixes(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?price__gte=10")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert response.json()["rows"][0]["cells"]["name"] == "Alpha"


@isolate_apps("tests.testapp")
def test_lookup_allowed_honors_limit_choices_to_relation_lookups(db):
    class LimitedCategory(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "testapp"

    class LimitedProduct(models.Model):
        category = models.ForeignKey(LimitedCategory, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class LimitedImage(models.Model):
        product = models.ForeignKey(
            LimitedProduct,
            on_delete=models.CASCADE,
            limit_choices_to={"category__name": "Cameras"},
        )

        class Meta:
            app_label = "testapp"

    class LimitedProductAdmin(ModelAdmin):
        list_filter = ()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(LimitedProduct, LimitedProductAdmin)
    model_admin = admin_site.get_model_admin(LimitedProduct)
    request = RequestFactory().get("/admin-api/testapp/limitedproduct")

    assert model_admin.lookup_allowed("category__name", "Cameras", request) is True
    assert model_admin.lookup_allowed("category__name", "Accessories", request) is False


def test_changelist_rejects_bad_lookup_page_and_ordering(admin_client, sample):
    bad_lookup = admin_client.get("/admin-api/testapp/product?category__name=Cameras")
    assert bad_lookup.status_code == 400

    bad_filter_value = admin_client.get("/admin-api/testapp/product?category__id__exact=not-an-id")
    assert bad_filter_value.status_code == 400
    assert bad_filter_value.json()["errors"] == [
        {"message": "Invalid lookup value.", "param": "category__id__exact"}
    ]

    bad_direct_value = admin_client.get("/admin-api/testapp/product?price=not-a-decimal")
    assert bad_direct_value.status_code == 400
    assert bad_direct_value.json()["errors"] == [{"message": "Invalid lookup value.", "param": "price"}]

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
    assert fields_by_name["name"]["attrs"]["error_messages"]["required"] == "This field is required."
    assert fields_by_name["name"]["attrs"]["localize"] is False
    assert fields_by_name["name"]["attrs"]["is_localized"] is False
    assert fields_by_name["category"]["attrs"]["related_model"] == "testapp.category"
    assert fields_by_name["category"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["category"]["attrs"]["related_model_name"] == "category"
    assert fields_by_name["category"]["attrs"]["related_object_name"] == "Category"
    assert fields_by_name["category"]["attrs"]["related_verbose_name"] == "category"
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "id"
    assert fields_by_name["category"]["attrs"]["model_field_name"] == "category"
    assert fields_by_name["category"]["attrs"]["model_field_class"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["internal_type"] == "ForeignKey"
    assert fields_by_name["category"]["attrs"]["attname"] == "category_id"
    assert fields_by_name["category"]["attrs"]["column"] == "category_id"
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
    assert fields_by_name["stock_status"]["attrs"]["option_template_name"] == "django/forms/widgets/radio_option.html"
    assert fields_by_name["stock_status"]["attrs"]["add_id_index"] is True
    assert fields_by_name["stock_status"]["attrs"]["checked_attribute"] == {"checked": True}
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
    assert fields_by_name["stock_status"]["attrs"]["radio"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "stock_status",
        "orientation": VERTICAL,
    }
    assert fields_by_name["category"]["attrs"]["admin_widget"] == "autocomplete"
    assert fields_by_name["category"]["attrs"]["autocomplete"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "category",
    }
    assert fields_by_name["description"]["attrs"]["blank"] is True
    assert fields_by_name["description"]["attrs"]["null"] is False
    assert fields_by_name["description"]["attrs"]["prepopulated_from"] == ["name"]
    assert fields_by_name["description"]["attrs"]["prepopulated"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "description",
        "sources": [{"field_name": "name", "label": "name", "internal_type": "CharField"}],
    }
    assert fields_by_name["manual"]["type"] == "FileField"
    assert fields_by_name["manual"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["manual"]["attrs"]["blank"] is True
    assert fields_by_name["manual"]["attrs"]["upload_to"] == "manuals"
    assert fields_by_name["photo"]["type"] == "ImageField"
    assert fields_by_name["photo"]["attrs"]["needs_multipart_form"] is True
    assert fields_by_name["photo"]["attrs"]["image"] is True
    assert fields_by_name["photo"]["attrs"]["accepted_content_types"] == ["image/*"]
    assert fields_by_name["photo"]["attrs"]["upload_to"] == "photos"
    assert fields_by_name["photo"]["attrs"]["width_field"] == "photo_width"
    assert fields_by_name["photo"]["attrs"]["height_field"] == "photo_height"
    assert fields_by_name["tags"]["type"] == "ModelMultipleChoiceField"
    assert fields_by_name["tags"]["attrs"]["related_model"] == "testapp.tag"
    assert fields_by_name["tags"]["attrs"]["related_app_label"] == "testapp"
    assert fields_by_name["tags"]["attrs"]["related_model_name"] == "tag"
    assert fields_by_name["tags"]["attrs"]["related_object_name"] == "Tag"
    assert fields_by_name["tags"]["attrs"]["model_field_name"] == "tags"
    assert fields_by_name["tags"]["attrs"]["model_field_class"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["internal_type"] == "ManyToManyField"
    assert fields_by_name["tags"]["attrs"]["multiple"] is True
    assert fields_by_name["tags"]["attrs"]["blank"] is True
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"
    assert fields_by_name["tags"]["attrs"]["filtered_select"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "tags",
        "direction": "horizontal",
    }
    assert form.json()["form"]["filter_horizontal"] == ["tags"]

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    assert change_form.status_code == 200
    change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
    assert change_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert set(change_fields_by_name["tags"]["attrs"]["value"]) == set(sample.tags.values_list("pk", flat=True))
    assert {option["text"] for option in change_fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }
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
    latest_history = history.json()["results"][0]
    assert latest_history["change_message"] == [{"changed": {"fields": ["Tags"]}}]
    assert latest_history["change_message_text"] == "Changed Tags."

    deleted = admin_client.delete(f"/admin-api/testapp/product/{created_id}")
    assert deleted.status_code == 204


def test_add_form_description_uses_changeform_initial_data(admin_client, sample):
    tag_ids = list(sample.tags.order_by("name").values_list("pk", flat=True))
    response = admin_client.get(
        "/admin-api/testapp/product/form",
        {
            "name": "Seed product",
            "category": sample.category_id,
            "tags": ",".join(str(tag_id) for tag_id in tag_ids),
            "price": "4.50",
            "stock_status": "out_of_stock",
        },
    )

    assert response.status_code == 200
    fields_by_name = {field["name"]: field for field in response.json()["form"]["fields"]}
    assert fields_by_name["name"]["attrs"]["value"] == "Seed product"
    assert fields_by_name["category"]["attrs"]["value"] == str(sample.category_id)
    assert fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert set(fields_by_name["tags"]["attrs"]["value"]) == {str(tag_id) for tag_id in tag_ids}
    assert {option["text"] for option in fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Compact",
        "Featured",
    }
    assert fields_by_name["price"]["attrs"]["value"] == "4.50"
    assert fields_by_name["stock_status"]["attrs"]["value"] == "out_of_stock"

    class InitialProductAdmin(ModelAdmin):
        def get_changeform_initial_data(self, request):
            return {
                "name": "Hooked initial",
                "category": sample.category_id,
                "tags": tag_ids,
            }

    user = get_user_model().objects.create_user("initial-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form?name=Ignored")
    request.user = user
    model_admin = InitialProductAdmin(Product, NinjaAdminSite(include_auth=False))

    hooked_form = model_admin.get_form_description(request)["form"]
    hooked_fields_by_name = {field["name"]: field for field in hooked_form["fields"]}

    assert hooked_fields_by_name["name"]["attrs"]["value"] == "Hooked initial"
    assert hooked_fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert {option["text"] for option in hooked_fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Compact",
        "Featured",
    }


def test_direct_update_skips_empty_change_log(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    save_calls = []
    original_save_model = product_admin.save_model

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

    monkeypatch.setattr(product_admin, "save_model", save_model)
    before = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count()
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"name": sample.name}},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert save_calls == [sample.pk]
    assert LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count() == before
    sample.refresh_from_db()
    assert sample.name == "Alpha"


def test_form_description_uses_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def get_extra(self, request, obj=None, **kwargs):
        return 2 if obj is not None else 4

    def get_min_num(self, request, obj=None, **kwargs):
        return 1

    def get_max_num(self, request, obj=None, **kwargs):
        return 5

    monkeypatch.setattr(ProductImageInline, "get_extra", get_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", get_min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", get_max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["extra"] == 2
    assert inline["min_num"] == 1
    assert inline["max_num"] == 5
    title_values = [
        next(field for field in row if field["name"] == "title")["attrs"].get("value")
        for row in inline["formset"]
    ]
    assert title_values == ["Front", None, None]

    add_response = admin_client.get("/admin-api/testapp/product/form")

    assert add_response.status_code == 200
    add_inline = next(item for item in add_response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert add_inline["extra"] == 4
    assert add_inline["min_num"] == 1
    assert len(add_inline["formset"]) == 5


def test_form_description_rejects_invalid_dynamic_inline_count_hooks(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    def negative_extra(self, request, obj=None, **kwargs):
        return -1

    monkeypatch.setattr(ProductImageInline, "get_extra", negative_extra)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'extra' must not be negative.",
            "param": "inlines.testapp.productimage.extra",
        }
    ]

    def zero_extra(self, request, obj=None, **kwargs):
        return 0

    def min_num(self, request, obj=None, **kwargs):
        return 3

    def max_num(self, request, obj=None, **kwargs):
        return 1

    monkeypatch.setattr(ProductImageInline, "get_extra", zero_extra)
    monkeypatch.setattr(ProductImageInline, "get_min_num", min_num)
    monkeypatch.setattr(ProductImageInline, "get_max_num", max_num)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 400
    assert response.json()["errors"] == [
        {
            "message": "Inline 'min_num' must not exceed 'max_num'.",
            "param": "inlines.testapp.productimage.min_num",
        }
    ]


def test_inline_descriptions_use_formfield_hooks_and_media(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class InlineTitleWidget(forms.TextInput):
        class Media:
            css = {"all": ("admin/inline-title.css",)}
            js = ("admin/inline-title.js",)

    original_formfield_for_dbfield = ProductImageInline.formfield_for_dbfield

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "title":
            kwargs["help_text"] = "Inline title from formfield hook."
            kwargs["widget"] = InlineTitleWidget(attrs={"data-inline": "title"})
        return original_formfield_for_dbfield(self, db_field, request, **kwargs)

    monkeypatch.setattr(ProductImageInline, "formfield_for_dbfield", formfield_for_dbfield)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    assert inline["media"] == {
        "css": {"all": ["admin/inline-title.css"]},
        "js": ["admin/inline-title.js"],
    }
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["help_text"] == "Inline title from formfield hook." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-inline"] == "title" for field in title_fields)


def test_inline_admin_form_class_drives_metadata_and_validation(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    class ProductImageAdminForm(forms.ModelForm):
        title = forms.CharField(
            max_length=100,
            required=False,
            help_text="Inline title from custom form.",
            widget=forms.TextInput(attrs={"data-form": "inline"}),
        )

        class Meta:
            model = ProductImage
            fields = ("title",)

        def clean_title(self):
            title = self.cleaned_data["title"]
            if title == "Forbidden":
                raise forms.ValidationError("Forbidden inline title.")
            return title

    monkeypatch.setattr(ProductImageInline, "form_class", ProductImageAdminForm)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    inline = next(item for item in response.json()["inlines"] if item["model"] == "testapp.productimage")
    title_fields = [field for row in inline["formset"] for field in row if field["name"] == "title"]
    assert title_fields
    assert all(field["attrs"]["required"] is False for field in title_fields)
    assert all(field["attrs"]["help_text"] == "Inline title from custom form." for field in title_fields)
    assert all(field["attrs"]["widget_attrs"]["data-form"] == "inline" for field in title_fields)
    inline_admin = ProductImageInline(Product, NinjaAdminSite(include_auth=False))
    row_schema = inline_admin.get_inline_row_schema(RequestFactory().get("/"), sample)
    assert "title" not in row_schema.model_json_schema().get("required", [])

    invalid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Forbidden"}]}}},
        content_type="application/json",
    )

    assert invalid.status_code == 400
    assert "Forbidden inline title." in str(invalid.json()["errors"])
    assert not ProductImage.objects.filter(product=sample, title="Forbidden").exists()

    valid = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": "Allowed inline"}]}}},
        content_type="application/json",
    )

    assert valid.status_code == 200
    assert ProductImage.objects.filter(product=sample, title="Allowed inline").exists()


def test_disabled_inline_form_fields_are_optional_in_write_schema(db, sample):
    class DisabledProductImageForm(forms.ModelForm):
        title = forms.CharField(disabled=True, initial="Generated image title", max_length=100)

        class Meta:
            model = ProductImage
            fields = ("title",)

    class DisabledProductImageInline(TabularInline):
        model = ProductImage
        form_class = DisabledProductImageForm

    inline_admin = DisabledProductImageInline(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    field = inline_admin.get_form_fields_description(request, None)[0]
    row_schema = inline_admin.get_inline_row_schema(request, sample)

    assert field["name"] == "title"
    assert field["attrs"]["required"] is True
    assert field["attrs"]["disabled"] is True
    assert field["attrs"]["initial"] == "Generated image title"
    assert "title" not in row_schema.model_json_schema().get("required", [])


def test_readonly_display_fields_include_values_and_display_metadata(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def callable_summary(obj):
        return f"{obj.name}:{obj.stock_status}"

    callable_summary.short_description = "Callable summary"
    monkeypatch.setattr(
        product_admin,
        "readonly_fields",
        ("upper_name", "has_description", "subtitle", callable_summary),
    )

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    assert "callable_summary" in response.json()["form"]["readonly_fields"]
    assert "django_ninja_admin.E012" not in {error.id for error in product_admin.check()}
    fields_by_name = {field["name"]: field for field in response.json()["form"]["fields"]}
    assert fields_by_name["upper_name"]["attrs"]["label"] == "Upper name"
    assert fields_by_name["upper_name"]["attrs"]["value"] == "ALPHA"
    assert fields_by_name["upper_name"]["attrs"]["read_only"] is True
    assert fields_by_name["has_description"]["attrs"]["label"] == "Has description"
    assert fields_by_name["has_description"]["attrs"]["value"] is True
    assert fields_by_name["has_description"]["attrs"]["boolean"] is True
    assert fields_by_name["subtitle"]["attrs"]["label"] == "Subtitle"
    assert fields_by_name["subtitle"]["attrs"]["value"] == "Nice camera"
    assert fields_by_name["subtitle"]["attrs"]["empty_value_display"] == "No subtitle"
    assert fields_by_name["callable_summary"]["attrs"]["label"] == "Callable summary"
    assert fields_by_name["callable_summary"]["attrs"]["value"] == "Alpha:in_stock"
    assert fields_by_name["callable_summary"]["attrs"]["read_only"] is True

    empty_product = Product.objects.get(name="Beta")
    empty_response = admin_client.get(f"/admin-api/testapp/product/{empty_product.pk}/form")
    empty_fields_by_name = {field["name"]: field for field in empty_response.json()["form"]["fields"]}
    assert empty_fields_by_name["subtitle"]["attrs"]["value"] == "No subtitle"


def test_explicit_form_layouts_accept_callable_readonly_field_names(db, sample):
    def callable_summary(obj):
        return f"{obj.name}:{obj.stock_status}"

    callable_summary.short_description = "Callable summary"

    class ReadonlyLayoutProductAdmin(ModelAdmin):
        readonly_fields = ("upper_name", callable_summary)
        fieldsets = ((None, {"fields": ("name", "callable_summary", "upper_name")}),)

        @display(description="Upper name")
        def upper_name(self, obj):
            return obj.name.upper()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, ReadonlyLayoutProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    user = get_user_model().objects.create_user("readonly-layout-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    request.user = user

    assert "django_ninja_admin.E014" not in {error.id for error in model_admin.check()}
    assert list(model_admin.get_form_class(request, sample, change=True).base_fields) == ["name"]

    form = model_admin.get_form_description(request, sample)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert form["fieldsets"] == [(None, {"fields": ("name", "callable_summary", "upper_name")})]
    assert fields_by_name["callable_summary"]["attrs"]["label"] == "Callable summary"
    assert fields_by_name["callable_summary"]["attrs"]["value"] == "Alpha:in_stock"
    assert fields_by_name["upper_name"]["attrs"]["value"] == "ALPHA"


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
    assert {
        (item["detail_url"], item["change_form_url"])
        for item in global_history.json()["results"]
    } == {(f"/admin-api/testapp/product/{sample.pk}", f"/admin-api/testapp/product/{sample.pk}/form")}

    paged = client.get("/admin-api/history", {"per_page": 1, "page": 2})
    assert paged.status_code == 200
    assert paged.json()["pagination"] == {
        "num_pages": 2,
        "count": 2,
        "has_next": False,
        "has_previous": True,
        "page": 2,
        "per_page": 1,
    }
    assert len(paged.json()["results"]) == 1

    filtered = client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": ADDITION},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["results"]] == [product_addition.pk]
    assert filtered.json()["results"][0]["change_message_text"] == "Added."

    forbidden = client.get("/admin-api/history", {"app_label": "testapp", "model": "category"})
    assert forbidden.status_code == 403

    missing_app_label = client.get("/admin-api/history", {"model": "product"})
    assert missing_app_label.status_code == 400
    assert missing_app_label.json()["errors"] == [
        {"message": "app_label is required when model is provided.", "param": "app_label"}
    ]

    bad_page = client.get("/admin-api/history", {"page": 0})
    assert bad_page.status_code == 404

    bad_page_size = client.get("/admin-api/history", {"per_page": 0})
    assert bad_page_size.status_code == 400
    assert bad_page_size.json()["errors"] == [{"message": "Invalid page size.", "param": "per_page"}]


def test_form_description_marks_raw_id_and_filter_vertical_widget_modes(db, sample):
    user = get_user_model().objects.create_user("widget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get(f"/admin-api/testapp/product/{sample.pk}/form")
    request.user = user

    class RawWidgetProductAdmin(ModelAdmin):
        raw_id_fields = ("category",)
        filter_vertical = ("tags",)

    model_admin = RawWidgetProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request, sample)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert fields_by_name["category"]["attrs"]["admin_widget"] == "raw_id"
    assert fields_by_name["category"]["attrs"]["raw_id"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "category",
    }
    assert fields_by_name["category"]["attrs"]["selected_options"] == [
        {"id": str(sample.category_id), "text": "Cameras"}
    ]
    assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_vertical"
    assert fields_by_name["tags"]["attrs"]["filtered_select"] == {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "tags",
        "direction": "vertical",
    }
    assert {option["text"] for option in fields_by_name["tags"]["attrs"]["selected_options"]} == {
        "Featured",
        "Compact",
    }


def test_form_description_exposes_multiwidget_metadata(db):
    user = get_user_model().objects.create_user("multiwidget-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form")
    request.user = user

    class SplitWidgetProductForm(forms.ModelForm):
        release_window = forms.SplitDateTimeField(
            required=False,
            input_date_formats=["%Y-%m-%d"],
            input_time_formats=["%H:%M"],
            widget=forms.SplitDateTimeWidget(
                date_attrs={"data-part": "date"},
                time_attrs={"data-part": "time"},
                date_format="%Y-%m-%d",
                time_format="%H:%M",
            ),
        )
        product_code = forms.RegexField(required=False, regex=r"^[A-Z]{3}$")

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class SplitWidgetProductAdmin(ModelAdmin):
        form_class = SplitWidgetProductForm

    model_admin = SplitWidgetProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    field = next(item for item in form["fields"] if item["name"] == "release_window")
    code_field = next(item for item in form["fields"] if item["name"] == "product_code")
    attrs = field["attrs"]

    assert attrs["widget"] == "SplitDateTimeWidget"
    assert attrs["template_name"] == "django/forms/widgets/splitdatetime.html"
    assert attrs["use_fieldset"] is True
    assert attrs["supports_microseconds"] is False
    assert attrs["input_formats"] == [
        {"index": 0, "input_formats": ["%Y-%m-%d"]},
        {"index": 1, "input_formats": ["%H:%M"]},
    ]
    assert attrs["subwidgets"] == [
        {
            "name_suffix": "_0",
            "widget": "DateInput",
            "widget_attrs": {"data-part": "date"},
            "is_hidden": False,
            "is_localized": False,
            "multiple": False,
            "template_name": "django/forms/widgets/date.html",
            "input_type": "text",
            "format": "%Y-%m-%d",
            "needs_multipart_form": False,
            "supports_microseconds": False,
        },
        {
            "name_suffix": "_1",
            "widget": "TimeInput",
            "widget_attrs": {"data-part": "time"},
            "is_hidden": False,
            "is_localized": False,
            "multiple": False,
            "template_name": "django/forms/widgets/time.html",
            "input_type": "text",
            "format": "%H:%M",
            "needs_multipart_form": False,
            "supports_microseconds": False,
        },
    ]
    assert any(
        detail.get("pattern") == "^[A-Z]{3}$"
        for detail in code_field["attrs"]["validator_details"]
    )


def test_form_description_exposes_select_date_widget_metadata(db):
    user = get_user_model().objects.create_user("selectdate-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form?release_date=2024-02-03")
    request.user = user

    class SelectDateProductForm(forms.ModelForm):
        release_date = forms.DateField(
            required=False,
            widget=forms.SelectDateWidget(
                years=[2024, 2025],
                months={1: "Jan", 2: "Feb"},
                empty_label=("Year", "Month", "Day"),
                attrs={"data-date": "release"},
            ),
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class SelectDateProductAdmin(ModelAdmin):
        form_class = SelectDateProductForm

    model_admin = SelectDateProductAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    attrs = next(field["attrs"] for field in form["fields"] if field["name"] == "release_date")

    assert attrs["widget"] == "SelectDateWidget"
    assert attrs["template_name"] == "django/forms/widgets/select_date.html"
    assert attrs["input_type"] == "select"
    assert attrs["use_fieldset"] is True
    assert attrs["widget_attrs"] == {"data-date": "release"}
    assert attrs["value"] == "2024-02-03"
    assert attrs["select_date"] == {
        "order": ["month", "day", "year"],
        "field_names": {
            "year": "release_date_year",
            "month": "release_date_month",
            "day": "release_date_day",
        },
        "years": [2024, 2025],
        "months": [{"value": 1, "label": "Jan"}, {"value": 2, "label": "Feb"}],
        "days": list(range(1, 32)),
        "empty_choices": {
            "year": {"value": "", "label": "Year"},
            "month": {"value": "", "label": "Month"},
            "day": {"value": "", "label": "Day"},
        },
        "selected": {"year": 2024, "month": 2, "day": 3},
    }


def test_form_description_exposes_filepath_field_metadata(db, tmp_path):
    fixture_file = tmp_path / "choice.txt"
    fixture_file.write_text("ok")
    skipped_file = tmp_path / "skipped.md"
    skipped_file.write_text("no")
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "deep.txt"
    nested_file.write_text("nested")

    class FilePathProductForm(forms.ModelForm):
        file_path = forms.FilePathField(
            path=str(tmp_path),
            match=r".*\.txt$",
            recursive=True,
            allow_files=True,
            allow_folders=False,
            required=False,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class FilePathProductAdmin(ModelAdmin):
        form_class = FilePathProductForm

    model_admin = FilePathProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    field = next(
        item for item in model_admin.get_form_fields_description(request) if item["name"] == "file_path"
    )

    attrs = field["attrs"]
    choice_values = [value for value, _label in attrs["choices"]]
    assert field["type"] == "FilePathField"
    assert attrs["path"] == str(tmp_path)
    assert attrs["match"] == r".*\.txt$"
    assert attrs["recursive"] is True
    assert attrs["allow_files"] is True
    assert attrs["allow_folders"] is False
    assert str(fixture_file) in choice_values
    assert str(nested_file) in choice_values
    assert str(skipped_file) not in choice_values


def test_form_description_exposes_combo_field_metadata(db):
    class ComboProductForm(forms.ModelForm):
        combo_code = forms.ComboField(
            fields=[
                forms.CharField(max_length=5),
                forms.RegexField(regex=r"^[A-Z]+$"),
            ],
            required=False,
        )

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class ComboProductAdmin(ModelAdmin):
        form_class = ComboProductForm

    model_admin = ComboProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    field = next(
        item for item in model_admin.get_form_fields_description(request) if item["name"] == "combo_code"
    )

    attrs = field["attrs"]
    assert field["type"] == "ComboField"
    assert [item["type"] for item in attrs["combo_fields"]] == ["CharField", "RegexField"]
    assert attrs["combo_fields"][0]["index"] == 0
    assert attrs["combo_fields"][0]["attrs"]["max_length"] == 5
    assert attrs["combo_fields"][1]["index"] == 1
    assert any(
        detail.get("pattern") == "^[A-Z]+$"
        for detail in attrs["combo_fields"][1]["attrs"]["validator_details"]
    )


def test_form_description_exposes_numeric_step_metadata(db):
    class StepProductForm(forms.ModelForm):
        stepped_count = forms.IntegerField(required=False, step_size=2)
        offset_count = forms.IntegerField(required=False, min_value=1, step_size=2)
        stepped_price = forms.DecimalField(required=False, step_size=Decimal("0.25"), max_digits=4, decimal_places=2)

        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

    class StepProductAdmin(ModelAdmin):
        form_class = StepProductForm

    model_admin = StepProductAdmin(Product, NinjaAdminSite(include_auth=False))
    request = RequestFactory().get("/")
    fields_by_name = {
        item["name"]: item
        for item in model_admin.get_form_fields_description(request)
    }

    assert fields_by_name["stepped_count"]["attrs"]["step_size"] == 2
    assert "step_offset" not in fields_by_name["stepped_count"]["attrs"]
    assert fields_by_name["offset_count"]["attrs"]["step_size"] == 2
    assert fields_by_name["offset_count"]["attrs"]["step_offset"] == 1
    assert fields_by_name["stepped_price"]["attrs"]["step_size"] == "0.25"


@pytest.mark.parametrize(
    ("limit_choices_to", "expected"),
    [
        ({"name__startswith": "Cam"}, {"name__startswith": "Cam"}),
        (lambda: {"name__startswith": "Cam"}, {"name__startswith": "Cam"}),
        (
            models.Q(name__startswith="Cam"),
            {
                "connector": "AND",
                "negated": False,
                "children": [{"lookup": "name__startswith", "value": "Cam"}],
            },
        ),
    ],
    ids=["dict", "callable", "q"],
)
def test_form_description_exposes_relation_limit_choices_to(db, sample, monkeypatch, limit_choices_to, expected):
    user = get_user_model().objects.create_user("limit-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product/form")
    request.user = user
    category_field = Product._meta.get_field("category")
    monkeypatch.setattr(category_field.remote_field, "limit_choices_to", limit_choices_to)

    model_admin = ModelAdmin(Product, NinjaAdminSite(include_auth=False))
    form = model_admin.get_form_description(request)["form"]
    fields_by_name = {field["name"]: field for field in form["fields"]}

    assert fields_by_name["category"]["attrs"]["limit_choices_to"] == expected


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


def test_file_and_image_fields_reject_non_string_json_payloads(admin_client, sample):
    invalid_manual = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"manual": {"name": "manual.txt"}}},
        content_type="application/json",
    )
    invalid_photo = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {"photo": ["photo.png"]}},
        content_type="application/json",
    )

    assert invalid_manual.status_code == 422
    assert invalid_manual.json()["errors"][0]["param"] == "data.manual"
    assert invalid_photo.status_code == 422
    assert invalid_photo.json()["errors"][0]["param"] == "data.photo"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_multipart_file_parts_satisfy_required_file_schema_fields(admin_client, sample, tmp_path):
    schema = admin_client.get("/required-file-admin/openapi.json").json()
    create_data_schema = schema["components"]["schemas"]["ProductAdminCreateData"]

    assert "manual" in create_data_schema["required"]
    assert create_data_schema["properties"]["manual"] == {"title": "Manual", "type": "string"}
    multipart_schema = schema["paths"]["/required-file-admin/testapp/product/multipart"]["post"]["requestBody"][
        "content"
    ]["multipart/form-data"]["schema"]
    assert multipart_schema["required"] == ["data", "manual"]

    form = admin_client.get("/required-file-admin/testapp/product/form")
    manual_attrs = next(field["attrs"] for field in form.json()["form"]["fields"] if field["name"] == "manual")
    assert manual_attrs["allowed_extensions"] == ["pdf", "txt"]
    assert manual_attrs["accepted_extensions"] == [".pdf", ".txt"]

    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Invalid manual extension",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.exe", b"required", content_type="application/octet-stream"),
            },
        )

        assert invalid.status_code == 400
        assert invalid.json()["errors"]["form"][0]["param"] == "manual"
        assert not Product.objects.filter(name="Invalid manual extension").exists()

        created = admin_client.post(
            "/required-file-admin/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Required manual",
                        "category": sample.category_id,
                        "price": "5.00",
                        "stock_status": "in_stock",
                    }
                ),
                "manual": SimpleUploadedFile("required.txt", b"required", content_type="text/plain"),
            },
        )

        assert created.status_code == 201, created.json()
        product = Product.objects.get(pk=created.json()["data"]["id"])
        assert product.manual.name.startswith("manuals/required")
        assert (tmp_path / product.manual.name).read_bytes() == b"required"
        assert created.json()["data"]["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }


def test_file_field_can_be_uploaded_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        created = admin_client.post(
            "/admin-api/testapp/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Upload",
                        "category": sample.category_id,
                        "tags": list(sample.tags.values_list("pk", flat=True)),
                        "price": "7.00",
                        "stock_status": "in_stock",
                        "description": "Created with upload",
                    }
                ),
                "manual": SimpleUploadedFile("manual.txt", b"hello", content_type="text/plain"),
            },
        )

        assert created.status_code == 201
        created_body = created.json()["data"]
        product = Product.objects.get(pk=created_body["id"])
        assert product.manual.name.startswith("manuals/manual")
        assert (tmp_path / product.manual.name).read_bytes() == b"hello"
        assert created_body["manual"] == {
            "name": product.manual.name,
            "url": f"/media/{product.manual.name}",
        }

        changed = admin_client.patch(
            f"/admin-api/testapp/product/{product.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Updated with upload"}),
                    "manual": SimpleUploadedFile("replacement.txt", b"updated", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200
        product.refresh_from_db()
        assert product.description == "Updated with upload"
        assert product.manual.name.startswith("manuals/replacement")
        assert (tmp_path / product.manual.name).read_bytes() == b"updated"
        change_entry = LogEntry.objects.filter(object_id=str(product.pk), action_flag=CHANGE).latest("action_time")
        changed_fields = json.loads(change_entry.change_message)[0]["changed"]["fields"]
        assert set(changed_fields) == {"Description", "Manual"}


def test_image_field_validates_and_uploads_with_multipart_payload(admin_client, sample, tmp_path):
    with override_settings(MEDIA_ROOT=tmp_path):
        invalid = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Invalid image upload"}),
                    "photo": SimpleUploadedFile("not-image.txt", b"not an image", content_type="text/plain"),
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert invalid.status_code == 400
        invalid_body = invalid.json()
        assert invalid_body["errors"]["form"][0]["param"] == "photo"
        assert Product.objects.get(pk=sample.pk).photo.name == ""

        uploaded = _uploaded_png("cover.png", size=(2, 3))
        changed = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}/multipart",
            data=encode_multipart(
                BOUNDARY,
                {
                    "data": json.dumps({"description": "Image uploaded"}),
                    "photo": uploaded,
                },
            ),
            content_type=MULTIPART_CONTENT,
        )

        assert changed.status_code == 200, changed.json()
        sample.refresh_from_db()
        assert sample.description == "Image uploaded"
        assert sample.photo.name.startswith("photos/cover")
        assert sample.photo_width == 2
        assert sample.photo_height == 3
        assert (tmp_path / sample.photo.name).exists()
        assert changed.json()["data"]["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
        assert detail.status_code == 200
        assert detail.json()["photo"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        photo_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "photo")
        assert photo_attrs["current_file"] == {
            "name": sample.photo.name,
            "url": f"/media/{sample.photo.name}",
            "width": 2,
            "height": 3,
        }

        cleared = admin_client.patch(
            f"/admin-api/testapp/product/{sample.pk}",
            data={"data": {"photo": None}},
            content_type="application/json",
        )

        assert cleared.status_code == 200, cleared.json()
        assert cleared.json()["data"]["photo"] is None
        sample.refresh_from_db()
        assert sample.photo.name == ""
        assert sample.photo_width is None
        assert sample.photo_height is None
        cleared_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
        cleared_photo_attrs = next(
            field["attrs"] for field in cleared_form.json()["form"]["fields"] if field["name"] == "photo"
        )
        assert "current_file" not in cleared_photo_attrs
        clear_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
        assert json.loads(clear_entry.change_message) == [{"changed": {"fields": ["Photo"]}}]


def test_file_field_metadata_handles_storage_without_public_url(admin_client, sample, monkeypatch):
    manual_field = Product._meta.get_field("manual")
    monkeypatch.setattr(manual_field, "storage", Storage())

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")

    assert detail.status_code == 200
    assert detail.json()["manual"] == {"name": "manuals/alpha.pdf", "url": None}

    change_form = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")
    manual_attrs = next(field["attrs"] for field in change_form.json()["form"]["fields"] if field["name"] == "manual")

    assert change_form.status_code == 200
    assert manual_attrs["current_file"] == {"name": "manuals/alpha.pdf", "url": None}


@isolate_apps("tests.testapp")
def test_image_field_has_typed_schema_and_image_metadata(db):
    class GalleryImage(models.Model):
        image = models.ImageField(
            upload_to="photos",
            width_field="width",
            height_field="height",
            blank=True,
        )
        width = models.PositiveIntegerField(null=True, blank=True)
        height = models.PositiveIntegerField(null=True, blank=True)

        class Meta:
            app_label = "testapp"

    admin_site = NinjaAdminSite(auth=None, include_auth=False)
    admin_site.register(GalleryImage)
    model_admin = admin_site.get_model_admin(GalleryImage)
    request = RequestFactory().get("/")
    obj = GalleryImage(id=1, image="photos/sample.png", width=640, height=480)

    output_schema = model_admin.get_output_schema().model_json_schema()
    image_schema = output_schema["properties"]["image"]["anyOf"]
    assert any(option.get("$ref", "").endswith("ImageFieldValue") for option in image_schema)
    assert output_schema["$defs"]["ImageFieldValue"]["properties"]["width"]["anyOf"][0]["type"] == "integer"

    image_field = next(
        field for field in model_admin.get_form_fields_description(request, obj) if field["name"] == "image"
    )
    assert image_field["type"] == "ImageField"
    assert image_field["attrs"]["image"] is True
    assert image_field["attrs"]["accepted_content_types"] == ["image/*"]
    assert image_field["attrs"]["upload_to"] == "photos"
    assert image_field["attrs"]["width_field"] == "width"
    assert image_field["attrs"]["height_field"] == "height"
    assert image_field["attrs"]["current_file"] == {
        "name": "photos/sample.png",
        "url": "/media/photos/sample.png",
        "width": None,
        "height": None,
    }

    assert model_admin.serialize_object(obj, request)["image"] == {
        "name": "photos/sample.png",
        "url": "/media/photos/sample.png",
        "width": None,
        "height": None,
    }


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


def test_direct_delete_returns_object_permission_needed_details(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_delete_permission(request, obj=None):
        return obj is None

    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.delete(f"/admin-api/testapp/product/{sample.pk}")

    assert response.status_code == 403
    body = response.json()
    assert body["errors"][0]["param"] == "object_id"
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
    assert bad_field.json()["errors"] == [
        {"message": "The field 'name' cannot be referenced.", "param": "_to_field"}
    ]


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
    fields_by_name = {
        field["name"]: field
        for row in changelist.json()["list_editing_rows"]
        for field in row["fields"]
    }
    assert list(fields_by_name) == ["stock_status"]
    assert fields_by_name["stock_status"]["attrs"]["help_text"] == "Bulk-only status field."
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [["out_of_stock", "Bulk unavailable"]]

    invalid = admin_client.put(
        "/bulk-form-admin/testapp/product/bulk",
        data={"data": [{"pk": sample.pk, "stock_status": "in_stock"}]},
        content_type="application/json",
    )

    assert invalid.status_code == 400
    assert invalid.json()["errors"]["0"][0]["param"] == "stock_status"
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


def test_inline_payload_uses_pydantic_request_validation(admin_client, sample):
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{}]}}},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title"


@override_settings(ROOT_URLCONF="tests.custom_form_urls")
def test_inline_multivalue_payload_uses_pydantic_and_formset_normalization(admin_client, sample):
    product = Product.objects.create(
        name="Inline coded",
        category=sample.category,
        price="4.00",
        stock_status="in_stock",
    )

    invalid = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["abc", 4]}]}}},
        content_type="application/json",
    )
    assert invalid.status_code == 422
    assert invalid.json()["errors"][0]["param"] == "inlines.testapp.productimage.add.0.title.0"
    assert not ProductImage.objects.filter(product=product).exists()

    created = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"add": [{"title": ["ABC", "4"]}]}}},
        content_type="application/json",
    )
    assert created.status_code == 200, created.json()
    image = ProductImage.objects.get(product=product)
    assert image.title == "ABC:4"
    assert created.json()["inlines"]["testapp.productimage"]["add"][0]["title"] == "ABC:4"

    changed = admin_client.patch(
        f"/inline-multivalue-admin/testapp/product/{product.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": ["XYZ", 9]}]}}},
        content_type="application/json",
    )
    assert changed.status_code == 200, changed.json()
    image.refresh_from_db()
    assert image.title == "XYZ:9"
    assert changed.json()["inlines"]["testapp.productimage"]["change"][0]["title"] == "XYZ:9"


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
        },
    )
    assert first_page.status_code == 200
    assert len(first_page.json()["results"]) == 20
    assert first_page.json()["pagination"] == {
        "more": True,
        "count": 25,
        "num_pages": 2,
        "page": 1,
        "per_page": 20,
        "has_next": True,
        "has_previous": False,
    }

    second_page = admin_client.get(
        "/admin-api/autocomplete",
        {
            "app_label": "testapp",
            "model_name": "product",
            "field_name": "tags",
            "term": "Tag",
            "page": 2,
        },
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["results"]) == 5
    assert second_page.json()["pagination"] == {
        "more": False,
        "count": 25,
        "num_pages": 2,
        "page": 2,
        "per_page": 20,
        "has_next": False,
        "has_previous": True,
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
    assert bad_page.status_code == 404


def test_autocomplete_uses_remote_model_admin_paginator_hook(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    tag_admin = site.get_model_admin(Tag)
    monkeypatch.setattr(product_admin, "autocomplete_fields", ("tags",))
    Tag.objects.bulk_create(Tag(name=f"Tag {index:02d}") for index in range(3))
    calls = {}

    def get_paginator(request, queryset, per_page, orphans=0, allow_empty_first_page=True):
        calls["path"] = request.path
        calls["model"] = queryset.model
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
        },
    )

    assert response.status_code == 200
    assert calls == {
        "path": "/admin-api/autocomplete",
        "model": Tag,
        "per_page": 20,
        "orphans": 0,
        "allow_empty_first_page": True,
    }


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_autocomplete_uses_remote_related_to_field(admin_client):
    Category.objects.create(name="Cameras", slug="cameras")
    Category.objects.create(name="Accessories", slug="accessories")
    source_model_name = CategorySlugLink._meta.model_name

    form = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink/form")
    assert form.status_code == 200
    fields_by_name = {field["name"]: field for field in form.json()["form"]["fields"]}
    assert fields_by_name["category"]["attrs"]["to_field_name"] == "slug"
    assert fields_by_name["category"]["attrs"]["autocomplete"] == {
        "app_label": "testapp",
        "model_name": source_model_name,
        "field_name": "category",
    }

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
    assert body["perms_needed"] == ["product"]
    assert body["model_count"]["testapp.product"] == 1
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
    assert response.json()["errors"] == {"0": [{"message": "Permission denied.", "param": "pk"}]}
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
    assert response.json()["errors"]["0"] == [{"message": "Object not found.", "param": "pk"}]
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
    assert errors["0"][0]["param"] == "stock_status"
    assert errors["1"] == [{"message": "Object not found.", "param": "pk"}]
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


def test_inline_mutations_reject_unknown_and_readonly_fields(admin_client, sample, monkeypatch):
    from tests.testapp.admin import ProductImageInline

    image = sample.images.get()
    unknown_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side", "bogus": "x"}]}},
        },
        content_type="application/json",
    )
    assert unknown_response.status_code == 422
    assert unknown_response.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.change.0.bogus"}
    ]

    monkeypatch.setattr(ProductImageInline, "readonly_fields", ("title",))
    readonly_response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"change": [{"pk": image.pk, "title": "Side"}]}}},
        content_type="application/json",
    )
    assert readonly_response.status_code == 400
    assert readonly_response.json()["errors"]["testapp.productimage"]["change"]["0"] == [
        {"message": "Unknown or readonly inline field.", "param": "title"}
    ]
    image.refresh_from_db()
    assert image.title == "Front"


def test_inline_mutations_reject_unknown_inline_keys(admin_client, sample):
    unknown_inline = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.unknown": {"add": []}}},
        content_type="application/json",
    )
    assert unknown_inline.status_code == 422
    assert unknown_inline.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.unknown"}
    ]

    unknown_operation = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={"data": {}, "inlines": {"testapp.productimage": {"replace": []}}},
        content_type="application/json",
    )
    assert unknown_operation.status_code == 422
    assert unknown_operation.json()["errors"] == [
        {"message": "Extra inputs are not permitted", "param": "inlines.testapp.productimage.replace"}
    ]


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
    deleted_image = ProductImage.objects.create(product=sample, title="Back")
    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {},
            "inlines": {
                "testapp.productimage": {
                    "change": [{"pk": image.pk, "title": "Profile"}],
                    "add": [{"title": "Side"}],
                    "delete": [deleted_image.pk],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    inline_response = response.json()["inlines"]["testapp.productimage"]
    assert "_changed_fields" not in inline_response["change"][0]
    assert inline_response["delete"] == [deleted_image.pk]
    change_entry = LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).latest("action_time")
    change_message = json.loads(change_entry.change_message)
    assert {"added": {"name": "product image", "object": "Side"}} in change_message
    assert {"changed": {"name": "product image", "object": "Profile", "fields": ["title"]}} in change_message
    assert {"deleted": {"name": "product image", "object": "Back"}} in change_message
    history = admin_client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": CHANGE},
    )
    assert history.status_code == 200
    assert history.json()["results"][0]["change_message_text"] == (
        "Added product image \u201cSide\u201d. "
        "Changed title for product image \u201cProfile\u201d. "
        "Deleted product image \u201cBack\u201d."
    )


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


def test_inline_mutation_aggregates_server_side_row_errors(admin_client, sample):
    image = sample.images.get()
    other = ProductImage.objects.create(product=sample, title="Back")

    response = admin_client.patch(
        f"/admin-api/testapp/product/{sample.pk}",
        data={
            "data": {"price": "99.00"},
            "inlines": {
                "testapp.productimage": {
                    "change": [
                        {"pk": image.pk, "title": "Profile"},
                        {"pk": other.pk, "title": "Back A"},
                        {"pk": other.pk, "title": "Back B"},
                        {"pk": 999999, "title": "Ghost"},
                    ],
                    "delete": [image.pk, 999999],
                }
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    errors = response.json()["errors"]["testapp.productimage"]
    assert errors["change"]["0"] == [
        {
            "message": "Inline object cannot be changed and deleted in the same request.",
            "param": "pk",
        }
    ]
    assert errors["change"]["2"] == [{"message": "Duplicate inline change pk.", "param": "pk"}]
    assert errors["change"]["3"] == [{"message": "Unknown inline object.", "param": "pk"}]
    assert errors["delete"]["1"] == [{"message": "Unknown inline object.", "param": "pk"}]
    image.refresh_from_db()
    other.refresh_from_db()
    sample.refresh_from_db()
    assert image.title == "Front"
    assert other.title == "Back"
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


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
    assert response.json()["errors"]["testapp.productimage"]["change"]["0"][0]["message"] == "Unknown inline object."
    sample.refresh_from_db()
    assert str(sample.price) == "12.50"
    assert not LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).exists()


def test_schema_field_overrides_are_included_and_serialize_admin_methods(sample):
    class ProductAdminWithOverride(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None)}

        @display(description="Custom note")
        def custom_note(self, obj):
            return f"{obj.name}:{obj.stock_status}"

    admin_site = NinjaAdminSite(include_auth=False)
    model_admin = ProductAdminWithOverride(Product, admin_site)

    assert "custom_note" in model_admin.get_output_schema().model_fields
    assert model_admin.serialize_object(sample)["custom_note"] == "Alpha:in_stock"


def test_admin_checks_validate_schema_field_overrides(db):
    class ValidSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None), "score": (int,)}

    class BadMappingSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = [("custom_note", str)]

    class BadKeySchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {123: str}

    class BadTupleSchemaOverrideProductAdmin(ModelAdmin):
        schema_field_overrides = {"custom_note": (str, None, "extra")}

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidSchemaOverrideProductAdmin)
    bad_mapping_site = NinjaAdminSite(include_auth=False)
    bad_mapping_site.register(Product, BadMappingSchemaOverrideProductAdmin)
    bad_key_site = NinjaAdminSite(include_auth=False)
    bad_key_site.register(Product, BadKeySchemaOverrideProductAdmin)
    bad_tuple_site = NinjaAdminSite(include_auth=False)
    bad_tuple_site.register(Product, BadTupleSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {"django_ninja_admin.E098", "django_ninja_admin.E099", "django_ninja_admin.E100"}
    )
    assert bad_mapping_ids == {"django_ninja_admin.E098"}
    assert bad_key_ids == {"django_ninja_admin.E099"}
    assert bad_tuple_ids == {"django_ninja_admin.E100"}


def test_admin_checks_validate_form_schema_field_overrides(db):
    class ValidFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": dict[str, int], "score": (int,)}

    class BadMappingFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = [("metadata", dict[str, int])]

    class BadKeyFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {123: str}

    class BadTupleFormSchemaOverrideProductAdmin(ModelAdmin):
        form_schema_field_overrides = {"metadata": (dict[str, int], None, "extra")}

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFormSchemaOverrideProductAdmin)
    bad_mapping_site = NinjaAdminSite(include_auth=False)
    bad_mapping_site.register(Product, BadMappingFormSchemaOverrideProductAdmin)
    bad_key_site = NinjaAdminSite(include_auth=False)
    bad_key_site.register(Product, BadKeyFormSchemaOverrideProductAdmin)
    bad_tuple_site = NinjaAdminSite(include_auth=False)
    bad_tuple_site.register(Product, BadTupleFormSchemaOverrideProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    bad_mapping_ids = {error.id for error in bad_mapping_site.get_model_admin(Product).check()}
    bad_key_ids = {error.id for error in bad_key_site.get_model_admin(Product).check()}
    bad_tuple_ids = {error.id for error in bad_tuple_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint(
        {"django_ninja_admin.E101", "django_ninja_admin.E102", "django_ninja_admin.E103"}
    )
    assert bad_mapping_ids == {"django_ninja_admin.E101"}
    assert bad_key_ids == {"django_ninja_admin.E102"}
    assert bad_tuple_ids == {"django_ninja_admin.E103"}


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
