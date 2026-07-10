from typing import override

from django_ninja_admin.admins.model import ModelAdmin


def _existing_model_fields(model, field_names):
    model_fields = {field.name for field in (*model._meta.fields, *model._meta.many_to_many)}
    return tuple(field for field in field_names if field in model_fields)


class AuthUserAdmin(ModelAdmin):
    list_display = ("__str__", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    sensitive_fields = ("password", "is_superuser", "user_permissions", "groups")

    @override
    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        excluded.extend(_existing_model_fields(self.model, self.sensitive_fields))
        return tuple(dict.fromkeys(excluded))

    @override
    def get_output_exclude(self, request=None):
        excluded = list(super().get_output_exclude(request) or [])
        excluded.extend(_existing_model_fields(self.model, self.sensitive_fields))
        return tuple(dict.fromkeys(excluded))


class AuthGroupAdmin(ModelAdmin):
    list_display = ("__str__",)
    search_fields = ("name",)
    sensitive_fields = ("permissions",)

    @override
    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        excluded.extend(_existing_model_fields(self.model, self.sensitive_fields))
        return tuple(dict.fromkeys(excluded))

    @override
    def get_output_exclude(self, request=None):
        excluded = list(super().get_output_exclude(request) or [])
        excluded.extend(_existing_model_fields(self.model, self.sensitive_fields))
        return tuple(dict.fromkeys(excluded))
