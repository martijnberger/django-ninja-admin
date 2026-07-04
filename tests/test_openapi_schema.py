import pytest
from django.test import Client
from pydantic import ValidationError as PydanticValidationError

from django_ninja_admin.schemas import ErrorResponse


def _response_schema_ref(operation, status):
    return operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def test_docs_and_openapi_require_site_auth(db):
    client = Client()

    for path in ("/admin-api/docs", "/admin-api/openapi.json"):
        response = client.get(path)

        assert response.status_code == 401
        body = response.json()
        ErrorResponse.model_validate(body)
        assert body["errors"] == [{"message": "Authentication required.", "param": "non_field_errors"}]


def test_error_response_openapi_schema_is_semantic_and_stable(admin_client, sample):
    schema = admin_client.get("/admin-api/openapi.json").json()
    components = schema["components"]["schemas"]

    assert components["ErrorItem"] == {
        "additionalProperties": False,
        "properties": {
            "message": {"$ref": "#/components/schemas/ErrorMessage"},
            "param": {
                "default": "non_field_errors",
                "title": "Param",
                "type": "string",
            },
        },
        "required": ["message"],
        "title": "ErrorItem",
        "type": "object",
    }
    assert components["ErrorMessage"] == {
        "anyOf": [
            {"type": "string"},
            {"items": {"type": "string"}, "type": "array"},
        ]
    }
    assert components["DeletedObject"] == {
        "anyOf": [
            {"type": "string"},
            {"items": {"$ref": "#/components/schemas/DeletedObject"}, "type": "array"},
        ]
    }
    assert components["ErrorResponse"]["required"] == ["errors"]
    assert components["ErrorResponse"]["properties"] == {
        "errors": {
            "items": {"$ref": "#/components/schemas/ErrorItem"},
            "title": "Errors",
            "type": "array",
        },
        "deleted_objects": {
            "anyOf": [
                {"items": {"$ref": "#/components/schemas/DeletedObject"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Deleted Objects",
        },
        "protected": {
            "anyOf": [
                {"items": {"type": "string"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Protected",
        },
        "perms_needed": {
            "anyOf": [
                {"items": {"type": "string"}, "type": "array"},
                {"type": "null"},
            ],
            "title": "Perms Needed",
        },
        "model_count": {
            "anyOf": [
                {"additionalProperties": {"type": "integer"}, "type": "object"},
                {"type": "null"},
            ],
            "title": "Model Count",
        },
    }

    for path, method, status in [
        ("/admin-api/apps", "get", "401"),
        ("/admin-api/testapp/product", "post", "422"),
        ("/admin-api/testapp/product", "get", "403"),
        ("/admin-api/testapp/product/{object_id}", "get", "404"),
        ("/admin-api/testapp/product/{object_id}", "delete", "409"),
    ]:
        assert _response_schema_ref(schema["paths"][path][method], status) == "#/components/schemas/ErrorResponse"
    ErrorResponse.model_validate(
        {
            "errors": [{"message": ["This field is required."], "param": "name"}],
            "deleted_objects": ["Alpha", ["Front", ["Nested child"]]],
        }
    )
    with pytest.raises(PydanticValidationError):
        ErrorResponse.model_validate({"errors": [{"message": {"detail": "Nope"}, "param": "name"}]})
