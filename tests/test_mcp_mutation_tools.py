from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from mcp import Client

from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.integrations.mcp import MCPAdminServer
from django_veo_admin_api.models import ADDITION, LogEntry
from tests.testapp.admin import ProductAdmin
from tests.testapp.models import Product


def make_adapter(user):
    admin_site = CoreAdminSite(include_auth=False)
    admin_site.register(Product, ProductAdmin)

    def request_factory(info):
        request = RequestFactory().get("/mcp")
        request.user = user
        return request

    return MCPAdminServer(admin_site, request_factory)


def test_mutation_tools_use_generated_schemas_and_core_operations(sample):
    user = get_user_model().objects.create_superuser("mcp-mutation-admin", password="pw")
    adapter = make_adapter(user)

    async def exercise():
        async with Client(adapter.server) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            prefix = "admin.testapp.product"
            assert {
                f"{prefix}.create",
                f"{prefix}.update",
                f"{prefix}.bulk_update",
                f"{prefix}.actions",
                f"{prefix}.delete_preview",
                f"{prefix}.delete",
            } <= tools.keys()
            assert tools[f"{prefix}.create"].annotations.destructive_hint is True
            assert tools[f"{prefix}.delete_preview"].annotations.read_only_hint is True

            create_result = await client.call_tool(
                f"{prefix}.create",
                {
                    "payload": {
                        "data": {
                            "name": "MCP Gamma",
                            "category": sample.category_id,
                            "price": "9.00",
                            "stock_status": "in_stock",
                            "description": "Created through MCP",
                        },
                        "inlines": {"testapp.productimage": {"add": [{"title": "Side"}]}},
                    }
                },
            )
            assert create_result.is_error is False
            created_id = create_result.structured_content["data"]["data"]["id"]

            update_result = await client.call_tool(
                f"{prefix}.update",
                {"object_id": str(created_id), "payload": {"data": {"price": "11.00"}}},
            )
            assert update_result.is_error is False
            assert update_result.structured_content["data"]["data"]["price"] == "11.00"

            action_result = await client.call_tool(
                f"{prefix}.actions",
                {
                    "payload": {
                        "action": "report_names",
                        "selected_ids": [created_id],
                    }
                },
            )
            assert action_result.is_error is False
            assert action_result.structured_content["data"] == {"names": ["MCP Gamma"]}

            bulk_result = await client.call_tool(
                f"{prefix}.bulk_update",
                {"payload": {"data": [{"pk": created_id, "stock_status": "out_of_stock"}]}},
            )
            assert bulk_result.is_error is False
            assert bulk_result.structured_content["data"]["data"]["0"]["stock_status"] == "out_of_stock"

            preview_result = await client.call_tool(
                f"{prefix}.delete_preview",
                {"object_id": str(created_id)},
            )
            assert preview_result.is_error is False
            assert preview_result.structured_content["data"]["can_delete"] is True

            delete_result = await client.call_tool(
                f"{prefix}.delete",
                {"object_id": str(created_id)},
            )
            assert delete_result.is_error is False
            assert delete_result.structured_content["data"] == {
                "deleted": True,
                "status_code": 204,
                "response": None,
            }

        return created_id

    created_id = async_to_sync(exercise)()
    assert not Product.objects.filter(pk=created_id).exists()
    assert LogEntry.objects.filter(object_id=str(created_id), action_flag=ADDITION).exists()


def test_mutation_tools_return_canonical_validation_and_permission_errors(sample):
    superuser = get_user_model().objects.create_superuser("mcp-validation-admin", password="pw")
    adapter = make_adapter(superuser)

    async def invalid_create():
        async with Client(adapter.server) as client:
            return await client.call_tool(
                "admin.testapp.product.create",
                {
                    "payload": {
                        "data": {
                            "name": "Invalid relation",
                            "category": 999999,
                            "price": "9.00",
                            "stock_status": "in_stock",
                            "description": "",
                        }
                    }
                },
            )

    invalid_result = async_to_sync(invalid_create)()
    assert invalid_result.is_error is True
    assert invalid_result.structured_content["data"] is None
    assert invalid_result.structured_content["error"]["errors"][0]["param"] == "category"

    staff = get_user_model().objects.create_user("mcp-mutation-staff", password="pw", is_staff=True)
    denied_adapter = make_adapter(staff)

    async def denied_create():
        async with Client(denied_adapter.server) as client:
            return await client.call_tool(
                "admin.testapp.product.create",
                {
                    "payload": {
                        "data": {
                            "name": "Denied",
                            "category": sample.category_id,
                            "price": "9.00",
                            "stock_status": "in_stock",
                            "description": "",
                        }
                    }
                },
            )

    denied_result = async_to_sync(denied_create)()
    assert denied_result.is_error is True
    assert denied_result.structured_content["error"]["errors"] == [
        {"message": "Permission denied.", "param": "non_field_errors"}
    ]
