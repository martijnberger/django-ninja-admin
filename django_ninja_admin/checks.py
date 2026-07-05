from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from contextlib import suppress
from typing import cast

from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import Paginator
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.expressions import Combinable
from django.forms.models import BaseInlineFormSet, BaseModelForm, _get_foreign_key
from pydantic import TypeAdapter
from pydantic.errors import PydanticSchemaGenerationError, PydanticUserError

from django_ninja_admin.exceptions import NotRegistered
from django_ninja_admin.filters import FieldListFilter, ListFilter, SimpleListFilter
from django_ninja_admin.utils.flatten import flatten
from django_ninja_admin.utils.lookup import (
    field_name_for_display,
    model_field_from_path,
    single_valued_model_field_from_path,
)

ERROR_PREFIX = "django_ninja_admin"

DJANGO_SEQUENCE_OPTION_CODES = {
    "fields": "E004",
    "exclude": "E014",
    "raw_id_fields": "E001",
    "filter_vertical": "E017",
    "filter_horizontal": "E018",
    "ordering": "E031",
    "readonly_fields": "E034",
    "autocomplete_fields": "E036",
    "list_display": "E107",
    "list_display_links": "E110",
    "list_filter": "E112",
    "list_select_related": "E117",
    "list_editable": "E120",
    "search_fields": "E126",
}

PACKAGE_OPTION_CODES = {
    "list_prefetch_related_type": "E131",
    "list_prefetch_related_path": "E132",
    "form_schema_field_overrides_type": "E133",
    "form_schema_field_overrides_key": "E134",
    "form_schema_field_overrides_value": "E135",
    "search_fields_item": "E136",
    "search_fields_lookup": "E137",
    "ordering_item": "E138",
    "date_hierarchy_type": "E139",
    "action_missing": "E140",
    "autocomplete_raw_id_conflict": "E141",
    "autocomplete_radio_conflict": "E142",
    "raw_id_radio_conflict": "E143",
    "filter_horizontal_vertical_conflict": "E144",
    "inline_can_delete_type": "E145",
    "inline_show_change_link_type": "E146",
    "inline_extra_negative": "E147",
    "inline_min_num_negative": "E148",
    "inline_max_num_negative": "E149",
    "inline_min_exceeds_max": "E150",
    "inline_layout_sequence_type": "E151",
    "inline_layout_item_type": "E152",
    "inline_layout_unknown": "E153",
    "inline_layout_duplicate": "E154",
    "inline_readonly_unknown": "E155",
    "inline_fieldset_shape": "E156",
    "list_per_page_range": "E157",
    "list_max_show_all_range": "E158",
    "form_layout_item_type": "E159",
    "form_layout_unknown": "E160",
    "readonly_duplicate": "E161",
    "form_layout_non_editable": "E162",
    "list_editable_missing_from_form": "E163",
    "list_display_item_type": "E164",
    "list_display_links_item_type": "E165",
    "list_display_links_duplicate": "E166",
    "list_editable_item_type": "E167",
    "list_editable_duplicate": "E168",
    "list_filter_tuple_shape": "E169",
    "simple_list_filter_parameter": "E170",
    "sortable_by_type": "E171",
    "sortable_by_item": "E172",
    "sortable_by_missing": "E173",
    "schema_field_overrides_type": "E174",
    "schema_field_overrides_key": "E175",
    "schema_field_overrides_value": "E176",
    "form_class_model_mismatch": "E177",
    "formfield_overrides_type": "E178",
    "formfield_overrides_key": "E179",
    "formfield_overrides_value": "E180",
    "formfield_overrides_nested_key": "E181",
    "paginator_type": "E182",
    "save_as_continue_type": "E183",
    "actions_on_top_type": "E184",
    "actions_on_bottom_type": "E185",
    "actions_selection_counter_type": "E186",
    "show_full_result_count_type": "E187",
    "show_facets_type": "E188",
    "search_help_text_type": "E189",
    "empty_value_display_type": "E190",
    "list_display_empty": "E191",
    "list_select_related_item": "E192",
    "list_select_related_path": "E193",
    "actions_type": "E195",
    "open_contract_schema": "E196",
}

DJANGO_RELATION_OPTION_CODES = {
    "autocomplete_fields": {
        "missing": "E037",
        "invalid_relation": "E038",
        "unregistered": "E039",
        "unsearchable": "E040",
    },
    "raw_id_fields": {
        "missing": "E002",
        "invalid_relation": "E003",
    },
    "filter_horizontal": {
        "missing": "E019",
        "not_many_to_many": "E020",
        "manual_through": "E013",
    },
    "filter_vertical": {
        "missing": "E019",
        "not_many_to_many": "E020",
        "manual_through": "E013",
    },
}

DJANGO_DISPLAY_OPTION_CODES = {
    "list_display_missing": "E108",
    "list_display_many_to_many": "E109",
    "list_display_links_missing": "E111",
    "list_editable_missing": "E121",
    "list_editable_not_in_list_display": "E122",
    "list_editable_in_list_display_links": "E123",
    "list_editable_first_without_display_link": "E124",
    "list_editable_not_editable": "E125",
}

DJANGO_LIST_FILTER_OPTION_CODES = {
    "invalid_filter_class": "E113",
    "field_filter_as_top_level": "E114",
    "invalid_field_filter_class": "E115",
    "invalid_field": "E116",
}


def _error(obj, message, code, *, hint=None):
    return checks.Error(message, hint=hint, obj=obj, id=f"{ERROR_PREFIX}.{code}")


