"""MCP-specific envelopes around shared core contracts."""

from django_veo_admin_api.schemas import AdminSchema, ErrorResponse


class MCPToolResponse[ResultT](AdminSchema):
    data: ResultT | None = None
    error: ErrorResponse | None = None
