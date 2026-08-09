"""Map core operation failures to MCP tool execution results."""

import json
import logging

from django.core.exceptions import PermissionDenied, SuspiciousOperation, ValidationError
from django.http import Http404
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError as PydanticValidationError

from django_veo_admin_api.core.exceptions import (
    AdminError,
    AdminPermissionError,
    AdminValidationError,
    MissingSearchFields,
    NotRegistered,
)
from django_veo_admin_api.schemas import ErrorResponse
from django_veo_admin_api.utils.format_error import format_error

logger = logging.getLogger(__name__)


def operation_error_result(exc: Exception, *, tool_name: str) -> CallToolResult:
    payload = _error_payload(exc)
    if payload is None:
        logger.exception("Unexpected MCP admin tool failure", extra={"tool_name": tool_name})
        payload = ErrorResponse.model_validate(
            {"errors": [{"message": "Operation failed.", "param": "non_field_errors"}]}
        )
    structured = {"data": None, "error": payload.model_dump(mode="json")}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured, sort_keys=True))],
        structured_content=structured,
        is_error=True,
    )


def operation_result_error(payload: ErrorResponse) -> CallToolResult:
    structured = {"data": None, "error": payload.model_dump(mode="json")}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured, sort_keys=True))],
        structured_content=structured,
        is_error=True,
    )


def _error_payload(exc: Exception) -> ErrorResponse | None:
    if isinstance(exc, (AdminValidationError, AdminPermissionError)):
        return ErrorResponse.model_validate({"errors": exc.errors})
    if isinstance(exc, MissingSearchFields):
        return _message("Missing search_fields.", "search_fields")
    if isinstance(exc, (Http404, NotRegistered)):
        return _message("Not found.")
    if isinstance(exc, (PermissionDenied,)):
        return _message("Permission denied.")
    if isinstance(exc, (ValidationError, PydanticValidationError, SuspiciousOperation)):
        return ErrorResponse.model_validate({"errors": format_error(exc)})
    if isinstance(exc, AdminError):
        return _message(str(exc) or "Operation failed.")
    return None


def _message(message: str, param: str = "non_field_errors") -> ErrorResponse:
    return ErrorResponse.model_validate({"errors": [{"message": message, "param": param}]})
