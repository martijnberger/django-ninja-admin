from typing import Any

from django.core.exceptions import ValidationError
from django.db import router, transaction
from django.utils.translation import gettext as _
from pydantic import TypeAdapter

from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.core.operations.form_data import copy_form_row, normalize_form_data
from django_veo_admin_api.utils.format_error import format_error
from django_veo_admin_api.utils.forms import model_data_for_form


class BulkMutationOperations:
    """Validate and apply permission-aware list-editable formset mutations."""

    def update(self, context: AdminRequestContext, model_admin: Any, payload: Any) -> OperationResult[Any]:
        request = context.request
        if not model_admin.has_change_permission(request):
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
        changelist = model_admin.get_changelist_instance(request)
        return self._update(
            request,
            model_admin,
            payload,
            queryset=changelist.queryset,
            object_id_field=changelist.object_id_field,
        )

    def _update(self, request, model_admin, payload, *, queryset, object_id_field):
        payload_rows = [
            item.model_dump(mode="python", exclude_unset=True) if hasattr(item, "model_dump") else item
            for item in payload.data
        ]
        if not payload_rows:
            raise AdminValidationError([{"message": _("Change data cannot be empty."), "param": "data"}])
        formset_class = model_admin.get_changelist_formset(request)
        form_class = formset_class.form
        form_fields = form_class.base_fields
        editable_fields = set(form_fields)
        validatable_rows = []
        validated_rows = []
        row_errors = {}
        has_permission_errors = False
        seen_pks = set()
        allowed = set(model_admin.list_editable) | {"pk", model_admin.model._meta.pk.name}
        for index, data in enumerate(payload_rows):
            pk = data.get("pk") or data.get(model_admin.model._meta.pk.name)
            if pk is None:
                row_errors[index] = [{"message": _("This field is required."), "param": "pk"}]
                continue
            pk_key = str(pk)
            if pk_key in seen_pks:
                row_errors[index] = [{"message": _("Duplicate object in bulk update."), "param": "pk"}]
                continue
            seen_pks.add(pk_key)
            unknown_fields = sorted(set(data) - allowed)
            if unknown_fields:
                row_errors[index] = [
                    {
                        "message": _("Field is not list editable: %(fields)s.") % {"fields": ", ".join(unknown_fields)},
                        "param": unknown_fields[0],
                    }
                ]
                continue
            obj = _object_from_queryset(queryset, pk, object_id_field=object_id_field)
            if obj is None:
                row_errors[index] = [{"message": _("Object not found."), "param": "pk"}]
                continue
            if not model_admin.has_change_permission(request, obj):
                row_errors[index] = [{"message": _("Permission denied."), "param": "pk"}]
                has_permission_errors = True
                continue
            current = model_data_for_form(obj, list(editable_fields))
            current.update({key: value for key, value in data.items() if key in allowed})
            current = normalize_form_data(form_class, current)
            validatable_rows.append((index, obj, current))
        if validatable_rows:
            formset_data = _formset_data(formset_class, validatable_rows, form_fields)
            formset_queryset = queryset.filter(pk__in=[obj.pk for _index, obj, _row in validatable_rows])
            formset = formset_class(data=formset_data, queryset=formset_queryset)
            if formset.is_valid():
                validated_rows = [
                    (index, form.instance, form)
                    for (index, _obj, _row), form in zip(validatable_rows, formset.forms, strict=True)
                ]
            else:
                for (index, _obj, _row), errors in zip(validatable_rows, formset.errors, strict=True):
                    formatted_errors = format_error(errors)
                    if formatted_errors:
                        row_errors[index] = formatted_errors
                non_form_errors = format_error(formset.non_form_errors())
                if non_form_errors:
                    row_errors["data"] = non_form_errors
        if row_errors:
            row_errors = _ordered_errors(row_errors)
            if has_permission_errors:
                raise AdminPermissionError(row_errors)
            raise AdminValidationError(row_errors)

        results = {}
        with transaction.atomic(using=router.db_for_write(model_admin.model)):
            for index, obj, form in validated_rows:
                if form.has_changed():
                    updated = model_admin.save_form(request, form, change=True)
                    model_admin.save_model(request, updated, form, change=True)
                    model_admin.save_related(request, form, {}, change=True)
                    change_message = model_admin.construct_change_message(request, form)
                    if change_message:
                        model_admin.log_change(request, updated, change_message)
                    obj = updated
                results[str(index)] = model_admin.serialize_object(obj, request)
        response = TypeAdapter(model_admin.get_bulk_response_schema(request)).validate_python({"data": results})
        return OperationResult(response)


def _formset_data(formset_class, rows, form_fields):
    prefix = formset_class.get_default_prefix()
    total_forms = len(rows)
    formset_data = {
        f"{prefix}-TOTAL_FORMS": str(total_forms),
        f"{prefix}-INITIAL_FORMS": str(total_forms),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "",
    }
    for form_index, (_payload_index, obj, row) in enumerate(rows):
        copy_form_row(formset_data, prefix, form_index, row, form_fields)
        formset_data[f"{prefix}-{form_index}-{obj._meta.pk.name}"] = str(obj.pk)
    return formset_data


def _ordered_errors(row_errors):
    return {key: row_errors[key] for key in sorted(row_errors, key=_error_sort_key)}


def _error_sort_key(key):
    if isinstance(key, int):
        return (0, key)
    if isinstance(key, str) and key.isdigit():
        return (0, int(key))
    return (1, str(key))


def _object_from_queryset(queryset, pk, *, object_id_field=None):
    field = queryset.model._meta.pk if object_id_field is None else queryset.model._meta.get_field(object_id_field)
    try:
        object_id = field.to_python(pk)
        return queryset.get(**{field.name: object_id})
    except (queryset.model.DoesNotExist, ValidationError, ValueError):
        return None
