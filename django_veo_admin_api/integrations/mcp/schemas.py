"""MCP-specific envelopes around shared core contracts."""

from typing import Any

from django_veo_admin_api.schemas import AdminSchema, ErrorResponse


class MCPToolResponse[ResultT](AdminSchema):
    data: ResultT | None = None
    error: ErrorResponse | None = None


class MCPDeleteResult(AdminSchema):
    """Make no-content and custom delete responses explicit for MCP clients."""

    deleted: bool = True
    status_code: int
    response: Any = None
