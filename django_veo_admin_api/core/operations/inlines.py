from django.core.exceptions import FieldDoesNotExist
from django.forms.models import _get_foreign_key
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError, AdminValidationError
from django_veo_admin_api.core.operations.form_data import copy_form_row
from django_veo_admin_api.core.operations.forms import inline_remote_accessor_name
from django_veo_admin_api.utils.forms import formset_errors, model_data_for_form


class InlineMutationProcessor:
    """Validate and save inline operations as one authoritative Django formset."""

    def process(self, request, model_admin, obj, inline_payload, *, change):
        if not inline_payload:
            return {}
        results = {}
        inline_by_id = {
            f"{inline.model._meta.app_label}.{inline.model._meta.model_name}": inline
            for inline in model_admin.get_inline_instances(request, obj, check_permissions=False)
        }
        for inline_id, operations in inline_payload.items():
            if inline_id not in inline_by_id:
                raise AdminValidationError(
                    {inline_id: [{"message": _("Unknown inline."), "param": "non_field_errors"}]}
                )
            inline = inline_by_id[inline_id]
            foreign_key = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
            related_name = inline_remote_accessor_name(foreign_key)
            related_manager = getattr(obj, related_name, None)
            results[inline_id] = self._process_formset(
                request,
                inline,
                obj,
                operations,
                related_manager,
                change=change,
            )
        return results

    def _process_formset(self, request, inline, obj, operations, related_manager, *, change):
        allowed_operations = {"add", "change", "delete"}
        unknown_operations = set(operations) - allowed_operations
        inline_id = f"{inline.model._meta.app_label}.{inline.model._meta.model_name}"
        if unknown_operations:
            raise AdminValidationError(
                {
                    inline_id: [
                        {
                            "message": _("Unknown inline operation: %(operations)s.")
                            % {"operations": ", ".join(sorted(unknown_operations))},
                            "param": "non_field_errors",
                        }
                    ]
                }
            )

        add_rows = list(operations.get("add", []))
        change_rows = list(operations.get("change", []))
        delete_values = [str(pk) for pk in operations.get("delete", [])]
        delete_pks = set(delete_values)
        if add_rows and not inline.has_add_permission(request, obj):
            self._raise_permission()
        if change_rows and not inline.has_change_permission(request, obj):
            self._raise_permission()
        if delete_pks and not inline.has_delete_permission(request, obj):
            self._raise_permission()
        if delete_pks and not inline.can_delete:
            raise AdminValidationError(
                {inline_id: {"delete": [{"message": _("Inline deletion is not allowed."), "param": "delete"}]}}
            )

        formset_class = inline.get_formset(request, obj, change=change)
        form_fields = formset_class.form.base_fields
        editable_fields = set(form_fields)
        pk_name = inline.model._meta.pk.name
        inline_errors = {}
        duplicate_delete_pks = {pk for pk in delete_values if delete_values.count(pk) > 1}
        for index, pk in enumerate(delete_values):
            if pk in duplicate_delete_pks:
                self._add_row_error(
                    inline_errors,
                    "delete",
                    index,
                    message=_("Duplicate inline delete pk."),
                    param="pk",
                )
        self._collect_row_field_errors(inline_errors, add_rows, editable_fields, operation="add")
        self._collect_row_field_errors(
            inline_errors,
            change_rows,
            editable_fields | {"pk", "id", pk_name},
            operation="change",
        )

        queryset = related_manager.all() if related_manager is not None else inline.model.objects.none()
        existing_instances = list(queryset)
        existing_by_pk = {str(instance.pk): instance for instance in existing_instances}
        changes_by_pk = {}
        seen_change_pks = set()
        for index, row in enumerate(change_rows):
            pk = row.get("pk") or row.get(pk_name)
            has_row_error = False
            if pk is None:
                self._add_row_error(inline_errors, "change", index, message=_("Missing pk."), param="pk")
                continue
            pk = str(pk)
            if pk in seen_change_pks:
                self._add_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Duplicate inline change pk."),
                    param="pk",
                )
                has_row_error = True
            seen_change_pks.add(pk)
            if pk not in existing_by_pk:
                self._add_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Unknown inline object."),
                    param="pk",
                )
                has_row_error = True
            if pk in delete_pks and pk in existing_by_pk:
                self._add_row_error(
                    inline_errors,
                    "change",
                    index,
                    message=_("Inline object cannot be changed and deleted in the same request."),
                    param="pk",
                )
                has_row_error = True
            if not has_row_error:
                changes_by_pk[pk] = row
        for index, pk in enumerate(delete_values):
            if pk not in existing_by_pk:
                self._add_row_error(
                    inline_errors,
                    "delete",
                    index,
                    message=_("Unknown inline object."),
                    param="pk",
                )
        if inline_errors:
            raise AdminValidationError({inline_id: inline_errors})

        formset_data = self._formset_data(
            request,
            inline,
            obj,
            formset_class,
            existing_instances,
            changes_by_pk,
            add_rows,
            delete_pks,
        )
        formset = formset_class(data=formset_data, instance=obj, queryset=queryset)
        if not formset.is_valid():
            raise AdminValidationError({inline_id: {"formset": formset_errors(formset)}})
        deleted_objects = [
            {"id": existing_by_pk[pk].pk, "_object_repr": str(existing_by_pk[pk])} for pk in delete_values
        ]
        formset.save()
        changed_objects = []
        for instance, fields in formset.changed_objects:
            item = inline.serialize_object(instance, request)
            item["_changed_fields"] = [self._field_label(inline, field_name) for field_name in fields]
            changed_objects.append(item)
        return {
            "add": [inline.serialize_object(instance, request) for instance in formset.new_objects],
            "change": changed_objects,
            "delete": [item["id"] for item in deleted_objects],
            "_delete_objects": deleted_objects,
        }

    def _formset_data(
        self,
        request,
        inline,
        obj,
        formset_class,
        existing_instances,
        changes_by_pk,
        add_rows,
        delete_pks,
    ):
        prefix = formset_class.get_default_prefix()
        min_num = inline.get_min_num(request, obj) or 0
        max_num = inline.get_max_num(request, obj)
        total_forms = len(existing_instances) + len(add_rows)
        formset_data = {
            f"{prefix}-TOTAL_FORMS": str(total_forms),
            f"{prefix}-INITIAL_FORMS": str(len(existing_instances)),
            f"{prefix}-MIN_NUM_FORMS": str(min_num),
            f"{prefix}-MAX_NUM_FORMS": "" if max_num is None else str(max_num),
        }
        form_fields = formset_class.form.base_fields
        editable_fields = set(form_fields)
        pk_name = inline.model._meta.pk.name
        foreign_key = _get_foreign_key(inline.parent_model, inline.model, fk_name=inline.fk_name)
        for index, instance in enumerate(existing_instances):
            pk = str(instance.pk)
            row = model_data_for_form(instance, list(editable_fields))
            row.update(changes_by_pk.get(pk, {}))
            copy_form_row(formset_data, prefix, index, row, form_fields)
            formset_data[f"{prefix}-{index}-{pk_name}"] = pk
            formset_data[f"{prefix}-{index}-{foreign_key.name}"] = str(obj.pk)
            if pk in delete_pks:
                formset_data[f"{prefix}-{index}-DELETE"] = "on"
        for offset, row in enumerate(add_rows, start=len(existing_instances)):
            copy_form_row(formset_data, prefix, offset, row, form_fields)
            formset_data[f"{prefix}-{offset}-{foreign_key.name}"] = str(obj.pk)
        return formset_data

    def _collect_row_field_errors(self, inline_errors, rows, allowed_fields, *, operation):
        for index, row in enumerate(rows):
            unknown_fields = sorted(set(row) - allowed_fields)
            for field in unknown_fields:
                self._add_row_error(
                    inline_errors,
                    operation,
                    index,
                    message=_("Unknown or readonly inline field."),
                    param=field,
                )

    @staticmethod
    def _add_row_error(inline_errors, operation, index, *, message, param):
        row_errors = inline_errors.setdefault(operation, {}).setdefault(index, [])
        row_errors.append({"message": message, "param": param})

    @staticmethod
    def _field_label(inline, field_name):
        try:
            return str(inline.model._meta.get_field(field_name).verbose_name)
        except FieldDoesNotExist:
            return field_name.replace("_", " ")

    @staticmethod
    def _raise_permission():
        raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])
