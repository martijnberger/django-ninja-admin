from typing import Any

from django.db import router, transaction
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.objects import ObjectOperations
from django_veo_admin_api.core.operations.responses import StatusResponseResolver, validate_mutation_response
from django_veo_admin_api.schemas import DeletionPreview, ErrorResponse
from django_veo_admin_api.utils.deletion import deletion_error_payload, stringify_deleted_objects


class DeletionOperations:
    """Preview and execute permission-aware, protected-object-safe deletion."""

    def __init__(self, *, status_resolver: StatusResponseResolver | None = None):
        self.status_resolver = status_resolver
        self.object_operations = ObjectOperations()

    def preview(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        object_id: str,
        to_field: str | None = None,
    ) -> OperationResult[DeletionPreview]:
        request = context.request
        obj = self.object_operations.get_object(context, model_admin, object_id, to_field).data
        if not model_admin.has_delete_permission(request, obj):
            self._require_global_permission(model_admin.has_delete_permission(request))
        deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
        preview = DeletionPreview.model_validate(
            {
                "can_delete": model_admin.has_delete_permission(request, obj) and not protected and not perms_needed,
                "deleted_objects": stringify_deleted_objects(deleted_objects),
                "protected": [str(item) for item in protected],
                "perms_needed": sorted(str(permission) for permission in perms_needed),
                "model_count": model_count,
            }
        )
        return OperationResult(preview)

    def delete(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        object_id: str,
        to_field: str | None = None,
    ) -> OperationResult[Any]:
        request = context.request
        obj = self.object_operations.get_object(context, model_admin, object_id, to_field).data
        if not model_admin.has_delete_permission(request, obj):
            if model_admin.has_delete_permission(request):
                deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
                return self._error_result(
                    403,
                    _("Permission denied."),
                    deleted_objects=deleted_objects,
                    perms_needed=perms_needed,
                    protected=protected,
                    model_count=model_count,
                )
            self._require_global_permission(False)

        deleted_objects, model_count, perms_needed, protected = model_admin.get_deleted_objects([obj], request)
        if protected:
            return self._error_result(
                409,
                _("Cannot delete protected objects."),
                deleted_objects=deleted_objects,
                protected=protected,
                model_count=model_count,
            )
        if perms_needed:
            return self._error_result(
                403,
                _("Permission denied."),
                deleted_objects=deleted_objects,
                perms_needed=perms_needed,
                model_count=model_count,
            )

        obj_display = str(obj)
        obj_id = str(obj.pk)
        with transaction.atomic(using=router.db_for_write(model_admin.model)):
            model_admin.log_deletion(request, [obj])
            model_admin.delete_model(request, obj)
            response = model_admin.response_delete(request, obj_display, obj_id)
            return validate_mutation_response(
                response,
                default_status=204,
                default_schema=None,
                hook_schema=model_admin.get_response_delete_schema(request),
                hook_name="response_delete",
                plain_status=200,
                status_resolver=self.status_resolver,
            )

    @staticmethod
    def _error_result(status_code, message, **metadata):
        return OperationResult(
            ErrorResponse.model_validate(deletion_error_payload(message, **metadata)),
            status_code=status_code,
        )

    @staticmethod
    def _require_global_permission(allowed):
        if not allowed:
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "object_id"}])
