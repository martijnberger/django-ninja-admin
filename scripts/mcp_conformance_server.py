"""Minimal hosted adapter used by the official MCP transport conformance smoke."""

from __future__ import annotations

from typing import Annotated

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="mcp-conformance",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django_veo_admin_api",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
    )

import django

django.setup()

from django.test import RequestFactory  # noqa: E402
from mcp.server.mcpserver import Resolve, Sample  # noqa: E402
from mcp.types import CreateMessageResult, SamplingMessage, TextContent  # noqa: E402

from django_veo_admin_api.core import CoreAdminSite  # noqa: E402
from django_veo_admin_api.integrations.mcp import MCPAdminServer  # noqa: E402


class ConformanceUser:
    is_authenticated = True
    is_active = True
    is_staff = True
    is_superuser = True
    pk = "conformance"

    def has_perm(self, permission, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True


def request_factory(info):
    request = RequestFactory().get("/mcp")
    request.user = ConformanceUser()
    return request


adapter = MCPAdminServer(CoreAdminSite(include_auth=False), request_factory)


def require_sampling():
    return Sample(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text="conformance"))],
        max_tokens=1,
    )


async def test_missing_capability(
    sample: Annotated[CreateMessageResult, Resolve(require_sampling)],
) -> str:
    return sample.model_dump_json()


adapter.server.add_tool(
    test_missing_capability,
    name="test_missing_capability",
    description="Official conformance diagnostic for undeclared client capabilities.",
)
app = adapter.streamable_http_app(host="127.0.0.1")
