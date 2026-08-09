from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from mcp import Client
from mcp.types import ListToolsResult

from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.integrations.mcp import MCPAdminServer, MCPRequestInfo, MCPToolPolicy
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product


def make_adapter(user, *, policy=None):
    admin_site = CoreAdminSite(include_auth=False)
    admin_site.register(Product, ProductAdmin)

    def request_factory(info):
        request = RequestFactory().get("/mcp")
        request.user = user
        return request

    return MCPAdminServer(admin_site, request_factory, policy=policy)


def test_read_tools_use_core_operations_and_structured_contracts(sample):
    user = get_user_model().objects.create_superuser("mcp-admin", password="pw", email="admin@example.com")
    adapter = make_adapter(user)

    async def exercise():
        async with Client(adapter.server) as client:
            tools = await client.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "admin.testapp.product.list" in tool_names
            assert "admin.testapp.product.detail" in tool_names
            assert "admin.testapp.product.form" in tool_names
            assert "admin.testapp.product.autocomplete" in tool_names
            assert all(tool.annotations.open_world_hint is False for tool in tools.tools)

            apps_result = await client.call_tool("admin.apps")
            assert apps_result.is_error is False
            assert any(
                model["model_name"] == "product"
                for app in apps_result.structured_content["data"]
                for model in app["models"]
            )

            list_result = await client.call_tool(
                "admin.testapp.product.list",
                {"params": {"q": "Alpha"}},
            )
            assert list_result.is_error is False
            assert [row["id"] for row in list_result.structured_content["data"]["rows"]] == [sample.pk]

            detail_result = await client.call_tool(
                "admin.testapp.product.detail",
                {"object_id": str(sample.pk)},
            )
            assert detail_result.is_error is False
            assert detail_result.structured_content["data"]["name"] == "Alpha"

            form_result = await client.call_tool(
                "admin.testapp.product.form",
                {"object_id": str(sample.pk)},
            )
            assert form_result.is_error is False
            assert any(field["name"] == "name" for field in form_result.structured_content["data"]["form"]["fields"])

            missing_result = await client.call_tool(
                "admin.testapp.product.detail",
                {"object_id": "999999"},
            )
            assert missing_result.is_error is True
            assert missing_result.structured_content == {
                "data": None,
                "error": {
                    "errors": [{"message": "Not found.", "param": "non_field_errors"}],
                    "deleted_objects": None,
                    "protected": None,
                    "perms_needed": None,
                    "model_count": None,
                },
            }

    async_to_sync(exercise)()


def test_tool_discovery_is_permission_and_policy_filtered(db):
    user = get_user_model().objects.create_user("mcp-staff", password="pw", is_staff=True)
    adapter = make_adapter(user, policy=MCPToolPolicy(deny=("admin.history",)))

    async def exercise():
        async with Client(adapter.server) as client:
            all_tools = await adapter.server.list_tools()

            class ListContext:
                method = "tools/list"
                protocol_version = "2026-07-28"
                request = None

            async def call_next(ctx):
                return ListToolsResult(tools=all_tools)

            filtered = await adapter._filter_tools(ListContext(), call_next)
            tool_names = {tool.name for tool in filtered.tools}
            assert tool_names == {"admin.apps", "admin.context", "admin.permissions"}

            apps_result = await client.call_tool("admin.apps")
            assert apps_result.structured_content == {"data": [], "error": None}

            denied_result = await client.call_tool("admin.history")
            assert denied_result.is_error is True
            assert denied_result.structured_content["error"]["errors"] == [
                {"message": "Permission denied.", "param": "non_field_errors"}
            ]

    async_to_sync(exercise)()

    allowed = adapter._allowed_tool_names_sync(MCPRequestInfo("2026-07-28", {}, None))
    assert allowed == {"admin.apps", "admin.context", "admin.permissions"}
