import json
from typing import Any

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.paginator import InvalidPage
from django.http import Http404
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError, NotRegistered
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.pagination import pagination_result, visibility_filtered_pagination_result
from django_veo_admin_api.core.operations.permissions import uses_object_visibility_permissions
from django_veo_admin_api.models import LogEntry
from django_veo_admin_api.schemas import HistoryActionFlag, HistoryResponse
from django_veo_admin_api.utils.json_values import jsonish_value
from django_veo_admin_api.utils.quote import quote

_UNSET = object()


class HistoryOperations:
    """Permission-filtered Django admin log discovery and serialization."""

    def __init__(self, admin_site: Any):
        self.admin_site = admin_site

    def list(
        self,
        context: AdminRequestContext,
        *,
        app_label: str | None = None,
        model_name: str | None = None,
        object_id: str | None = None,
        action_flag: HistoryActionFlag | None = None,
        ordering: str = "-action_time",
        page: int = 1,
        per_page: int = 20,
    ) -> OperationResult[HistoryResponse]:
        request = context.request
        content_type_ids = self._content_type_ids(
            request,
            app_label=app_label,
            model_name=model_name,
        )
        queryset = (
            LogEntry.objects.filter(content_type_id__in=content_type_ids)
            .order_by(ordering)
            .select_related("content_type")
        )
        if object_id is not None:
            queryset = queryset.filter(object_id=object_id)
        if action_flag is not None:
            queryset = queryset.filter(action_flag=int(action_flag))

        use_visibility_filter = self._requires_object_visibility_filter(content_type_ids)
        paginator = self.admin_site.paginator(queryset, per_page)
        try:
            page_obj = paginator.page(page)
        except InvalidPage as exc:
            raise Http404 from exc
        page_items = list(page_obj.object_list)
        visible_objects = {}
        if use_visibility_filter:
            visible_items = []
            for item in page_items:
                visible, obj = self._item_visibility(request, item)
                if visible:
                    visible_items.append(item)
                    visible_objects[item.pk] = obj
            page_items = visible_items

        results = []
        for item in page_items:
            try:
                message = json.loads(item.change_message or "[]")
            except json.JSONDecodeError:
                message = item.change_message
            content_type = item.content_type
            model_class = content_type.model_class() if content_type is not None else None
            opts = model_class._meta if model_class is not None else None
            object_links = self._object_links(
                request,
                item,
                model_class,
                opts,
                obj=visible_objects.get(item.pk, _UNSET),
            )
            results.append(
                {
                    "id": jsonish_value(item.pk),
                    "action_time": item.action_time,
                    "user_id": jsonish_value(item.user_id),
                    "content_type_id": jsonish_value(item.content_type_id),
                    "model": f"{opts.app_label}.{opts.model_name}" if opts is not None else None,
                    "app_label": opts.app_label if opts is not None else None,
                    "model_name": opts.model_name if opts is not None else None,
                    "model_verbose_name": str(opts.verbose_name) if opts is not None else None,
                    "model_verbose_name_plural": str(opts.verbose_name_plural) if opts is not None else None,
                    "object_id": item.object_id,
                    "object_repr": item.object_repr,
                    **object_links,
                    "action_flag": item.action_flag,
                    "change_message": jsonish_value(message),
                    "change_message_text": item.get_change_message(),
                }
            )
        pagination = (
            visibility_filtered_pagination_result(page_obj, page_items)
            if use_visibility_filter
            else pagination_result(paginator, page_obj)
        )
        return OperationResult(HistoryResponse.model_validate({"pagination": pagination, "results": results}))

    def _content_type_ids(self, request, *, app_label=None, model_name=None):
        if model_name and not app_label:
            raise AdminValidationError(
                [{"message": _("app_label is required when model is provided."), "param": "app_label"}]
            )
        if app_label and model_name:
            try:
                model = apps.get_model(app_label, model_name)
                model_admin = self.admin_site.get_model_admin(model)
            except (LookupError, NotRegistered) as exc:
                raise Http404 from exc
            self._require_permission(model_admin.has_view_or_change_permission(request))
            return [ContentType.objects.get_for_model(model, for_concrete_model=False).pk]

        registered_model_admins = list(self.admin_site.get_registered_model_admins())
        registered_models = [
            model
            for model, model_admin in registered_model_admins
            if (app_label is None or model._meta.app_label == app_label)
            and model_admin.has_view_or_change_permission(request)
        ]
        if app_label is not None and not any(
            model._meta.app_label == app_label for model, _ in registered_model_admins
        ):
            raise Http404
        return [
            content_type.pk
            for content_type in ContentType.objects.get_for_models(
                *registered_models,
                for_concrete_models=False,
            ).values()
        ]

    def _requires_object_visibility_filter(self, content_type_ids):
        for content_type in ContentType.objects.filter(pk__in=content_type_ids):
            model_class = content_type.model_class()
            if model_class is None:
                continue
            try:
                model_admin = self.admin_site.get_model_admin(model_class)
            except NotRegistered:
                continue
            if uses_object_visibility_permissions(model_admin):
                return True
        return False

    def _object_links(self, request, item, model_class, opts, obj=_UNSET):
        if model_class is None or opts is None or not item.object_id:
            return {"detail_url": None, "change_form_url": None}
        try:
            model_admin = self.admin_site.get_model_admin(model_class)
        except NotRegistered:
            return {"detail_url": None, "change_form_url": None}
        if not uses_object_visibility_permissions(model_admin):
            if not model_admin.has_view_or_change_permission(request):
                return {"detail_url": None, "change_form_url": None}
            return _object_link_urls(request, item, opts)
        if obj is _UNSET:
            try:
                obj = model_admin.get_object(request, item.object_id)
            except (LookupError, ValidationError, ValueError):
                return {"detail_url": None, "change_form_url": None}
        if obj is None:
            return {"detail_url": None, "change_form_url": None}
        if not model_admin.has_view_permission(request, obj) and not model_admin.has_change_permission(request, obj):
            return {"detail_url": None, "change_form_url": None}
        return _object_link_urls(request, item, opts)

    def _item_visibility(self, request, item):
        content_type = item.content_type
        model_class = content_type.model_class() if content_type is not None else None
        if model_class is None or not item.object_id:
            return True, None
        try:
            model_admin = self.admin_site.get_model_admin(model_class)
            obj = model_admin.get_object(request, item.object_id)
        except (LookupError, NotRegistered, ValidationError, ValueError):
            return True, None
        if obj is None:
            return True, None
        visible = model_admin.has_view_permission(request, obj) or model_admin.has_change_permission(request, obj)
        return visible, obj

    @staticmethod
    def _require_permission(allowed):
        if not allowed:
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])


def _object_link_urls(request, item, opts):
    admin_base_path = request.path.rstrip("/")
    if admin_base_path.endswith("/history"):
        admin_base_path = admin_base_path[: -len("/history")]
    object_url = f"{admin_base_path}/{opts.app_label}/{opts.model_name}/{quote(item.object_id)}"
    return {"detail_url": object_url, "change_form_url": f"{object_url}/form"}
