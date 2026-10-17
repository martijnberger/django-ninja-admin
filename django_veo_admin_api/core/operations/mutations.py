from typing import Any

from django.db import router, transaction
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.form_data import normalize_form_data, payload_data, payload_inlines
from django_veo_admin_api.core.operations.inlines import InlineMutationProcessor
from django_veo_admin_api.core.operations.objects import ObjectOperations
from django_veo_admin_api.core.operations.responses import StatusResponseResolver, validate_mutation_response
from django_veo_admin_api.utils.forms import form_errors, model_data_for_form


class MutationOperations:
    """Transactional, form-authoritative create and update operations."""

    def __init__(self, *, status_resolver: StatusResponseResolver | None = None):
        self.status_resolver = status_resolver
        self.inline_processor = InlineMutationProcessor()
        self.object_operations = ObjectOperations()

    def create(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        payload: Any,
        *,
        files=None,
    ) -> OperationResult[Any]:
        request = context.request
        self._require_permission(model_admin.has_add_permission(request))
        with transaction.atomic(using=router.db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, None, change=False)
            form_data = normalize_form_data(form_class, payload_data(payload))
            form = form_class(data=form_data, files=files or None)
            if not form.is_valid():
                raise AdminValidationError({"form": form_errors(form)})
            obj = model_admin.save_form(request, form, change=False)
            model_admin.save_model(request, obj, form, change=False)
            inline_results = self.inline_processor.process(
                request,
                model_admin,
                obj,
                payload_inlines(payload) or {},
                change=False,
            )
            model_admin.save_related(request, form, inline_results, change=False)
            change_message = model_admin.construct_change_message(request, form, inline_results, add=True)
            model_admin.log_addition(request, obj, change_message)
            response = model_admin.response_add(request, obj, form, inline_results)
            return validate_mutation_response(
                response,
                default_status=201,
                default_schema=model_admin.get_mutation_response_schema(request),
                hook_schema=model_admin.get_response_add_schema(request),
                hook_name="response_add",
                status_resolver=self.status_resolver,
            )

    def update(
        self,
        context: AdminRequestContext,
        model_admin: Any,
        object_id: str,
        payload: Any,
        *,
        partial: bool,
        files=None,
        obj=None,
        to_field: str | None = None,
    ) -> OperationResult[Any]:
        request = context.request
        obj = obj or self.object_operations.get_object(context, model_admin, object_id, to_field).data
        self._require_permission(model_admin.has_change_permission(request, obj))
        with transaction.atomic(using=router.db_for_write(model_admin.model)):
            form_class = model_admin.get_form_class(request, obj, change=True)
            form_data = payload_data(payload, exclude_unset=partial)
            if partial:
                current = model_data_for_form(obj, list(form_class.base_fields.keys()))
                current.update(form_data)
                form_data = current
            form_data = normalize_form_data(form_class, form_data)
            form = form_class(data=form_data, files=files or None, instance=obj)
            if not form.is_valid():
                raise AdminValidationError({"form": form_errors(form)})
            updated_object = model_admin.save_form(request, form, change=True)
            model_admin.save_model(request, updated_object, form, change=True)
            inline_results = self.inline_processor.process(
                request,
                model_admin,
                updated_object,
                payload_inlines(payload) or {},
                change=True,
            )
            model_admin.save_related(request, form, inline_results, change=True)
            change_message = model_admin.construct_change_message(request, form, inline_results)
            if change_message:
                model_admin.log_change(request, updated_object, change_message)
            response = model_admin.response_change(request, updated_object, form, inline_results)
            return validate_mutation_response(
                response,
                default_status=200,
                default_schema=model_admin.get_mutation_response_schema(request),
                hook_schema=model_admin.get_response_change_schema(request),
                hook_name="response_change",
                status_resolver=self.status_resolver,
            )

    @staticmethod
    def _require_permission(allowed):
        if not allowed:
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
