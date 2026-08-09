from typing import Any

from django.http import Http404
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.utils.quote import unquote


class ObjectOperations:
    """Permission-aware object lookup and detail serialization operations."""

    def get_object(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        object_id: str,
        to_field: str | None = None,
    ) -> OperationResult[Any]:
        request = context.request
        if to_field and not model_admin.to_field_allowed(request, to_field):
            raise AdminValidationError(
                [
                    {
                        "message": _("The field '%(field)s' cannot be referenced.") % {"field": to_field},
                        "param": "_to_field",
                    }
                ]
            )
        obj = model_admin.get_object(request, unquote(object_id), to_field)
        if obj is None:
            raise Http404
        return OperationResult(obj)

    def detail(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        object_id: str,
        to_field: str | None = None,
    ) -> OperationResult[Any]:
        obj = self.get_object(context, model_admin, object_id, to_field).data
        if not model_admin.has_view_or_change_permission(context.request, obj):
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
        return OperationResult(model_admin.serialize_object(obj, context.request))