def check_model_admin(model_admin):
    errors = []
    errors.extend(_check_sequence_option(model_admin, "list_display", allow_none=False))
    errors.extend(_check_sequence_option(model_admin, "list_display_links"))
    errors.extend(_check_sequence_option(model_admin, "list_editable"))
    errors.extend(_check_sequence_option(model_admin, "list_filter"))
    errors.extend(_check_sequence_option(model_admin, "search_fields"))
    errors.extend(_check_sequence_option(model_admin, "ordering"))
    errors.extend(_check_sequence_option(model_admin, "readonly_fields"))
    errors.extend(_check_sequence_option(model_admin, "autocomplete_fields"))
    errors.extend(_check_sequence_option(model_admin, "raw_id_fields"))
    errors.extend(_check_sequence_option(model_admin, "filter_horizontal"))
    errors.extend(_check_sequence_option(model_admin, "filter_vertical"))
    errors.extend(_check_list_select_related(model_admin))
    errors.extend(_check_list_prefetch_related(model_admin))
    errors.extend(_check_pagination_options(model_admin))
    errors.extend(_check_paginator(model_admin))
    errors.extend(_check_boolean_options(model_admin))
    errors.extend(_check_show_facets(model_admin))
    errors.extend(_check_text_options(model_admin))
    errors.extend(_check_display_options(model_admin))
    errors.extend(_check_sortable_by(model_admin))
    errors.extend(_check_form_class(model_admin))
    errors.extend(_check_formfield_overrides(model_admin))
    errors.extend(_check_form_schema_field_overrides(model_admin))
    errors.extend(_check_schema_field_overrides(model_admin))
    errors.extend(_check_response_hook_schemas(model_admin))
    errors.extend(_check_form_layout(model_admin))
    errors.extend(_check_prepopulated_fields(model_admin))
    errors.extend(_check_list_filters(model_admin))
    errors.extend(_check_radio_fields(model_admin))
    errors.extend(_check_form_option_conflicts(model_admin))
    errors.extend(
        _check_lookup_fields(
            model_admin,
            "search_fields",
            item_code=PACKAGE_OPTION_CODES["search_fields_item"],
            lookup_code=PACKAGE_OPTION_CODES["search_fields_lookup"],
            allow_search_prefixes=True,
        )
    )
    errors.extend(
        _check_lookup_fields(
            model_admin,
            "ordering",
            item_code=PACKAGE_OPTION_CODES["ordering_item"],
            lookup_code="E033",
            allow_descending=True,
            allow_random=True,
        )
    )
    forward_relation_types = (models.ForeignKey, models.ManyToManyField)
    errors.extend(
        _check_relation_fields(
            model_admin,
            "autocomplete_fields",
            relation_types=forward_relation_types,
            require_registered_remote=True,
        )
    )
    errors.extend(
        _check_relation_fields(
            model_admin,
            "raw_id_fields",
            relation_types=forward_relation_types,
            require_field_name=True,
        )
    )
    errors.extend(_check_relation_fields(model_admin, "filter_horizontal", many_to_many_only=True))
    errors.extend(_check_relation_fields(model_admin, "filter_vertical", many_to_many_only=True))
    errors.extend(_check_date_hierarchy(model_admin))
    errors.extend(_check_actions(model_admin))
    errors.extend(_check_inlines(model_admin))
    return errors


def _check_sequence_option(model_admin, option, *, allow_none=True):
    value = getattr(model_admin, option, None)
    if value is None and allow_none:
        return []
    if not isinstance(value, (list, tuple)):
        code = DJANGO_SEQUENCE_OPTION_CODES.get(option, "E001")
        return [_error(model_admin.__class__, f"The value of '{option}' must be a list or tuple.", code)]
    return []


def _field_or_attr_exists(model_admin, name):
    if name == "__str__":
        return True
    if hasattr(model_admin, name):
        return True
    try:
        model_admin.model._meta.get_field(name)
        return True
    except FieldDoesNotExist:
        return hasattr(model_admin.model, name)


def _model_field(model_admin, name):
    try:
        return model_admin.model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _check_display_options(model_admin):
    errors = []
    list_display = tuple(model_admin.get_list_display(None))
    if not list_display:
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'list_display' must not be empty.",
                PACKAGE_OPTION_CODES["list_display_empty"],
            )
        )
    editable_form_fields = _editable_form_field_names(model_admin)
    excluded_form_fields = set(model_admin.get_exclude(None) or ())
    for item in list_display:
        if callable(item):
            continue
        if not isinstance(item, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'list_display' must be strings or callables.",
                    PACKAGE_OPTION_CODES["list_display_item_type"],
                )
            )
            continue
        if item == "__str__":
            continue
        field = None
        if "__" in item:
            with suppress(FieldDoesNotExist):
                field = single_valued_model_field_from_path(model_admin.model, item)
        elif _field_or_attr_exists(model_admin, item):
            field = _model_field(model_admin, item)

        if field is None and not _field_or_attr_exists(model_admin, item):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is not a field, method, or attribute.",
                    DJANGO_DISPLAY_OPTION_CODES["list_display_missing"],
                )
            )
            continue
        if field is not None and (getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is a many-to-many or reverse field.",
                    DJANGO_DISPLAY_OPTION_CODES["list_display_many_to_many"],
                )
            )

    configured_list_display_links = getattr(model_admin, "list_display_links", ())
    list_display_links = model_admin.get_list_display_links(None, list_display)
    if list_display_links is not None:
        seen_display_links = set()
        for item in list_display_links:
            if not isinstance(item, str) and not callable(item):
                errors.append(
                    _error(
                        model_admin.__class__,
                        "Items in 'list_display_links' must be strings or callables.",
                        PACKAGE_OPTION_CODES["list_display_links_item_type"],
                    )
                )
                continue
            item_key = field_name_for_display(item)
            if item_key in seen_display_links:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The field '{item_key}' is duplicated in 'list_display_links'.",
                        PACKAGE_OPTION_CODES["list_display_links_duplicate"],
                    )
                )
            seen_display_links.add(item_key)
            if not _display_item_in(item, list_display):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The value of 'list_display_links' refers to '{item}', which is not in 'list_display'.",
                        DJANGO_DISPLAY_OPTION_CODES["list_display_links_missing"],
                    )
                )

    editable = tuple(model_admin.list_editable or ())
    seen_editable = set()
    for item in editable:
        if not isinstance(item, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'list_editable' must be strings.",
                    PACKAGE_OPTION_CODES["list_editable_item_type"],
                )
            )
            continue
        item_key = field_name_for_display(item)
        if item_key in seen_editable:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item_key}' is duplicated in 'list_editable'.",
                    PACKAGE_OPTION_CODES["list_editable_duplicate"],
                )
            )
        seen_editable.add(item_key)
        field = _model_field(model_admin, item)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not a model field.",
                    DJANGO_DISPLAY_OPTION_CODES["list_editable_missing"],
                )
            )
            continue
        if item not in list_display:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not in 'list_display'.",
                    DJANGO_DISPLAY_OPTION_CODES["list_editable_not_in_list_display"],
                )
            )
            continue
        if configured_list_display_links and item in configured_list_display_links:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is also in 'list_display_links'.",
                    DJANGO_DISPLAY_OPTION_CODES["list_editable_in_list_display_links"],
                )
            )
        elif list_display and item == list_display[0] and configured_list_display_links == ():
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to the first field in 'list_display' ('{item}'), "
                    "which cannot be used unless 'list_display_links' is set.",
                    DJANGO_DISPLAY_OPTION_CODES["list_editable_first_without_display_link"],
                )
            )
        if field.primary_key or not field.editable:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' is not editable through the admin.",
                    DJANGO_DISPLAY_OPTION_CODES["list_editable_not_editable"],
                )
            )
        if item in excluded_form_fields or (editable_form_fields is not None and item not in editable_form_fields):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not included in the admin form.",
                    PACKAGE_OPTION_CODES["list_editable_missing_from_form"],
                )
            )
    return errors


