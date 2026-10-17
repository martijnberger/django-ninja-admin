"""Exercise the deployed HTTP boundary, including SDK middleware and auth."""

import time
from threading import get_ident

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.backends.signals import connection_created
from django.test import RequestFactory
from jsonschema import Draft202012Validator
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import field_serializer
from starlette.testclient import TestClient

from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.core.operations import OperationResult
from django_veo_admin_api.integrations.mcp import MCPAdminServer, MCPToolPolicy
from django_veo_admin_api.models import LogEntry
from django_veo_admin_api.schemas import AdminSchema
from tests.testapp.models import Category

pytestmark = pytest.mark.django_db(transaction=True)


class TokenVerifier:
    def __init__(self, user):
        self.tokens = {
            "valid": AccessToken(
                token="valid",
                client_id="http-tests",
                subject=str(user.pk),
                scopes=["admin:use"],
                expires_at=int(time.time()) + 3600,
            ),
        }

    async def verify_token(self, token):
        return self.tokens.get(token)


def make_adapter(user, admin_class=ModelAdmin, *, policy=None):
    site = CoreAdminSite(include_auth=False)
    site.register(Category, admin_class)
    verifier = TokenVerifier(user)

    def request_factory(info):
        assert info.access_token is not None
        request = RequestFactory().get("/mcp")
        # Only the verified subject establishes identity, never caller headers.
        request.user = get_user_model().objects.get(pk=info.access_token.subject)
        request.LANGUAGE_CODE = "en"
        return request

    adapter = MCPAdminServer(
        site,
        request_factory,
        policy=policy,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url="https://issuer.example.com/",
            resource_server_url="http://127.0.0.1:8000/mcp",
            required_scopes=["admin:use"],
        ),
    )
    return adapter, verifier


def rpc(client, method, params=None, *, token="valid", headers=None):
    params = {
        **(params or {}),
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    request_headers = {
        "accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
        "host": "127.0.0.1:8000",
        **(headers or {}),
    }
    if "name" in params:
        request_headers["Mcp-Name"] = params["name"]
    if token is not None:
        request_headers["authorization"] = f"Bearer {token}"
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers=request_headers,
    )


