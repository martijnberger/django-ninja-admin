from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.utils.translation import gettext as _

from django_veo_admin_api.core.exceptions import AdminPermissionError
from django_veo_admin_api.core.operations.base import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import ChangelistResponse, Pagination
from django_veo_admin_api.utils.forms import form_field_descriptions
from django_veo_admin_api.utils.json_values import jsonish_value
from django_veo_admin_api.utils.lookup import (
    display_metadata_for_field,
    field_name_for_display,
    label_for_field,
    lookup_field,
)
from django_veo_admin_api.utils.quote import quote


class ChangelistOperations:
    """Permission-aware changelist construction and serialization."""

    def list(self, context: AdminRequestContext, model_admin: Any) -> OperationResult[ChangelistResponse]:
        request = context.request
        if not model_admin.has_view_or_change_permission(request):
            raise AdminPermissionError([{"message": _("Permission denied."), "param": "non_field_errors"}])

        changelist = model_admin.get_changelist_instance(request)
        list_display = changelist.list_display
        ordering_field_columns = {field: int(column) for field, column in changelist.ordering_field_columns.items()}
        columns = [
            {
                "field": field_name_for_display(field),
                "header_name": label_for_field(field, model_admin.model, model_admin),
                "display_link": _display_field_in(field, changelist.list_display_links or ()),
                **display_metadata_for_field(field, model_admin.model, model_admin),
                "sortable": field in changelist.ordering_field_columns,
                "ordering_field": changelist.get_ordering_field(field),
                "ordering_index": ordering_field_columns.get(field),
                **changelist.column_sort_query_strings(field),
            }
            for field in list_display
        ]
        columns_by_field = {column["field"]: column for column in columns}
        rows = []
        empty_value = model_admin.get_empty_value_display()
        result_start_index = changelist.page.start_index()
        for index, obj in enumerate(changelist.result_list):
            object_id = jsonish_value(changelist.object_id_for(obj))
            row_metadata = _row_metadata(request, model_admin, obj, object_id, changelist.to_field)
            cells = {}
            cell_metadata = {}
            for field in list_display:
                field_key = field_name_for_display(field)
                raw_value = lookup_field(field, obj, model_admin)
                value = jsonish_value(raw_value)
                display_metadata = display_metadata_for_field(field, model_admin.model, model_admin)
                field_empty_value = (
                    display_metadata["empty_value_display"]
                    if display_metadata["empty_value_display"] is not None
                    else empty_value
                )
                is_empty = raw_value in (None, "")
                display_value = field_empty_value if is_empty else value
                cells[field_key] = display_value
                column = columns_by_field[field_key]
                cell_metadata[field_key] = {
                    "field": field_key,
                    "header_name": column["header_name"],
                    "value": value,
                    "display_value": display_value,
                    "empty": is_empty,
                    "boolean": column["boolean"],
                    "display_link": column["display_link"],
                    "link_url": row_metadata["detail_url"] if column["display_link"] else None,
                    "sortable": column["sortable"],
                    "ordering_field": column["ordering_field"],
                    "editable": field_key in model_admin.list_editable,
                    "empty_value_display": field_empty_value,
                }
            rows.append(
                {
                    "id": object_id,
                    "index": index,
                    "result_index": result_start_index + index,
                    "cells": cells,
                    "cell_metadata": cell_metadata,
                    **row_metadata,
                }
            )

        action_choices = model_admin.get_action_choices(request)
        action_form = []
        if action_choices:
            action_form = [
                {
                    "name": "action",
                    "type": "ChoiceField",
                    "attrs": {
                        "required": True,
                        "choices": [(item["action"], str(item["description"])) for item in action_choices],
                    },
                },
                {"name": "selected_ids", "type": "MultipleChoiceField", "attrs": {"required": False}},
                {"name": "select_across", "type": "BooleanField", "attrs": {"required": False}},
            ]

        list_editing_formset = []
        list_editing_rows = []
        list_editing_formset_prefix = None
        list_editing_management_form = []
        list_editing_total_form_count = None
        list_editing_initial_form_count = None
        if model_admin.list_editable:
            formset_class = model_admin.get_changelist_formset(request)
            form_class = formset_class.form
            page_pks = [obj.pk for obj in changelist.result_list]
            formset_queryset = model_admin.model._default_manager.filter(pk__in=page_pks)
            formset = formset_class(queryset=formset_queryset)
            list_editing_formset_prefix = formset.prefix
            list_editing_management_form = form_field_descriptions(
                formset.management_form.__class__,
                request=request,
                form=formset.management_form,
            )
            list_editing_total_form_count = formset.total_form_count()
            list_editing_initial_form_count = formset.initial_form_count()
            for index, obj in enumerate(changelist.result_list):
                object_id = jsonish_value(changelist.object_id_for(obj))
                form = form_class(instance=obj, prefix=f"{formset.prefix}-{index}")
                field_descriptions = model_admin.get_changelist_form_fields_description(request, obj, form=form)
                editable_fields = [field for field in field_descriptions if field["name"] in model_admin.list_editable]
                list_editing_formset.append(editable_fields)
                list_editing_rows.append(
                    {
                        "index": index,
                        "pk": object_id,
                        "pk_name": changelist.object_id_field,
                        "form_prefix": form.prefix,
                        "empty_permitted": form.empty_permitted,
                        "fields": editable_fields,
                    }
                )

        model_field_names = [field for field in list_display if _model_has_field(model_admin.model, field)]
        display_ordering_field_columns = {
            field_name_for_display(field): column for field, column in ordering_field_columns.items()
        }
        payload = {
            "columns": columns,
            "rows": rows,
            "config": {
                "full_count": changelist.full_result_count,
                "result_count": changelist.result_count,
                "page_result_count": len(changelist.result_list),
                "result_start_index": changelist.page.start_index(),
                "result_end_index": changelist.page.end_index(),
                "page_count": changelist.paginator.num_pages,
                "page": changelist.page_num,
                "per_page": changelist.per_page,
                "pagination": _pagination_payload(changelist.paginator, changelist.page),
                "has_next": changelist.page.has_next(),
                "has_previous": changelist.page.has_previous(),
                "multi_page": changelist.multi_page,
                "pagination_required": changelist.pagination_required,
                "page_range": changelist.get_page_range(),
                "page_choices": changelist.get_page_choices(),
                **changelist.pagination_query_strings(),
                **changelist.show_all_query_strings(),
                "show_all": changelist.show_all,
                "can_show_all": changelist.can_show_all_results,
                "show_facets": changelist.show_facets,
                **changelist.facet_query_strings(),
                "has_filters": changelist.has_filters,
                "has_active_filters": changelist.has_active_filters(),
                "clear_all_filters_query_string": changelist.clear_all_filters_query_string(),
                "actions_on_top": bool(model_admin.actions_on_top),
                "actions_on_bottom": bool(model_admin.actions_on_bottom),
                "actions_selection_counter": bool(model_admin.actions_selection_counter),
                "show_full_result_count": changelist.show_full_result_count,
                "show_admin_actions": changelist.show_admin_actions and bool(action_choices),
                "action_choices": action_choices,
                "filters": changelist.filter_descriptions(),
                "date_hierarchy": changelist.date_hierarchy_description(),
                "list_display_fields": model_field_names,
                "list_display_links": [
                    field_name_for_display(field) for field in (changelist.list_display_links or ())
                ],
                "to_field": changelist.to_field,
                "object_id_field": changelist.object_id_field,
                "ordering_field_columns": display_ordering_field_columns,
                "ordering": changelist.ordering,
                **changelist.search_query_strings(),
                "search_fields": list(changelist.search_fields),
                "search_help_text": model_admin.search_help_text,
            },
            "action_form": action_form,
            "list_editing_formset_prefix": list_editing_formset_prefix,
            "list_editing_management_form": list_editing_management_form,
            "list_editing_total_form_count": list_editing_total_form_count,
            "list_editing_initial_form_count": list_editing_initial_form_count,
            "list_editing_formset": list_editing_formset,
            "list_editing_rows": list_editing_rows,
        }
        return OperationResult(ChangelistResponse.model_validate(payload))


