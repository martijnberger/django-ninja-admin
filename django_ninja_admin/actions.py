from django.core.exceptions import PermissionDenied
from django.db import router, transaction
from django.utils.translation import gettext_lazy as _


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
        return {"detail": _("Cannot delete protected objects."), "protected": [str(obj) for obj in protected]}
    if perms_needed:
        raise PermissionDenied

    with transaction.atomic(using=router.db_for_write(model_admin.model)):
        model_admin.log_deletion(request, list(queryset))
        model_admin.delete_queryset(request, queryset)
    return {"detail": _("Successfully deleted selected objects."), "deleted": model_count}


delete_selected.short_description = _("Delete selected objects")
delete_selected.allowed_permissions = ["delete"]

