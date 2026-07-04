from django.test import Client, override_settings

from django_ninja_admin import NinjaAdminSite
from django_ninja_admin.schemas import ErrorResponse


class _ClassAttrThrottleSite(NinjaAdminSite):
    history_throttle = object()
    autocomplete_throttle = object()


def _assert_typed_throttle_response(response):
    assert response.status_code == 429
    assert response["Retry-After"] == "1"
    body = response.json()
    ErrorResponse.model_validate(body)
    assert body == {"errors": [{"message": "Too many requests.", "param": "non_field_errors"}]}


def test_site_throttle_constructor_preserves_subclass_defaults():
    site = _ClassAttrThrottleSite(auth=None, include_auth=False)

    assert site.history_throttle is _ClassAttrThrottleSite.history_throttle
    assert site.autocomplete_throttle is _ClassAttrThrottleSite.autocomplete_throttle


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_changelist_autocomplete_and_custom_routes_support_throttles(admin_client, sample):
    first_list = admin_client.get("/throttled-admin/testapp/product")
    second_list = admin_client.get("/throttled-admin/testapp/product")

    assert first_list.status_code == 200
    _assert_typed_throttle_response(second_list)

    autocomplete_params = {
        "app_label": "testapp",
        "model_name": "product",
        "field_name": "category",
        "term": "Cam",
    }
    first_autocomplete = admin_client.get("/throttled-admin/autocomplete", autocomplete_params)
    second_autocomplete = admin_client.get("/throttled-admin/autocomplete", autocomplete_params)

    assert first_autocomplete.status_code == 200
    _assert_typed_throttle_response(second_autocomplete)

    first_history = admin_client.get("/throttled-admin/history")
    second_history = admin_client.get("/throttled-admin/history")

    assert first_history.status_code == 200
    _assert_typed_throttle_response(second_history)

    first_custom = Client().get("/throttled-admin/limited-status")
    second_custom = Client().get("/throttled-admin/limited-status")

    assert first_custom.status_code == 200
    _assert_typed_throttle_response(second_custom)


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_throttled_routes_advertise_typed_429_responses(admin_client):
    schema = admin_client.get("/throttled-admin/openapi.json").json()
    paths = schema["paths"]

    assert paths["/throttled-admin/testapp/product"]["get"]["responses"]["429"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}
    assert paths["/throttled-admin/autocomplete"]["get"]["responses"]["429"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}
    assert paths["/throttled-admin/history"]["get"]["responses"]["429"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert paths["/throttled-admin/limited-status"]["get"]["responses"]["429"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}
