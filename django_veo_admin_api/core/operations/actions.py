from typing import Any

from django.db import router, transaction
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.responses import (
    StatusResponseResolver,
    validate_action_response,
)


class ActionOperations:
    """Dispatch registered admin actions against the filtered changelist queryset."""

    def __init__(self, *, status_resolver: StatusResponseResolver | None = None):
        self.status_resolver = status_resolver

    def execute(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        payload: Any,
        *,
        to_field: str | None = None,
    ) -> OperationResult[Any]:
        request = context.request
        if not model_admin.has_view_or_change_permission(request):
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
        queryset = model_admin.get_changelist_instance(request).queryset
        with transaction.atomic(using=router.db_for_write(model_admin.model)):
            response = model_admin.response_action(request, queryset, payload, to_field=to_field)
            return validate_action_response(
                response,
                response_schema=model_admin.get_action_response_schema(request),
                status_resolver=self.status_resolver,
            )