def _check_sortable_by(model_admin):
    value = getattr(model_admin, "sortable_by", None)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return [
            _error(
                model_admin.__class__,
                "The value of 'sortable_by' must be a list or tuple.",
                PACKAGE_OPTION_CODES["sortable_by_type"],
            )
        ]

    errors = []
    list_display = tuple(model_admin.get_list_display(None))
    for item in value:
        if not isinstance(item, str) and not callable(item):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'sortable_by' must be strings or callables.",
                    PACKAGE_OPTION_CODES["sortable_by_item"],
                )
            )
            continue
        if not _display_item_in(item, list_display):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'sortable_by' refers to '{item}', which is not in 'list_display'.",
                    PACKAGE_OPTION_CODES["sortable_by_missing"],
                )
            )
    return errors


def _check_pagination_options(model_admin):
    errors = []
    list_per_page = getattr(model_admin, "list_per_page", None)
    list_max_show_all = getattr(model_admin, "list_max_show_all", None)
    if not _is_integer_option(list_per_page):
        errors.append(_error(model_admin.__class__, "The value of 'list_per_page' must be an integer.", "E118"))
    else:
        list_per_page_int = cast(int, list_per_page)
        if list_per_page_int < 1:
            errors.append(
                _error(
                    model_admin.__class__,
                    "The value of 'list_per_page' must be greater than zero.",
                    PACKAGE_OPTION_CODES["list_per_page_range"],
                )
            )
    if not _is_integer_option(list_max_show_all):
        errors.append(_error(model_admin.__class__, "The value of 'list_max_show_all' must be an integer.", "E119"))
    else:
        list_max_show_all_int = cast(int, list_max_show_all)
        if list_max_show_all_int < 0:
            errors.append(
                _error(
                    model_admin.__class__,
                    "The value of 'list_max_show_all' must not be negative.",
                    PACKAGE_OPTION_CODES["list_max_show_all_range"],
                )
            )
    return errors


def _is_integer_option(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_paginator(model_admin):
    paginator = getattr(model_admin, "paginator", None)
    if not isinstance(paginator, type) or not issubclass(paginator, Paginator):
        return [
            _error(
                model_admin.__class__,
                "The value of 'paginator' must inherit from Paginator.",
                PACKAGE_OPTION_CODES["paginator_type"],
            )
        ]
    return []


def _check_boolean_options(model_admin):
    errors = []
    if not isinstance(getattr(model_admin, "save_as", False), bool):
        errors.append(_error(model_admin.__class__, "The value of 'save_as' must be a boolean.", "E101"))
    if not isinstance(getattr(model_admin, "save_as_continue", True), bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'save_as_continue' must be a boolean.",
                PACKAGE_OPTION_CODES["save_as_continue_type"],
            )
        )
    if not isinstance(getattr(model_admin, "save_on_top", False), bool):
        errors.append(_error(model_admin.__class__, "The value of 'save_on_top' must be a boolean.", "E102"))
    if not isinstance(getattr(model_admin, "actions_on_top", True), bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'actions_on_top' must be a boolean.",
                PACKAGE_OPTION_CODES["actions_on_top_type"],
            )
        )
    if not isinstance(getattr(model_admin, "actions_on_bottom", False), bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'actions_on_bottom' must be a boolean.",
                PACKAGE_OPTION_CODES["actions_on_bottom_type"],
            )
        )
    if not isinstance(getattr(model_admin, "actions_selection_counter", True), bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'actions_selection_counter' must be a boolean.",
                PACKAGE_OPTION_CODES["actions_selection_counter_type"],
            )
        )
    if not isinstance(getattr(model_admin, "show_full_result_count", True), bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'show_full_result_count' must be a boolean.",
                PACKAGE_OPTION_CODES["show_full_result_count_type"],
            )
        )
    view_on_site = getattr(model_admin, "view_on_site", True)
    if not callable(view_on_site) and not isinstance(view_on_site, bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'view_on_site' must be a callable or a boolean.",
                "E025",
            )
        )
    return errors


def _check_show_facets(model_admin):
    from django_ninja_admin.constants import ShowFacets

    if not isinstance(getattr(model_admin, "show_facets", ShowFacets.ALLOW), ShowFacets):
        return [
            _error(
                model_admin.__class__,
                "The value of 'show_facets' must be a ShowFacets value.",
                PACKAGE_OPTION_CODES["show_facets_type"],
            )
        ]
    return []


def _check_text_options(model_admin):
    errors = []
    search_help_text = getattr(model_admin, "search_help_text", None)
    if search_help_text is not None and not isinstance(search_help_text, str):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'search_help_text' must be a string or None.",
                PACKAGE_OPTION_CODES["search_help_text_type"],
            )
        )
    empty_value_display = getattr(model_admin, "empty_value_display", None)
    if empty_value_display is not None and not isinstance(empty_value_display, str):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'empty_value_display' must be a string or None.",
                PACKAGE_OPTION_CODES["empty_value_display_type"],
            )
        )
    return errors


def _display_item_in(item, candidates):
    item_key = field_name_for_display(item)
    return any(item == candidate or item_key == field_name_for_display(candidate) for candidate in candidates)


def _check_form_class(model_admin):
    form_class = getattr(model_admin, "form_class", None)
    if form_class is None:
        return []
    if not isinstance(form_class, type) or not issubclass(form_class, BaseModelForm):
        return [_error(model_admin.__class__, "The value of 'form_class' must inherit from ModelForm.", "E016")]

    form_model = getattr(getattr(form_class, "_meta", None), "model", None)
    if form_model is not None and form_model is not model_admin.model:
        return [
            _error(
                model_admin.__class__,
                f"The value of 'form_class' declares model '{form_model._meta.label}', "
                f"but this admin is registered for '{model_admin.model._meta.label}'.",
                PACKAGE_OPTION_CODES["form_class_model_mismatch"],
            )
        ]
    return []


def _check_formfield_overrides(model_admin):
    value = getattr(model_admin, "formfield_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [
            _error(
                model_admin.__class__,
                "The value of 'formfield_overrides' must be a mapping.",
                PACKAGE_OPTION_CODES["formfield_overrides_type"],
            )
        ]

    errors = []
    for field_class, overrides in value.items():
        if not isinstance(field_class, type) or not issubclass(field_class, models.Field):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'formfield_overrides' must be Django model field classes.",
                    PACKAGE_OPTION_CODES["formfield_overrides_key"],
                )
            )
            continue
        if not isinstance(overrides, Mapping):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_class.__name__}' must be a mapping of formfield keyword arguments.",
                    PACKAGE_OPTION_CODES["formfield_overrides_value"],
                )
            )
            continue
        for key in overrides:
            if not isinstance(key, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Keys in the override for '{field_class.__name__}' must be strings.",
                        PACKAGE_OPTION_CODES["formfield_overrides_nested_key"],
                    )
                )
    return errors


