from django.contrib.admin.utils import NestedObjects
from django.db import router


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
        except Exception:
            continue
        if not model_admin.has_delete_permission(request):
            perms_needed.add(opts.verbose_name)
    return collector.nested(), model_count, perms_needed, collector.protected


def deletion_error_payload(message, *, param="object_id", protected=None, perms_needed=None, model_count=None):
    payload = {"errors": [{"message": message, "param": param}]}
    if protected:
        payload["protected"] = [str(obj) for obj in protected]
    if perms_needed:
        payload["perms_needed"] = sorted(str(perm) for perm in perms_needed)
    if model_count:
        payload["model_count"] = dict(model_count)
    return payload
