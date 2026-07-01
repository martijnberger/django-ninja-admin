import json
from datetime import datetime

import pytest
from django import forms
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.test import Client, RequestFactory, override_settings
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import isolate_apps
from django.utils import timezone
from ninja.security import SessionAuthIsStaff

from django_ninja_admin import (
    VERTICAL,
    EmptyFieldListFilter,
    ModelAdmin,
    NinjaAdminSite,
    SimpleListFilter,
    TabularInline,
    display,
    register,
    site,
)
from django_ninja_admin.changelist import ChangeList
from django_ninja_admin.exceptions import AlreadyRegistered, NotRegistered
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
    multipart_schema = schema_body["paths"]["/admin-api/testapp/product/multipart"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]
    assert multipart_schema["properties"]["manual"] == {"type": "string", "format": "binary"}
    assert multipart_schema["required"] == ["data"]
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


def test_admin_checks_validate_form_class(db):
    class ProductAdminForm(forms.ModelForm):
        class Meta:
            model = Product
            fields = ("name", "category", "price", "stock_status")

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

    valid_site = NinjaAdminSite(include_auth=False)
    valid_site.register(Product, ValidFormProductAdmin)
    plain_site = NinjaAdminSite(include_auth=False)
    plain_site.register(Product, PlainFormProductAdmin)
    wrong_model_site = NinjaAdminSite(include_auth=False)
    wrong_model_site.register(Product, WrongModelFormProductAdmin)

    valid_ids = {error.id for error in valid_site.get_model_admin(Product).check()}
    plain_ids = {error.id for error in plain_site.get_model_admin(Product).check()}
    wrong_model_ids = {error.id for error in wrong_model_site.get_model_admin(Product).check()}

    assert valid_ids.isdisjoint({"django_ninja_admin.E058", "django_ninja_admin.E059"})
    assert plain_ids == {"django_ninja_admin.E058"}
    assert wrong_model_ids == {"django_ninja_admin.E059"}


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

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, MissingFromFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, ExcludedProductAdmin)

    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert "django_ninja_admin.E044" in {error.id for error in fields_errors}
    assert "django_ninja_admin.E044" in {error.id for error in exclude_errors}


def test_admin_checks_validate_fields_and_exclude_items(db):
    class BadFieldsProductAdmin(ModelAdmin):
        fields = ("name", 123)

    class BadExcludeProductAdmin(ModelAdmin):
        exclude = ("missing", 123)

    fields_site = NinjaAdminSite(include_auth=False)
    fields_site.register(Product, BadFieldsProductAdmin)
    exclude_site = NinjaAdminSite(include_auth=False)
    exclude_site.register(Product, BadExcludeProductAdmin)

    fields_errors = fields_site.check(app_configs=[django_apps.get_app_config("testapp")])
    exclude_errors = exclude_site.check(app_configs=[django_apps.get_app_config("testapp")])

    assert {error.id for error in fields_errors} == {"django_ninja_admin.E048"}
    assert {error.id for error in exclude_errors} == {"django_ninja_admin.E048", "django_ninja_admin.E049"}


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
    initial = admin_client.get("/admin-api/testapp/product")
    assert initial.status_code == 200
    assert {
        item["parameter_name"] for item in initial.json()["config"]["filters"]
    } == {"stock_status__exact", "price_band"}

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
    assert show_all_body["config"]["full_count"] == 3
    assert show_all_body["config"]["show_all"] is True
    assert show_all_body["config"]["can_show_all"] is True
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


