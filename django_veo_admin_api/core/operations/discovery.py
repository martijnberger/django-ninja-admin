from typing import Any

from django.apps import apps
from django.http import Http404
from django.utils.text import capfirst

from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import AppSummary, PermissionsResponse, SiteContext


class DiscoveryOperations:
    """Permission-aware app discovery and site metadata operations."""

    def __init__(self, admin_site: Any):
        self.admin_site = admin_site

    def list_apps(
        self,
        context: AdminRequestContext,
        app_label: str | None = None,
    ) -> OperationResult[list[AppSummary] | AppSummary]:
        app_dict = self._build_app_dict(context, app_label)
        if app_label is not None:
            app = app_dict.get(app_label)
            if app is None:
                raise Http404
            app["models"].sort(key=lambda model: model["name"])
            return OperationResult(AppSummary.model_validate(app))

        app_list = sorted(app_dict.values(), key=lambda app: app["name"].lower())
        for app in app_list:
            app["models"].sort(key=lambda model: model["name"])
        return OperationResult([AppSummary.model_validate(app) for app in app_list])

    def site_context(self, context: AdminRequestContext) -> OperationResult[SiteContext]:
        apps_result = self.list_apps(context)
        available_apps = apps_result.data
        if not isinstance(available_apps, list):  # pragma: no cover - constrained by the call above
            raise TypeError("Expected the complete app list.")
        return OperationResult(
            SiteContext(
                site_title=self.admin_site.get_site_title(),
                site_header=self.admin_site.get_site_header(),
                site_url=self.admin_site.get_site_url(context.request),
                has_permission=self.admin_site.has_permission(context.request),
                available_apps=available_apps,
                is_nav_sidebar_enabled=self.admin_site.enable_nav_sidebar,
            )
        )

    def permissions(self, context: AdminRequestContext) -> OperationResult[PermissionsResponse]:
        apps_result = self.list_apps(context)
        app_list = apps_result.data
        if not isinstance(app_list, list):  # pragma: no cover - constrained by the call above
            raise TypeError("Expected the complete app list.")
        user = context.user
        return OperationResult(
            PermissionsResponse(
                is_authenticated=user.is_authenticated,
                is_active=user.is_active,
                is_staff=user.is_staff,
                is_superuser=user.is_superuser,
                has_permission=self.admin_site.has_permission(context.request),
                models=[model for app in app_list for model in app.models],
            )
        )

    def _build_app_dict(self, context: AdminRequestContext, label: str | None) -> dict[str, dict[str, Any]]:
        app_dict: dict[str, dict[str, Any]] = {}
        for model, model_admin in self.admin_site.get_registered_model_admins():
            if label is not None and model._meta.app_label != label:
                continue
            app_label = model._meta.app_label
            has_module_perms = model_admin.has_module_permission(context.request)
            if not has_module_perms:
                continue
            perms = model_admin.get_model_perms(context.request)
            if True not in perms.values():
                continue
            model_data = {
                "name": str(capfirst(model._meta.verbose_name_plural)),
                "object_name": model._meta.object_name,
                "app_label": app_label,
                "model_name": model._meta.model_name,
                "perms": perms,
            }
            if app_label in app_dict:
                app_dict[app_label]["models"].append(model_data)
            else:
                app_dict[app_label] = {
                    "name": str(apps.get_app_config(app_label).verbose_name),
                    "app_label": app_label,
                    "has_module_perms": has_module_perms,
                    "models": [model_data],
                }
        return app_dict
