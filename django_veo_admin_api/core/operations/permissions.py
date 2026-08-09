from django_veo_admin_api.admins.model import ModelAdmin


def model_admin_method_overridden(model_admin, method_name):
    method = getattr(model_admin, method_name)
    base_method = getattr(ModelAdmin, method_name)
    return getattr(method, "__func__", method) is not base_method


def uses_object_visibility_permissions(model_admin):
    return model_admin_method_overridden(
        model_admin,
        "has_view_permission",
    ) or model_admin_method_overridden(
        model_admin,
        "has_change_permission",
    )
