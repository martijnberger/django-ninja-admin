from django.contrib.auth import get_permission_codename
from django.utils.text import format_lazy

from django_ninja_admin.admins.base import BaseAdmin


class InlineModelAdmin(BaseAdmin):
    model = None
    fk_name = None
    extra = 3
    min_num = None
    max_num = None
    verbose_name = None
    verbose_name_plural = None
    can_delete = True
    show_change_link = False
    admin_style = "tabular"

    def __init__(self, parent_model, admin_site):
        self.admin_site = admin_site
        self.parent_model = parent_model
        self.opts = self.model._meta
        self.has_registered_model = admin_site.is_registered(self.model)
        if self.verbose_name_plural is None:
            if self.verbose_name is None:
                self.verbose_name_plural = self.opts.verbose_name_plural
            else:
                self.verbose_name_plural = format_lazy("{}s", self.verbose_name)
        if self.verbose_name is None:
            self.verbose_name = self.opts.verbose_name

    def get_extra(self, request, obj=None, **kwargs):
        return self.extra

    def get_min_num(self, request, obj=None, **kwargs):
        return self.min_num

    def get_max_num(self, request, obj=None, **kwargs):
        return self.max_num

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not self.has_view_or_change_permission(request):
            return queryset.none()
        return queryset

    def _has_any_perms_for_target_model(self, request, perms):
        opts = self.opts
        for field in opts.fields:
            if field.remote_field and field.remote_field.model != self.parent_model:
                opts = field.remote_field.model._meta
                break
        return any(
            request.user.has_perm(f"{opts.app_label}.{get_permission_codename(perm, opts)}")
            for perm in perms
        )

    def has_add_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["change"])
        return super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        if self.opts.auto_created:
            return self._has_any_perms_for_target_model(request, ["view", "change"])
        return super().has_view_permission(request, obj)


class TabularInline(InlineModelAdmin):
    admin_style = "tabular"


class StackedInline(InlineModelAdmin):
    admin_style = "stacked"
