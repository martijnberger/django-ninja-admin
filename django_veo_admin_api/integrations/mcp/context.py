"""Authenticated request boundary for the MCP integration."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from django.http import HttpRequest
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context


@dataclass(frozen=True, slots=True)
class MCPRequestInfo:
    """Verified SDK auth state and untrusted transport metadata for one call."""

    protocol_version: str
    headers: Mapping[str, str]
    access_token: Any | None


type DjangoRequestFactory = Callable[[MCPRequestInfo], HttpRequest]


def request_info(context: Context | Any) -> MCPRequestInfo:
    request_context = context.request_context if isinstance(context, Context) else context
    raw_request = getattr(request_context, "request", None)
    headers = getattr(raw_request, "headers", None) or {}
    return MCPRequestInfo(
        protocol_version=str(getattr(request_context, "protocol_version", "")),
        headers=headers,
        access_token=get_access_token(),
    )
