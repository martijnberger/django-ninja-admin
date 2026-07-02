from django_ninja_admin.admins.model import ModelAdmin


class AuthUserAdmin(ModelAdmin):
    list_display = ("__str__", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name")
    sensitive_fields = ("password", "is_superuser", "user_permissions", "groups")

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        model_fields = {field.name for field in self.model._meta.get_fields()}
        excluded.extend(field for field in self.sensitive_fields if field in model_fields)
        return tuple(dict.fromkeys(excluded))


class AuthGroupAdmin(ModelAdmin):
    list_display = ("__str__",)
    search_fields = ("name",)
    sensitive_fields = ("permissions",)

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        model_fields = {field.name for field in self.model._meta.get_fields()}
        excluded.extend(field for field in self.sensitive_fields if field in model_fields)
        return tuple(dict.fromkeys(excluded))
