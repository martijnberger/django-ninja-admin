from django.contrib.admin.utils import NestedObjects
from django.db import router

from django_ninja_admin.exceptions import NotRegistered


def get_deleted_objects(objs, request, admin_site):
    using = router.db_for_write(objs[0]._meta.model if objs else None)
    collector = NestedObjects(using=using)
    collector.collect(objs)
    perms_needed = set()
    model_count = {}
    for model, instances in collector.model_objs.items():
        opts = model._meta
        model_count[f"{opts.app_label}.{opts.model_name}"] = len(instances)
        try:
            model_admin = admin_site.get_model_admin(model)
        except NotRegistered:
            continue
        if not model_admin.has_delete_permission(request) or any(
            not model_admin.has_delete_permission(request, obj) for obj in instances
        ):
            perms_needed.add(opts.verbose_name)
    return collector.nested(), model_count, perms_needed, collector.protected


def stringify_deleted_objects(deleted_objects):
    if isinstance(deleted_objects, (list, tuple)):
        return [stringify_deleted_objects(item) for item in deleted_objects]
    return str(deleted_objects)


def deletion_error_payload(
    message,
    *,
    param="object_id",
    protected=None,
    perms_needed=None,
    model_count=None,
    deleted_objects=None,
):
    payload = {"errors": [{"message": message, "param": param}]}
    if deleted_objects:
        payload["deleted_objects"] = stringify_deleted_objects(deleted_objects)
    if protected:
        payload["protected"] = [str(obj) for obj in protected]
    if perms_needed:
        payload["perms_needed"] = sorted(str(perm) for perm in perms_needed)
    if model_count:
        payload["model_count"] = dict(model_count)
    return payload