def _check_schema_field_overrides(model_admin):
    value = getattr(model_admin, "schema_field_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [
            _error(
                model_admin.__class__,
                "The value of 'schema_field_overrides' must be a mapping.",
                PACKAGE_OPTION_CODES["schema_field_overrides_type"],
            )
        ]

    errors = []
    for field_name, override in value.items():
        if not isinstance(field_name, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'schema_field_overrides' must be field names.",
                    PACKAGE_OPTION_CODES["schema_field_overrides_key"],
                )
            )
        if isinstance(override, tuple) and len(override) not in {1, 2}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_name}' must be a type annotation or a one/two-item tuple.",
                    PACKAGE_OPTION_CODES["schema_field_overrides_value"],
                )
            )
    return errors


def _check_form_schema_field_overrides(model_admin):
    value = getattr(model_admin, "form_schema_field_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [
            _error(
                model_admin.__class__,
                "The value of 'form_schema_field_overrides' must be a mapping.",
                PACKAGE_OPTION_CODES["form_schema_field_overrides_type"],
            )
        ]

    errors = []
    for field_name, override in value.items():
        if not isinstance(field_name, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'form_schema_field_overrides' must be field names.",
                    PACKAGE_OPTION_CODES["form_schema_field_overrides_key"],
                )
            )
        if isinstance(override, tuple) and len(override) not in {1, 2}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_name}' must be a type annotation or a one/two-item tuple.",
                    PACKAGE_OPTION_CODES["form_schema_field_overrides_value"],
                )
            )
    return errors


def _check_response_hook_schemas(model_admin):
    errors = []
    for option in ("response_add_schema", "response_change_schema", "response_delete_schema"):
        errors.extend(_check_closed_contract_schema(model_admin, getattr(model_admin, option, None), f"'{option}'"))
    return errors


def _check_closed_contract_schema(obj, schema, label):
    errors = []
    for schema_label, schema_type in _iter_contract_schemas(schema, label):
        open_paths = _open_object_schema_paths(schema_type)
        if open_paths:
            errors.append(
                _error(
                    obj.__class__ if not isinstance(obj, type) else obj,
                    f"The schema for {schema_label} must forbid extra object properties.",
                    PACKAGE_OPTION_CODES["open_contract_schema"],
                    hint=(
                        "Set model_config = ConfigDict(extra='forbid') on the Pydantic/Ninja schema, "
                        "or use a schema whose object members define typed additionalProperties."
                    ),
                )
            )
    return errors


def _iter_contract_schemas(schema, label):
    if schema is None:
        return
    if isinstance(schema, Mapping):
        for status_code, status_schema in schema.items():
            yield f"{label}[{status_code}]", status_schema
        return
    yield label, schema


def _open_object_schema_paths(schema_type):
    try:
        json_schema = TypeAdapter(schema_type).json_schema()
    except (PydanticSchemaGenerationError, PydanticUserError, TypeError, ValueError):
        return []

    paths = []

    def walk(node, path):
        if isinstance(node, Mapping):
            if node.get("type") == "object":
                additional_properties = node.get("additionalProperties", None)
                if (
                    ("properties" in node and additional_properties is not False)
                    or ("properties" not in node and "additionalProperties" not in node)
                    or additional_properties is True
                    or additional_properties == {}
                ):
                    paths.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(json_schema, "")
    return paths


def _editable_form_field_names(model_admin):
    if model_admin.fields is not None:
        return set(flatten(model_admin.fields))
    if model_admin.fieldsets is not None:
        fields, errors = _fieldsets_fields_and_errors(model_admin)
        if errors:
            return None
        return set(fields)
    return None


def _check_form_layout(model_admin):
    errors = []
    if model_admin.fields is not None and model_admin.fieldsets is not None:
        errors.append(
            _error(
                model_admin.__class__,
                "Both 'fields' and 'fieldsets' are set; use only one form layout option.",
                "E005",
            )
        )
    errors.extend(_check_sequence_option(model_admin, "fields"))
    errors.extend(_check_sequence_option(model_admin, "exclude"))
    errors.extend(_check_form_option_items(model_admin, "fields"))
    errors.extend(_check_form_option_items(model_admin, "exclude", require_model_field=True))

    readonly_fields = tuple(model_admin.get_readonly_fields(None) or ())
    readonly_field_names = {field_name_for_display(field) for field in readonly_fields}
    seen_readonly_fields = set()
    for item in readonly_fields:
        item_key = field_name_for_display(item)
        if item_key in seen_readonly_fields:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item_key}' is duplicated in 'readonly_fields'.",
                    PACKAGE_OPTION_CODES["readonly_duplicate"],
                )
            )
        seen_readonly_fields.add(item_key)
        if callable(item):
            continue
        if not isinstance(item, str) or not _field_or_attr_exists(model_admin, item):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'readonly_fields' refers to '{item}', which is not a field, method, or attribute.",
                    "E035",
                )
            )

    fields = []
    if model_admin.fields is not None:
        fields = list(flatten(model_admin.fields))
    elif model_admin.fieldsets is not None:
        fields, fieldset_errors = _fieldsets_fields_and_errors(model_admin)
        errors.extend(fieldset_errors)
    for item in fields:
        if not isinstance(item, str):
            continue
        if item in readonly_field_names:
            continue
        field = _model_field(model_admin, item)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The form layout refers to '{item}', which is not an editable model field.",
                    PACKAGE_OPTION_CODES["form_layout_unknown"],
                )
            )
        elif not field.editable:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The form layout includes non-editable field '{item}'.",
                    PACKAGE_OPTION_CODES["form_layout_non_editable"],
                )
            )
        elif _is_manual_through_many_to_many(field):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The form layout includes many-to-many field '{item}', which uses a custom through model.",
                    "E013",
                )
            )

    return errors


def _is_manual_through_many_to_many(field):
    return isinstance(field, models.ManyToManyField) and not field.remote_field.through._meta.auto_created


def _fieldsets_fields_and_errors(model_admin):
    fields = []
    errors = []
    fieldsets = getattr(model_admin, "fieldsets", None)
    if not isinstance(fieldsets, (list, tuple)):
        return fields, [_error(model_admin.__class__, "The value of 'fieldsets' must be a list or tuple.", "E007")]

    seen_fields = set()
    for index, fieldset in enumerate(fieldsets):
        if not isinstance(fieldset, (list, tuple)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}]' must be a list or tuple.",
                    "E008",
                )
            )
            continue
        if len(fieldset) != 2:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}]' must be a two-item tuple.",
                    "E009",
                )
            )
            continue

        _name, options = fieldset
        if not isinstance(options, Mapping):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]' must be a dictionary.",
                    "E010",
                )
            )
            continue
        if "fields" not in options:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]' must contain a 'fields' option.",
                    "E011",
                )
            )
            continue
        if not isinstance(options["fields"], (list, tuple)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]['fields']' must be a list or tuple.",
                    "E008",
                )
            )
            continue

        for field_name in flatten(options["fields"]):
            if not isinstance(field_name, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Items in 'fieldsets[{index}][1]['fields']' must be strings.",
                        PACKAGE_OPTION_CODES["form_layout_item_type"],
                    )
                )
                continue
            fields.append(field_name)
            if field_name in seen_fields:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The field '{field_name}' is duplicated in 'fieldsets'.",
                        "E012",
                    )
                )
            seen_fields.add(field_name)
    return fields, errors


