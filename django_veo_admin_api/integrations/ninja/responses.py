from typing import Any

from ninja import Status

from django_veo_admin_api.core.operations.base import OperationResult


def resolve_ninja_status(response):
    if isinstance(response, Status):
        return OperationResult(response.value, status_code=response.status_code)
    return None


def ninja_operation_response(result: OperationResult[Any]):
    return Status(result.status_code, result.data)
