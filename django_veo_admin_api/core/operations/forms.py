from typing import Any

from django.forms.models import _get_foreign_key
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, NotRegistered
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import FormResponse
from django_veo_admin_api.utils.forms import (
    fieldset_layout_description,
    form_field_descriptions,
    form_media_description,
)
from django_veo_admin_api.utils.quote import quote


def inline_remote_accessor_name(foreign_key):
    remote_field = foreign_key.remote_field
    if hasattr(remote_field, "get_accessor_name"):
        return remote_field.get_accessor_name()
    return remote_field.accessor_name


class FormOperations:
    """Permission-aware parent and inline form-description operations."""

    def __init__(self, admin_site: Any):
        self.admin_site = admin_site

    def describe(self, context: AdminRequestContext, model_admin: Any, obj: Any) -> OperationResult[FormResponse]:
        request = context.request
        if obj is None:
            allowed = model_admin.has_add_permission(request)
        else:
            allowed = model_admin.has_view_or_change_permission(request, obj)
        if not allowed:
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])

        data = model_admin.get_form_description(request, obj)
        inlines = []
        for inline in model_admin.get_inline_instances(request, obj):
            count_options = inline.get_formset_count_options(request, obj)
            formset_class = inline.get_formset(request, obj, change=obj is not None, count_options=count_options)
            queryset = inline.model.objects.none()
            if obj is not None:
                foreign_key = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
                related_name = inline_remote_accessor_name(foreign_key)
                try:
                    queryset = getattr(obj, related_name).all()
                except AttributeError:
                    queryset = inline.model.objects.none()
            formset = formset_class(instance=obj, queryset=queryset)
            initial_form_count = formset.initial_form_count()
            fieldsets = inline.get_fieldsets(request, obj)
            inline_description = {
                "model": f"{inline.model._meta.app_label}.{inline.model._meta.model_name}",
                "readonly_fields": list(inline.get_readonly_fields(request, obj)),
                "fieldset_layout": fieldset_layout_description(fieldsets),
                "prepopulated": dict(inline.get_prepopulated_fields(request, obj)),
                "media": form_media_description(formset_class.form()),
                "permissions": {
                    "has_add_permission": inline.has_add_permission(request, obj),
                    "has_change_permission": inline.has_change_permission(request, obj),
                    "has_delete_permission": inline.has_delete_permission(request, obj),
                    "has_view_permission": inline.has_view_permission(request, obj),
                },
                "formset_prefix": formset.prefix,
                "management_form": form_field_descriptions(
                    formset.management_form.__class__,
                    request=request,
                    form=formset.management_form,
                ),
                "total_form_count": formset.total_form_count(),
                "initial_form_count": initial_form_count,
                "empty_form_prefix": formset.empty_form.prefix,
                "empty_form": inline.get_form_fields_description(request, None, form=formset.empty_form),
                "formset_row_metadata": [],
                "extra": count_options["extra"],
                "min_num": count_options["min_num"],
                "max_num": count_options["max_num"],
                "verbose_name": str(inline.verbose_name),
                "verbose_name_plural": str(inline.verbose_name_plural),
                "can_delete": inline.can_delete,
                "show_change_link": inline.show_change_link,
                "admin_style": inline.admin_style,
                "formset": [],
            }
            for index, form in enumerate(formset.forms):
                form_obj = form.instance if getattr(form.instance, "pk", None) else None
                inline_description["formset"].append(inline.get_form_fields_description(request, form_obj, form=form))
                row_metadata = {
                    "index": index,
                    "prefix": form.prefix,
                    "is_initial": index < initial_form_count,
                    "empty_permitted": form.empty_permitted,
                }
                if form_obj is not None:
                    row_metadata["object_id"] = str(form_obj.pk)
                    row_metadata.update(self._inline_row_object_links(request, inline, form_obj))
                inline_description["formset_row_metadata"].append(row_metadata)
            inlines.append(inline_description)
        data["inlines"] = inlines
        return OperationResult(FormResponse.model_validate(data))

    def _inline_row_object_links(self, request, inline, obj):
        if not inline.show_change_link:
            return {}
        try:
            model_admin = self.admin_site.get_model_admin(inline.model)
        except NotRegistered:
            return {}
        has_view_permission = model_admin.has_view_permission(request, obj)
        has_change_permission = model_admin.has_change_permission(request, obj)
        if not has_view_permission and not has_change_permission:
            return {}
        base_path = self._admin_base_path_from_model_route(request, inline.parent_model)
        if base_path is None:
            return {}
        object_url = f"{base_path}/{inline.model._meta.app_label}/{inline.model._meta.model_name}/{quote(str(obj.pk))}"
        return {
            "detail_url": object_url,
            "change_form_url": f"{object_url}/form" if has_change_permission else None,
        }

    @staticmethod
    def _admin_base_path_from_model_route(request, model):
        path = getattr(request, "path", None) or getattr(request, "path_info", None) or ""
        marker = f"/{model._meta.app_label}/{model._meta.model_name}"
        index = path.find(marker)
        if index < 0:
            return None
        return path[:index].rstrip("/")