def _check_form_option_items(model_admin, option, *, require_model_field=False):
    errors = []
    items = getattr(model_admin, option, None) or ()
    if option == "fields" and isinstance(items, (list, tuple)):
        items = flatten(items)
    seen_fields = set()
    for item in items:
        if not isinstance(item, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"Items in '{option}' must be strings.",
                    PACKAGE_OPTION_CODES["form_layout_item_type"],
                )
            )
            continue
        if option in {"fields", "exclude"}:
            if item in seen_fields:
                code = "E006" if option == "fields" else "E015"
                errors.append(_error(model_admin.__class__, f"The field '{item}' is duplicated in '{option}'.", code))
            seen_fields.add(item)
        if require_model_field and _model_field(model_admin, item) is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of '{option}' refers to unknown field '{item}'.",
                    PACKAGE_OPTION_CODES["form_layout_unknown"],
                )
            )
    return errors


def _check_prepopulated_fields(model_admin):
    value = getattr(model_admin, "prepopulated_fields", {}) or {}
    if not isinstance(value, dict):
        return [_error(model_admin.__class__, "The value of 'prepopulated_fields' must be a dictionary.", "E026")]

    errors = []
    for field_name, source_fields in value.items():
        if not isinstance(field_name, str):
            errors.append(_error(model_admin.__class__, "Keys in 'prepopulated_fields' must be field names.", "E027"))
            continue
        field = _model_field(model_admin, field_name)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields' refers to unknown field '{field_name}'.",
                    "E027",
                )
            )
            continue
        if isinstance(field, (models.DateTimeField, models.ForeignKey, models.ManyToManyField)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields' refers to '{field_name}', which cannot be prepopulated.",
                    "E028",
                )
            )

        if not isinstance(source_fields, (list, tuple)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields[{field_name!r}]' must be a list or tuple.",
                    "E029",
                )
            )
            continue
        for source_field in source_fields:
            if not isinstance(source_field, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Items in 'prepopulated_fields[{field_name!r}]' must be strings.",
                        "E030",
                    )
                )
                continue
            if _model_field(model_admin, source_field) is None:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The value of 'prepopulated_fields[{field_name!r}]' refers to unknown field '{source_field}'.",
                        "E030",
                    )
                )
    return errors


def _check_list_filters(model_admin):
    errors = []
    for item in model_admin.get_list_filter(None):
        if isinstance(item, type):
            if issubclass(item, FieldListFilter):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter {item.__name__!r} must not be used as a top-level list filter.",
                        DJANGO_LIST_FILTER_OPTION_CODES["field_filter_as_top_level"],
                    )
                )
                continue
            if not issubclass(item, ListFilter):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter {item.__name__!r} must inherit from ListFilter.",
                        DJANGO_LIST_FILTER_OPTION_CODES["invalid_filter_class"],
                    )
                )
                continue
            if issubclass(item, SimpleListFilter) and getattr(item, "parameter_name", None) is None:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter {item.__name__!r} has no parameter_name.",
                        PACKAGE_OPTION_CODES["simple_list_filter_parameter"],
                    )
                )
            continue
        if isinstance(item, (tuple, list)):
            if len(item) != 2:
                errors.append(
                    _error(
                        model_admin.__class__,
                        "Field-based 'list_filter' entries must be two-item tuples.",
                        PACKAGE_OPTION_CODES["list_filter_tuple_shape"],
                    )
                )
                continue
            field_path, filter_class = item
            if not isinstance(filter_class, type) or not issubclass(filter_class, FieldListFilter):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter for '{field_path}' must use a FieldListFilter subclass.",
                        DJANGO_LIST_FILTER_OPTION_CODES["invalid_field_filter_class"],
                    )
                )
        else:
            field_path = item
        if not isinstance(field_path, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'list_filter' must be strings or filters.",
                    DJANGO_LIST_FILTER_OPTION_CODES["invalid_field"],
                )
            )
            continue
        errors.extend(
            _check_field_path(model_admin, field_path, "list_filter", DJANGO_LIST_FILTER_OPTION_CODES["invalid_field"])
        )
    return errors


def _check_list_select_related(model_admin):
    value = getattr(model_admin, "list_select_related", False)
    if value is True or value is False:
        return []
    if not isinstance(value, (list, tuple)):
        return [
            _error(
                model_admin.__class__,
                "The value of 'list_select_related' must be a boolean, list, or tuple.",
                DJANGO_SEQUENCE_OPTION_CODES["list_select_related"],
            )
        ]

    errors = []
    for item in value:
        if not isinstance(item, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'list_select_related' must be strings.",
                    PACKAGE_OPTION_CODES["list_select_related_item"],
                )
            )
            continue
        errors.extend(_check_select_related_path(model_admin, item))
    return errors


def _check_select_related_path(model_admin, field_path):
    opts = model_admin.model._meta
    for path_part in field_path.split("__"):
        try:
            field = opts.get_field(path_part)
        except FieldDoesNotExist:
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_select_related' refers to unknown field '{field_path}'.",
                    PACKAGE_OPTION_CODES["list_select_related_path"],
                )
            ]
        if not getattr(field, "is_relation", False) or getattr(field, "many_to_many", False):
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_select_related' refers to '{field_path}', "
                    "which is not a select_related relation.",
                    PACKAGE_OPTION_CODES["list_select_related_path"],
                )
            ]
        related_model = getattr(field, "related_model", None)
        if related_model is None:
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_select_related' refers to unknown relation '{field_path}'.",
                    PACKAGE_OPTION_CODES["list_select_related_path"],
                )
            ]
        opts = related_model._meta
    return []


def _check_list_prefetch_related(model_admin):
    value = getattr(model_admin, "list_prefetch_related", ())
    if value in (None, False):
        return []
    if not isinstance(value, (list, tuple)):
        return [
            _error(
                model_admin.__class__,
                "The value of 'list_prefetch_related' must be a list or tuple.",
                PACKAGE_OPTION_CODES["list_prefetch_related_type"],
            )
        ]

    errors = []
    for item in value:
        lookup = _prefetch_related_lookup(item)
        if lookup is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    "Items in 'list_prefetch_related' must be strings or Prefetch objects.",
                    PACKAGE_OPTION_CODES["list_prefetch_related_type"],
                )
            )
            continue
        errors.extend(_check_prefetch_related_path(model_admin, lookup))
    return errors


def _prefetch_related_lookup(item):
    if isinstance(item, str):
        return item
    if isinstance(item, models.Prefetch):
        return item.prefetch_through
    return None