def test_changelist_row_metadata_honors_object_permissions(staff_client, sample):
    response = staff_client("view_product").get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert row["delete_url"] is None
    assert row["permissions"] == {
        "has_add_permission": False,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_changelist_action_ui_metadata_follows_model_admin(admin_client, sample, monkeypatch):
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
    assert {field["name"] for field in response.json()["action_form"]} == {"action", "selected_ids", "select_across"}


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
    assert body["config"]["ordering"] == ["price", "-name"]
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

    denied = staff_client().get("/custom-admin/testapp/product/stats")
    assert denied.status_code == 403

    schema = admin_client.get("/custom-admin/openapi.json").json()
    status_operation = schema["paths"]["/custom-admin/status"]["get"]
    token_operation = schema["paths"]["/custom-admin/token-status"]["get"]
    public_operation = schema["paths"]["/custom-admin/public-status"]["get"]
    stats_operation = schema["paths"]["/custom-admin/testapp/product/stats"]["get"]
    assert status_operation["operationId"] == "custom_site_status"
    assert status_operation["tags"] == ["custom.site"]
    assert status_operation["security"] == [{"SessionAuthIsStaff": []}]
    assert _response_schema_ref(status_operation, "200") == "#/components/schemas/SiteStatusResponse"
    assert token_operation["operationId"] == "custom_token_status"
    assert token_operation["tags"] == ["custom.auth"]
    assert {"PrimaryTokenAuth": []} in token_operation["security"]
    assert {"SecondaryTokenAuth": []} in token_operation["security"]
    assert _response_schema_ref(token_operation, "200") == "#/components/schemas/AuthStatusResponse"
    assert public_operation["operationId"] == "custom_public_status"
    assert public_operation["tags"] == ["custom.public"]
    assert "security" not in public_operation
    assert _response_schema_ref(public_operation, "200") == "#/components/schemas/PublicStatusResponse"
    assert stats_operation["operationId"] == "custom_product_stats"
    assert stats_operation["tags"] == ["custom.product"]
    assert stats_operation["summary"] == "Product stats"
    assert stats_operation["description"] == "Custom product statistics."
    assert _response_schema_ref(stats_operation, "200") == "#/components/schemas/ProductStatsResponse"
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
    assert fields_by_name["description"]["attrs"]["help_text"] == "Describe the product carefully."
    assert fields_by_name["description"]["attrs"]["widget"] == "Textarea"
    assert fields_by_name["description"]["attrs"]["widget_attrs"]["data-hook"] == "override"
    assert fields_by_name["description"]["attrs"]["widget_attrs"]["rows"] == 4
    assert fields_by_name["stock_status"]["attrs"]["choices"] == [["in_stock", "Available"]]
    assert fields_by_name["stock_status"]["attrs"]["widget"] == "RadioSelect"
    assert fields_by_name["stock_status"]["attrs"]["admin_widget"] == "radio"
    assert fields_by_name["stock_status"]["attrs"]["radio_orientation"] == VERTICAL
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
    assert invalid_name.status_code == 400
    assert invalid_name.json()["errors"]["form"][0]["param"] == "name"

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
    assert body["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert body["config"]["date_hierarchy"]["back_query_string"] is None
    assert [choice["value"] for choice in body["config"]["date_hierarchy"]["choices"]] == [2024, 2025]

    by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2024&_facets=1")
    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == 2
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

    filtered = client.get(
        "/admin-api/history",
        {"app_label": "testapp", "model": "product", "object_id": str(sample.pk), "action_flag": ADDITION},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["results"]] == [product_addition.pk]

    forbidden = client.get("/admin-api/history", {"app_label": "testapp", "model": "category"})
    assert forbidden.status_code == 403

    missing_app_label = client.get("/admin-api/history", {"model": "product"})
    assert missing_app_label.status_code == 400
    assert missing_app_label.json()["errors"] == [
        {"message": "app_label is required when model is provided.", "param": "app_label"}
    ]

    bad_page = client.get("/admin-api/history", {"page": 0})
    assert bad_page.status_code == 404


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
    assert first_page.json()["pagination"] == {"more": True}

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
    assert second_page.json()["pagination"] == {"more": False}
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
    save_calls = []
    original_save_model = product_admin.save_model

    def save_model(request, obj, form, change):
        save_calls.append(obj.pk)
        return original_save_model(request, obj, form, change)

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
    assert save_calls == [sample.pk]
    assert LogEntry.objects.filter(object_id=str(sample.pk), action_flag=CHANGE).count() == 1
    assert not LogEntry.objects.filter(object_id=str(beta.pk), action_flag=CHANGE).exists()
    sample.refresh_from_db()
    beta.refresh_from_db()
    assert sample.stock_status == "out_of_stock"
    assert beta.stock_status == "out_of_stock"


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
