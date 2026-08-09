from django.test import Client, override_settings
from pydantic import BaseModel

from django_veo_admin_api.schemas import AdminSchema


def test_shared_schema_base_is_plain_pydantic():
    assert AdminSchema.__bases__ == (BaseModel,)


@override_settings(ROOT_URLCONF="tests.ninja_pydantic_urls")
def test_ninja_parses_and_serializes_plain_pydantic_contracts():
    client = Client()

    response = client.post(
        "/compat/echo",
        data={"inputMessage": "hello"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == [{"outputValue": "POST:hello"}]

    openapi = client.get("/compat/openapi.json").json()
    request_schema = openapi["paths"]["/compat/echo"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema == {"$ref": "#/components/schemas/CompatPayload"}
    assert openapi["components"]["schemas"]["CompatPayload"]["additionalProperties"] is False


@override_settings(ROOT_URLCONF="tests.ninja_pydantic_urls")
def test_ninja_rejects_extra_keys_for_plain_pydantic_request_bodies():
    response = Client().post(
        "/compat/echo",
        data={"inputMessage": "hello", "unexpected": True},
        content_type="application/json",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "payload", "unexpected"]
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