def _check_prefetch_related_path(model_admin, field_path):
    opts = model_admin.model._meta
    for path_part in field_path.split("__"):
        try:
            field = opts.get_field(path_part)
        except FieldDoesNotExist:
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_prefetch_related' refers to unknown field '{field_path}'.",
                    PACKAGE_OPTION_CODES["list_prefetch_related_path"],
                )
            ]
        if not getattr(field, "is_relation", False):
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_prefetch_related' refers to '{field_path}', "
                    "which is not a prefetch_related relation.",
                    PACKAGE_OPTION_CODES["list_prefetch_related_path"],
                )
            ]
        related_model = getattr(field, "related_model", None)
        if related_model is None:
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_prefetch_related' refers to unknown relation '{field_path}'.",
                    PACKAGE_OPTION_CODES["list_prefetch_related_path"],
                )
            ]
        opts = related_model._meta
    return []


def _check_lookup_fields(
    model_admin,
    option,
    *,
    item_code,
    lookup_code,
    allow_search_prefixes=False,
    allow_descending=False,
    allow_random=False,
):
    errors = []
    items = tuple(getattr(model_admin, option) or ())
    if allow_random and "?" in items and len(items) > 1:
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'ordering' has the random ordering marker '?' but contains other fields.",
                "E032",
                hint='Either remove the "?", or remove the other fields.',
            )
        )
    for item in items:
        if allow_random and isinstance(item, (Combinable, models.OrderBy)):
            order_by = item if isinstance(item, models.OrderBy) else item.asc()
            if isinstance(order_by.expression, models.F):
                field_path = order_by.expression.name
            else:
                continue
        elif isinstance(item, str):
            field_path = item
        else:
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", item_code))
            continue
        if allow_descending:
            field_path = field_path.removeprefix("-")
        if allow_random and field_path == "?":
            continue
        if allow_search_prefixes and field_path[:1] in {"^", "=", "@"}:
            field_path = field_path[1:]
        errors.extend(
            _check_field_path(
                model_admin,
                field_path,
                option,
                lookup_code,
                allow_final_lookup=allow_search_prefixes,
            )
        )
    return errors


def _check_field_path(model_admin, field_path, option, code, *, allow_final_lookup=False):
    if field_path == "pk":
        return []
    model = model_admin.model
    opts = model._meta
    previous_field = None
    path_parts = field_path.split("__")
    for index, path_part in enumerate(path_parts):
        if path_part == "pk":
            path_part = opts.pk.name
        try:
            field = opts.get_field(path_part)
        except FieldDoesNotExist:
            if allow_final_lookup and previous_field is not None and previous_field.get_lookup(path_part):
                return []
            return [
                _error(
                    model_admin.__class__,
                    f"The value of '{option}' refers to unknown field '{field_path}'.",
                    code,
                )
            ]
        previous_field = field
        has_more_parts = index < len(path_parts) - 1
        if has_more_parts and hasattr(field, "path_infos"):
            opts = field.path_infos[-1].to_opts
        elif has_more_parts:
            return [_error(model_admin.__class__, f"The value of '{option}' cannot traverse '{field_path}'.", code)]
    return []


def _check_relation_fields(
    model_admin,
    option,
    *,
    many_to_many_only=False,
    relation_types=None,
    require_registered_remote=False,
    require_field_name=False,
):
    errors = []
    codes = DJANGO_RELATION_OPTION_CODES[option]
    for item in getattr(model_admin, option) or ():
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", codes["missing"]))
            continue
        field = _model_field(model_admin, item)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of '{option}' refers to unknown field '{item}'.",
                    codes["missing"],
                )
            )
            continue
        if require_field_name and field.name != item:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of '{option}' refers to unknown field '{item}'.",
                    codes["missing"],
                )
            )
            continue
        if relation_types is not None and not isinstance(field, relation_types):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' must be a forward ForeignKey, OneToOneField, or ManyToManyField.",
                    codes["invalid_relation"],
                )
            )
            continue
        if many_to_many_only and not isinstance(field, models.ManyToManyField):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' must be a many-to-many field.",
                    codes["not_many_to_many"],
                )
            )
            continue
        if many_to_many_only and not field.remote_field.through._meta.auto_created:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' uses a custom through model and cannot use '{option}'.",
                    codes["manual_through"],
                )
            )
            continue
        if not many_to_many_only and not getattr(field, "remote_field", None):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' must be a relation field.",
                    codes["invalid_relation"],
                )
            )
            continue
        if require_registered_remote:
            remote_model = field.remote_field.model
            try:
                remote_admin = model_admin.admin_site.get_model_admin(remote_model)
            except NotRegistered:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The related model for '{item}' is not registered.",
                        codes["unregistered"],
                    )
                )
                continue
            if not remote_admin.get_search_fields(None):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The related admin for '{item}' must define search_fields.",
                        codes["unsearchable"],
                    )
                )
    return errors


def _check_date_hierarchy(model_admin):
    field_name = getattr(model_admin, "date_hierarchy", None)
    if field_name is None:
        return []
    if not isinstance(field_name, str):
        return [
            _error(
                model_admin.__class__,
                "The value of 'date_hierarchy' must be a field path string.",
                PACKAGE_OPTION_CODES["date_hierarchy_type"],
            )
        ]
    try:
        field = model_field_from_path(model_admin.model, field_name)
    except FieldDoesNotExist:
        return [
            _error(
                model_admin.__class__,
                f"The value of 'date_hierarchy' refers to unknown field '{field_name}'.",
                "E127",
            )
        ]
    if not isinstance(field, (models.DateField, models.DateTimeField)):
        return [_error(model_admin.__class__, f"The field '{field_name}' is not a date or datetime field.", "E128")]
    return []


def _check_radio_fields(model_admin):
    from django_ninja_admin.admins.model import HORIZONTAL, VERTICAL

    value = getattr(model_admin, "radio_fields", {}) or {}
    if not isinstance(value, dict):
        return [_error(model_admin.__class__, "The value of 'radio_fields' must be a dictionary.", "E021")]

    errors = []
    for field_name, orientation in value.items():
        if not isinstance(field_name, str):
            errors.append(_error(model_admin.__class__, "Keys in 'radio_fields' must be field names.", "E022"))
            continue
        field = _model_field(model_admin, field_name)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'radio_fields' refers to unknown field '{field_name}'.",
                    "E022",
                )
            )
            continue
        if not getattr(field, "remote_field", None) and not getattr(field, "choices", None):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{field_name}' must be a relation field or define choices for 'radio_fields'.",
                    "E023",
                )
            )
        if orientation not in {HORIZONTAL, VERTICAL}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'radio_fields[{field_name!r}]' must be HORIZONTAL or VERTICAL.",
                    "E024",
                )
            )
    return errors


