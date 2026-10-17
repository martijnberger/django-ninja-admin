from typing import Any

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import InvalidPage
from django.db import models
from django.http import Http404
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, MissingSearchFields, NotRegistered
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.pagination import pagination_result, visibility_filtered_pagination_result
from django_veo_admin_api.core.operations.permissions import model_admin_method_overridden
from django_veo_admin_api.schemas import AutocompleteResponse


class AutocompleteOperations:
    """Resolve and search registered relation fields for autocomplete clients."""

    def __init__(self, admin_site: Any):
        self.admin_site = admin_site

    def search(
        self,
        context: AdminRequestContext,
        *,
        app_label: str,
        model_name: str,
        field_name: str,
        term: str = "",
        page: int = 1,
        per_page: int = 20,
    ) -> OperationResult[AutocompleteResponse]:
        request = context.request
        try:
            source_model = apps.get_model(app_label, model_name)
            source_admin = self.admin_site.get_model_admin(source_model)
            source_field = source_model._meta.get_field(field_name)
            if not isinstance(source_field, (models.ForeignKey, models.ManyToManyField)):
                raise Http404
            remote_field = source_field.remote_field
            if remote_field is None:
                raise Http404
            remote_model = remote_field.model
            model_admin = self.admin_site.get_model_admin(remote_model)
        except (FieldDoesNotExist, LookupError, NotRegistered) as exc:
            raise Http404 from exc

        if field_name not in source_admin.get_autocomplete_fields(request):
            raise Http404
        self._require_permission(source_admin.has_view_or_change_permission(request))
        if not model_admin.get_search_fields(request):
            raise MissingSearchFields

        if hasattr(remote_field, "get_related_field"):
            to_field_name = remote_field.get_related_field().attname
        else:
            to_field_name = remote_model._meta.pk.attname
        to_field_name = remote_model._meta.get_field(to_field_name).attname
        self._require_permission(model_admin.to_field_allowed(request, to_field_name))
        self._require_permission(model_admin.has_view_permission(request))

        queryset = model_admin.get_queryset(request).complex_filter(source_field.get_limit_choices_to())
        queryset, use_distinct = model_admin.get_search_results(request, queryset, term)
        if use_distinct:
            queryset = queryset.distinct()
        if not queryset.ordered:
            queryset = queryset.order_by(remote_model._meta.pk.name)

        use_visibility_filter = model_admin_method_overridden(model_admin, "has_view_permission")
        paginator = model_admin.get_paginator(request, queryset, per_page)
        try:
            page_obj = paginator.page(page)
        except InvalidPage as exc:
            raise Http404 from exc
        page_items = list(page_obj.object_list)
        if use_visibility_filter:
            page_items = [obj for obj in page_items if model_admin.has_view_permission(request, obj)]
        pagination = (
            visibility_filtered_pagination_result(page_obj, page_items)
            if use_visibility_filter
            else pagination_result(paginator, page_obj)
        )
        data = AutocompleteResponse.model_validate(
            {
                "results": [{"id": str(getattr(obj, to_field_name)), "text": str(obj)} for obj in page_items],
                "pagination": pagination,
            }
        )
        return OperationResult(data)

    @staticmethod
    def _require_permission(allowed):
        if not allowed:
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
