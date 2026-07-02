from django.core.exceptions import PermissionDenied
from django.db import router, transaction
from django.utils.translation import gettext_lazy as _
from ninja import Status

from django_ninja_admin.utils.deletion import deletion_error_payload


def delete_selected(model_admin, request, queryset):
    if not model_admin.has_delete_permission(request):
        raise PermissionDenied
    if not queryset:
        return {"detail": _("No objects selected.")}

    (
        deleted_objects,
        model_count,
        perms_needed,
        protected,
    ) = model_admin.get_deleted_objects(list(queryset), request)
    if protected:
        return Status(
            409,
            deletion_error_payload(
                _("Cannot delete protected objects."),
                param="selected_ids",
                deleted_objects=deleted_objects,
                protected=protected,
                model_count=model_count,
            ),
        )
    if perms_needed:
        return Status(
            403,
            deletion_error_payload(
                _("Permission denied."),
                param="selected_ids",
                deleted_objects=deleted_objects,
                perms_needed=perms_needed,
                model_count=model_count,
            ),
        )

    with transaction.atomic(using=router.db_for_write(model_admin.model)):
        model_admin.log_deletion(request, list(queryset))
        model_admin.delete_queryset(request, queryset)
    return {"detail": _("Successfully deleted selected objects."), "deleted": model_count}


delete_selected.short_description = _("Delete selected objects")
delete_selected.allowed_permissions = ["delete"]