def _check_form_option_conflicts(model_admin):
    conflicts = [
        ("autocomplete_fields", "raw_id_fields", PACKAGE_OPTION_CODES["autocomplete_raw_id_conflict"]),
        ("autocomplete_fields", "radio_fields", PACKAGE_OPTION_CODES["autocomplete_radio_conflict"]),
        ("raw_id_fields", "radio_fields", PACKAGE_OPTION_CODES["raw_id_radio_conflict"]),
        ("filter_horizontal", "filter_vertical", PACKAGE_OPTION_CODES["filter_horizontal_vertical_conflict"]),
    ]
    errors = []
    for left, right, code in conflicts:
        left_fields = _option_field_names(model_admin, left)
        right_fields = _option_field_names(model_admin, right)
        for field_name in sorted(left_fields & right_fields):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{field_name}' cannot be in both '{left}' and '{right}'.",
                    code,
                )
            )
    return errors


def _option_field_names(model_admin, option):
    value = getattr(model_admin, option, None) or ()
    if isinstance(value, dict):
        return {field_name for field_name in value if isinstance(field_name, str)}
    if isinstance(value, (list, tuple)):
        return {field_name for field_name in value if isinstance(field_name, str)}
    return set()


def _check_actions(model_admin):
    errors = []
    if model_admin.actions is None:
        return errors
    if not isinstance(model_admin.actions, (list, tuple)):
        return [
            _error(
                model_admin.__class__,
                "The value of 'actions' must be a list, tuple, or None.",
                PACKAGE_OPTION_CODES["actions_type"],
            )
        ]
    resolved_actions = []
    for item in model_admin.actions:
        action = model_admin.get_action(item) if callable(item) or isinstance(item, str) else None
        if action is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The action '{item}' is not a registered action.",
                    PACKAGE_OPTION_CODES["action_missing"],
                )
            )
            continue
        resolved_actions.append(action)
        func = action[0]
        errors.extend(
            _check_closed_contract_schema(
                model_admin,
                getattr(func, "action_input_schema", None),
                f"action '{action[1]}' input_schema",
            )
        )
        errors.extend(
            _check_closed_contract_schema(
                model_admin,
                getattr(func, "action_response_schema", None),
                f"action '{action[1]}' response_schema",
            )
        )
        for permission in getattr(func, "allowed_permissions", ()):
            if not isinstance(permission, str) or not hasattr(model_admin, f"has_{permission}_permission"):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The action '{action[1]}' references unknown permission '{permission}'.",
                        "E129",
                    )
                )
    action_name_counts = Counter(action[1] for action in resolved_actions)
    for name, count in action_name_counts.items():
        if count > 1:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"Action names must be unique. Name {name!r} is not unique.",
                    "E130",
                )
            )
    return errors


def _check_inlines(model_admin):
    from django_ninja_admin.admins.inline import InlineModelAdmin

    errors = []
    inlines = model_admin.inlines or ()
    if not isinstance(inlines, (list, tuple)):
        return [_error(model_admin.__class__, "The value of 'inlines' must be a list or tuple.", "E103")]

    for inline_class in inlines:
        if not isinstance(inline_class, type) or not issubclass(inline_class, InlineModelAdmin):
            errors.append(_error(model_admin.__class__, "Items in 'inlines' must subclass InlineModelAdmin.", "E104"))
            continue
        inline_model = getattr(inline_class, "model", None)
        if inline_model is None:
            errors.append(_error(inline_class, "Inline classes must define a concrete model.", "E105"))
            continue
        if not isinstance(inline_model, ModelBase):
            errors.append(_error(inline_class, "The value of 'model' must be a Django model.", "E106"))
            continue
        try:
            fk = _get_foreign_key(model_admin.model, inline_model, fk_name=getattr(inline_class, "fk_name", None))
        except ValueError as exc:
            errors.append(_error(inline_class, str(exc), "E202"))
            fk = None
        for option in ("fields", "exclude", "readonly_fields", "fieldsets"):
            errors.extend(_check_inline_sequence_option(inline_class, option))
        errors.extend(_check_inline_form_layout_items(inline_class))
        exclude = getattr(inline_class, "exclude", None)
        if fk is not None and isinstance(exclude, (list, tuple)) and fk.name in exclude:
            errors.append(
                _error(
                    inline_class,
                    f"Cannot exclude the parent foreign key field '{fk.name}' from inline forms.",
                    "E201",
                )
            )
        extra = getattr(inline_class, "extra", None)
        min_num = getattr(inline_class, "min_num", None)
        max_num = getattr(inline_class, "max_num", None)
        if not _is_integer_option(extra):
            errors.append(_error(inline_class, "The value of 'extra' must be an integer.", "E203"))
        else:
            extra_int = cast(int, extra)
            if extra_int < 0:
                errors.append(
                    _error(
                        inline_class,
                        "The value of 'extra' must not be negative.",
                        PACKAGE_OPTION_CODES["inline_extra_negative"],
                    )
                )
        if min_num is not None and not _is_integer_option(min_num):
            errors.append(_error(inline_class, "The value of 'min_num' must be an integer or None.", "E205"))
        elif min_num is not None:
            min_num_int = cast(int, min_num)
            if min_num_int < 0:
                errors.append(
                    _error(
                        inline_class,
                        "The value of 'min_num' must not be negative.",
                        PACKAGE_OPTION_CODES["inline_min_num_negative"],
                    )
                )
        if max_num is not None and not _is_integer_option(max_num):
            errors.append(_error(inline_class, "The value of 'max_num' must be an integer or None.", "E204"))
        elif max_num is not None:
            max_num_int = cast(int, max_num)
            if max_num_int < 0:
                errors.append(
                    _error(
                        inline_class,
                        "The value of 'max_num' must not be negative.",
                        PACKAGE_OPTION_CODES["inline_max_num_negative"],
                    )
                )
        if _is_integer_option(min_num) and _is_integer_option(max_num):
            min_num_int = cast(int, min_num)
            max_num_int = cast(int, max_num)
            if min_num_int >= 0 and max_num_int >= 0 and min_num_int > max_num_int:
                errors.append(
                    _error(
                        inline_class,
                        "The value of 'min_num' must not exceed 'max_num'.",
                        PACKAGE_OPTION_CODES["inline_min_exceeds_max"],
                    )
                )
        if not isinstance(getattr(inline_class, "can_delete", True), bool):
            errors.append(
                _error(
                    inline_class,
                    "The value of 'can_delete' must be a boolean.",
                    PACKAGE_OPTION_CODES["inline_can_delete_type"],
                )
            )
        if not isinstance(getattr(inline_class, "show_change_link", False), bool):
            errors.append(
                _error(
                    inline_class,
                    "The value of 'show_change_link' must be a boolean.",
                    PACKAGE_OPTION_CODES["inline_show_change_link_type"],
                )
            )
        formset = getattr(inline_class, "formset", None)
        if not isinstance(formset, type) or not issubclass(formset, BaseInlineFormSet):
            errors.append(_error(inline_class, "The value of 'formset' must inherit from BaseInlineFormSet.", "E206"))
        form_class = getattr(inline_class, "form_class", None)
        if form_class is not None:
            if not isinstance(form_class, type) or not issubclass(form_class, BaseModelForm):
                errors.append(_error(inline_class, "The value of 'form_class' must inherit from ModelForm.", "E016"))
            else:
                form_model = getattr(getattr(form_class, "_meta", None), "model", None)
                if form_model is not None and form_model is not inline_model:
                    errors.append(
                        _error(
                            inline_class,
                            f"The value of 'form_class' declares model '{form_model._meta.label}', "
                            f"but this admin is registered for '{inline_model._meta.label}'.",
                            PACKAGE_OPTION_CODES["form_class_model_mismatch"],
                        )
                    )
    return errors


