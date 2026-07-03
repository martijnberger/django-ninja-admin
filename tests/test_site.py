import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test import Client, override_settings
from django.test.utils import isolate_apps

from django_ninja_admin import ModelAdmin, NinjaAdminSite, register
from django_ninja_admin.exceptions import AlreadyRegistered, NotRegistered
from tests.testapp.models import Category, Product, Tag


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


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
