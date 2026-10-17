"""Optional Model Context Protocol integration."""

from django_veo_admin_api._optional import missing_mcp_dependency

try:
    from django_veo_admin_api.integrations.mcp.context import DjangoRequestFactory, MCPRequestInfo
    from django_veo_admin_api.integrations.mcp.policy import MCPToolPolicy
    from django_veo_admin_api.integrations.mcp.server import MCPAdminServer
except ModuleNotFoundError as exc:
    if exc.name == "mcp" or (exc.name or "").startswith("mcp."):
        raise missing_mcp_dependency(exc) from exc
    raise

__all__ = ["DjangoRequestFactory", "MCPAdminServer", "MCPRequestInfo", "MCPToolPolicy"]