def _check_inline_sequence_option(inline_class, option):
    value = getattr(inline_class, option, None)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return [
            _error(
                inline_class,
                f"The value of '{option}' must be a list or tuple.",
                PACKAGE_OPTION_CODES["inline_layout_sequence_type"],
            )
        ]
    return []


def _check_inline_form_layout_items(inline_class):
    errors = []
    readonly_fields = getattr(inline_class, "readonly_fields", None) or ()
    readonly_field_names = (
        {
            field_name_for_display(field)
            for field in readonly_fields
            if callable(field) or (isinstance(field, str) and _field_or_attr_exists(inline_class, field))
        }
        if isinstance(readonly_fields, (list, tuple))
        else set()
    )
    errors.extend(_check_inline_form_option_items(inline_class, "fields", readonly_field_names=readonly_field_names))
    errors.extend(_check_inline_form_option_items(inline_class, "exclude", require_model_field=True))
    errors.extend(_check_inline_readonly_fields(inline_class))
    errors.extend(_check_inline_fieldsets(inline_class, readonly_field_names=readonly_field_names))
    return errors


def _check_inline_form_option_items(
    inline_class,
    option,
    *,
    readonly_field_names=None,
    require_model_field=False,
):
    items = getattr(inline_class, option, None) or ()
    if not isinstance(items, (list, tuple)):
        return []
    if option == "fields":
        items = flatten(items)
    errors = []
    seen_fields = set()
    readonly_field_names = readonly_field_names or set()
    for item in items:
        if not isinstance(item, str):
            errors.append(
                _error(
                    inline_class,
                    f"Items in inline '{option}' must be strings.",
                    PACKAGE_OPTION_CODES["inline_layout_item_type"],
                )
            )
            continue
        if item in seen_fields:
            errors.append(
                _error(
                    inline_class,
                    f"The field '{item}' is duplicated in inline '{option}'.",
                    PACKAGE_OPTION_CODES["inline_layout_duplicate"],
                )
            )
        seen_fields.add(item)
        if item in readonly_field_names:
            continue
        field = _model_field(inline_class, item)
        if field is None:
            message = (
                f"The value of inline '{option}' refers to unknown field '{item}'."
                if require_model_field
                else f"The value of inline '{option}' refers to '{item}', "
                "which is not an editable model field or readonly field."
            )
            errors.append(_error(inline_class, message, PACKAGE_OPTION_CODES["inline_layout_unknown"]))
        elif option == "fields" and not field.editable:
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline '{option}' includes non-editable field '{item}'.",
                    PACKAGE_OPTION_CODES["inline_layout_unknown"],
                )
            )
    return errors


def _check_inline_readonly_fields(inline_class):
    readonly_fields = getattr(inline_class, "readonly_fields", None) or ()
    if not isinstance(readonly_fields, (list, tuple)):
        return []
    errors = []
    seen_fields = set()
    for item in readonly_fields:
        item_key = field_name_for_display(item)
        if item_key in seen_fields:
            errors.append(
                _error(
                    inline_class,
                    f"The field '{item_key}' is duplicated in inline 'readonly_fields'.",
                    PACKAGE_OPTION_CODES["inline_layout_duplicate"],
                )
            )
        seen_fields.add(item_key)
        if callable(item):
            continue
        if not isinstance(item, str) or not _field_or_attr_exists(inline_class, item):
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline 'readonly_fields' refers to '{item}', "
                    "which is not a field, method, or attribute.",
                    PACKAGE_OPTION_CODES["inline_readonly_unknown"],
                )
            )
    return errors


def _check_inline_fieldsets(inline_class, *, readonly_field_names=None):
    fieldsets = getattr(inline_class, "fieldsets", None)
    if fieldsets is None or not isinstance(fieldsets, (list, tuple)):
        return []
    errors = []
    seen_fields = set()
    readonly_field_names = readonly_field_names or set()
    for index, fieldset in enumerate(fieldsets):
        if not isinstance(fieldset, (list, tuple)) or len(fieldset) != 2:
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline 'fieldsets[{index}]' must be a two-item tuple.",
                    PACKAGE_OPTION_CODES["inline_fieldset_shape"],
                )
            )
            continue
        _name, options = fieldset
        if not isinstance(options, Mapping):
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline 'fieldsets[{index}][1]' must be a dictionary.",
                    PACKAGE_OPTION_CODES["inline_fieldset_shape"],
                )
            )
            continue
        if "fields" not in options:
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline 'fieldsets[{index}][1]' must contain a 'fields' option.",
                    PACKAGE_OPTION_CODES["inline_fieldset_shape"],
                )
            )
            continue
        fields = options["fields"]
        if not isinstance(fields, (list, tuple)):
            errors.append(
                _error(
                    inline_class,
                    f"The value of inline 'fieldsets[{index}][1]['fields']' must be a list or tuple.",
                    PACKAGE_OPTION_CODES["inline_fieldset_shape"],
                )
            )
            continue
        for field_name in flatten(fields):
            if not isinstance(field_name, str):
                errors.append(
                    _error(
                        inline_class,
                        f"Items in inline 'fieldsets[{index}][1]['fields']' must be strings.",
                        PACKAGE_OPTION_CODES["inline_layout_item_type"],
                    )
                )
                continue
            if field_name in seen_fields:
                errors.append(
                    _error(
                        inline_class,
                        f"The field '{field_name}' is duplicated in inline 'fieldsets'.",
                        PACKAGE_OPTION_CODES["inline_layout_duplicate"],
                    )
                )
            seen_fields.add(field_name)
            if field_name in readonly_field_names:
                continue
            field = _model_field(inline_class, field_name)
            if field is None or not field.editable:
                errors.append(
                    _error(
                        inline_class,
                        f"The value of inline 'fieldsets' refers to '{field_name}', "
                        "which is not an editable model field or readonly field.",
                        PACKAGE_OPTION_CODES["inline_layout_unknown"],
                    )
                )
    return errors