def call_tool(client, name, arguments=None):
    response = rpc(client, "tools/call", {"name": f"admin.testapp.category.{name}", "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_http_discovery_filters_permissions_policy_and_rechecks_active_user():
    user = get_user_model().objects.create_user("http-staff", is_staff=True)
    adapter, _ = make_adapter(user, policy=MCPToolPolicy(deny=("admin.history",)))
    with TestClient(adapter.streamable_http_app()) as client:
        response = rpc(client, "tools/list", headers={"x-user-id": "superuser"})
        assert response.status_code == 200
        result = response.json()["result"]
        assert {tool["name"] for tool in result["tools"]} == {"admin.apps", "admin.context", "admin.permissions"}
        assert result["cacheScope"] == "private"
        assert result["ttlMs"] == 0
        denied = call_tool(client, "create", {"payload": {"data": {"name": "Denied"}}})
        assert denied["isError"] is True
        assert denied["structuredContent"]["error"]["errors"][0]["message"] == "Permission denied."

        user.is_active = False
        user.save(update_fields=["is_active"])
        assert rpc(client, "tools/list").json()["result"]["tools"] == []
        assert call_tool(client, "form")["isError"] is True
    assert not Category.objects.filter(name="Denied").exists()


@pytest.mark.parametrize(
    ("token", "expected_status"),
    [(None, 401), ("invalid", 401), ("expired", 401), ("unscoped", 403)],
)
def test_http_bearer_auth_rejects_missing_invalid_expired_and_unscoped_tokens(token, expected_status):
    user = get_user_model().objects.create_superuser("http-auth-admin")
    adapter, verifier = make_adapter(user)
    verifier.tokens["expired"] = verifier.tokens["valid"].model_copy(update={"expires_at": int(time.time()) - 60})
    verifier.tokens["unscoped"] = verifier.tokens["valid"].model_copy(update={"scopes": []})
    with TestClient(adapter.streamable_http_app()) as client:
        response = rpc(client, "tools/list", token=token, headers={"x-user-id": str(user.pk)})
    assert response.status_code == expected_status
    assert "Bearer" in response.headers["www-authenticate"]


def test_http_revocation_is_applied_between_calls():
    user = get_user_model().objects.create_superuser("http-revocation-admin")
    adapter, verifier = make_adapter(user)
    with TestClient(adapter.streamable_http_app()) as client:
        assert rpc(client, "tools/list").status_code == 200
        verifier.tokens.clear()
        assert rpc(client, "tools/list").status_code == 401


def test_http_releases_request_database_connections():
    if connection.vendor != "postgresql":
        pytest.skip("SQLite intentionally keeps shared in-memory connections open.")
    user = get_user_model().objects.create_superuser("http-connection-admin")
    adapter, _ = make_adapter(user)
    caller_thread = get_ident()
    request_connections = []

    def capture_connection(sender, connection, **kwargs):
        if get_ident() != caller_thread:
            request_connections.append(connection)

    connection_created.connect(capture_connection)
    try:
        with TestClient(adapter.streamable_http_app()) as client:
            assert rpc(client, "tools/list").status_code == 200
            assert call_tool(client, "form").get("isError", False) is False
        assert request_connections
        assert all(connection.connection is None for connection in request_connections)
    finally:
        connection_created.disconnect(capture_connection)


def test_http_add_only_user_can_describe_add_form_but_not_existing_objects():
    user = get_user_model().objects.create_user("http-add-only", is_staff=True)
    user.user_permissions.add(Permission.objects.get(codename="add_category"))
    category = Category.objects.create(name="Existing")
    adapter, _ = make_adapter(user)
    with TestClient(adapter.streamable_http_app()) as client:
        tools = rpc(client, "tools/list").json()["result"]["tools"]
        assert "admin.testapp.category.form" in {tool["name"] for tool in tools}
        form = call_tool(client, "form")
        assert form.get("isError", False) is False
        assert form["structuredContent"]["data"]["form"]["permissions"]["has_add_permission"] is True
        existing = call_tool(client, "form", {"object_id": str(category.pk)})
        assert existing["isError"] is True


class Accepted(AdminSchema):
    object_id: int
    queued: bool


class Updated(AdminSchema):
    name: str


class HookAdmin(ModelAdmin):
    response_add_schema = {202: Accepted}
    response_change_schema = Updated

    def response_add(self, request, obj, form, inline_results):
        assert request.LANGUAGE_CODE == "en"
        return OperationResult({"object_id": obj.pk, "queued": True}, status_code=202)

    def response_change(self, request, obj, form, inline_results):
        return OperationResult({"name": obj.name}, status_code=200)


def test_http_custom_mutation_hooks_match_advertised_output_and_commit_once():
    user = get_user_model().objects.create_superuser("http-hooks-admin")
    adapter, _ = make_adapter(user, HookAdmin)
    with TestClient(adapter.streamable_http_app()) as client:
        tools = {tool["name"]: tool for tool in rpc(client, "tools/list").json()["result"]["tools"]}
        created = call_tool(client, "create", {"payload": {"data": {"name": "Queued"}}})
        assert created.get("isError", False) is False
        content = created["structuredContent"]
        Draft202012Validator(tools["admin.testapp.category.create"]["outputSchema"]).validate(content)
        category_id = content["data"]["object_id"]
        assert content["data"]["queued"] is True
        updated = call_tool(client, "update", {"object_id": str(category_id), "payload": {"data": {"name": "Updated"}}})
        assert updated.get("isError", False) is False
        Draft202012Validator(tools["admin.testapp.category.update"]["outputSchema"]).validate(
            updated["structuredContent"]
        )
        assert updated["structuredContent"]["data"] == {"name": "Updated"}
    assert Category.objects.get(pk=category_id).name == "Updated"
    assert Category.objects.count() == 1
    assert LogEntry.objects.filter(object_id=str(category_id)).count() == 2


def test_http_schema_drift_rolls_back_mutation_and_audit_entry():
    class RequestAwareHookAdmin(HookAdmin):
        def get_response_add_schema(self, request=None):
            return Accepted if request is None else Updated

        def response_add(self, request, obj, form, inline_results):
            return OperationResult({"name": obj.name}, status_code=202)

    user = get_user_model().objects.create_superuser("http-rollback-admin")
    adapter, _ = make_adapter(user, RequestAwareHookAdmin)
    with TestClient(adapter.streamable_http_app()) as client:
        result = call_tool(client, "create", {"payload": {"data": {"name": "Must roll back"}}})
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["errors"]
    assert not Category.objects.exists()
    assert not LogEntry.objects.exists()


def test_http_serialization_failure_rolls_back_without_logging_field_contents(caplog):
    class BrokenResponse(AdminSchema):
        secret: str

        @field_serializer("secret")
        def fail(self, value):
            raise ValueError(f"Cannot serialize {value}")

    class BrokenAdmin(ModelAdmin):
        response_add_schema = BrokenResponse

        def response_add(self, request, obj, form, inline_results):
            return OperationResult({"secret": "sensitive-value"}, status_code=202)

    user = get_user_model().objects.create_superuser("http-serialization-admin")
    adapter, _ = make_adapter(user, BrokenAdmin)
    with TestClient(adapter.streamable_http_app()) as client:
        result = call_tool(client, "create", {"payload": {"data": {"name": "Must roll back"}}})
    assert result["isError"] is True
    assert "sensitive-value" not in str(result)
    assert "sensitive-value" not in caplog.text
    assert not Category.objects.exists()
    assert not LogEntry.objects.exists()