def _pagination_payload(paginator, page_obj):
    has_next = page_obj.has_next()
    return Pagination(
        count=paginator.count,
        num_pages=paginator.num_pages,
        page=page_obj.number,
        per_page=paginator.per_page,
        has_next=has_next,
        has_previous=page_obj.has_previous(),
        more=has_next,
    ).model_dump(mode="json")


def _row_metadata(request, model_admin, obj, object_id, to_field=None):
    quoted_object_id = quote(object_id)
    detail_url = f"{request.path.rstrip('/')}/{quoted_object_id}"
    to_field_query_string = f"?_to_field={quote(to_field)}" if to_field else ""
    has_view_permission = model_admin.has_view_permission(request, obj)
    has_change_permission = model_admin.has_change_permission(request, obj)
    has_delete_permission = model_admin.has_delete_permission(request, obj)
    can_open_object = has_view_permission or has_change_permission
    return {
        "detail_url": f"{detail_url}{to_field_query_string}" if can_open_object else None,
        "change_form_url": f"{detail_url}/form{to_field_query_string}" if can_open_object else None,
        "delete_url": f"{detail_url}{to_field_query_string}" if has_delete_permission else None,
        "view_on_site_url": model_admin.get_view_on_site_url(obj) if can_open_object else None,
        "permissions": {
            "has_add_permission": model_admin.has_add_permission(request),
            "has_change_permission": has_change_permission,
            "has_delete_permission": has_delete_permission,
            "has_view_permission": has_view_permission,
        },
    }


def _display_field_in(field, candidates):
    field_key = field_name_for_display(field)
    return any(field == candidate or field_key == field_name_for_display(candidate) for candidate in candidates)


def _model_has_field(model, field):
    try:
        model._meta.get_field(field)
        return True
    except FieldDoesNotExist:
        return False
