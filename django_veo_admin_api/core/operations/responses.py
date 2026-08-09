from collections.abc import Callable
from typing import Any

from django.utils.translation import gettext as _
from pydantic import TypeAdapter

from django_veo_admin_api.core.exceptions import AdminValidationError
from django_veo_admin_api.core.operations.base import OperationResult
from django_veo_admin_api.schemas import ErrorResponse

type StatusResponseResolver = Callable[[Any], OperationResult[Any] | None]


def validate_mutation_response(
    response,
    *,
    default_status,
    default_schema,
    hook_schema,
    hook_name,
    plain_status=None,
    status_resolver: StatusResponseResolver | None = None,
):
    resolved = response if isinstance(response, OperationResult) else None
    if resolved is None and status_resolver is not None:
        resolved = status_resolver(response)
    if resolved is not None:
        status_code = resolved.status_code
        value = resolved.data
        explicit_status = True
    elif plain_status is not None and response is not None:
        status_code = plain_status
        value = response
        explicit_status = True
    else:
        status_code = default_status
        value = response
        explicit_status = False
    response_schema = mutation_response_schema(
        status_code,
        default_status=default_status,
        default_schema=default_schema,
        hook_schema=hook_schema,
        hook_name=hook_name,
        explicit_status=explicit_status,
    )
    if response_schema is None:
        if value is not None:
            raise AdminValidationError([{"message": _("Response status does not allow a body."), "param": hook_name}])
    else:
        TypeAdapter(response_schema).validate_python(value)
    return OperationResult(value, status_code=status_code)


def mutation_response_schema(
    status_code,
    *,
    default_status,
    default_schema,
    hook_schema,
    hook_name,
    explicit_status,
):
    if status_code == 204:
        return None
    custom_responses = _custom_hook_responses(hook_schema, (200, 202))
    if status_code == default_status and not (explicit_status and status_code in custom_responses):
        return default_schema
    if status_code in custom_responses:
        return custom_responses[status_code]
    raise AdminValidationError([{"message": _("Unsupported response status."), "param": hook_name}])


def validate_action_response(
    response,
    *,
    response_schema,
    status_resolver: StatusResponseResolver | None = None,
):
    resolved = response if isinstance(response, OperationResult) else None
    if resolved is None and status_resolver is not None:
        resolved = status_resolver(response)
    if resolved is not None:
        status_code = resolved.status_code
        value = resolved.data
    else:
        status_code = 200
        value = response
    if status_code == 204:
        if value is not None:
            raise AdminValidationError([{"message": _("Response status does not allow a body."), "param": "action"}])
        return OperationResult(None, status_code=status_code)
    if status_code in {200, 202}:
        value = TypeAdapter(response_schema).validate_python(value)
        return OperationResult(value, status_code=status_code)
    if status_code in {400, 403, 409}:
        value = TypeAdapter(ErrorResponse).validate_python(value)
        return OperationResult(value, status_code=status_code)
    raise AdminValidationError([{"message": _("Unsupported response status."), "param": "action"}])


def _custom_hook_responses(schema, statuses):
    if schema is None:
        return {}
    if isinstance(schema, dict):
        return schema
    return dict.fromkeys(statuses, schema)
