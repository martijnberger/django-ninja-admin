from __future__ import annotations

from collections.abc import Mapping

from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import Paginator
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.expressions import Combinable
from django.forms.models import BaseInlineFormSet, BaseModelForm, _get_foreign_key

from django_ninja_admin.exceptions import NotRegistered
from django_ninja_admin.filters import FieldListFilter, SimpleListFilter
from django_ninja_admin.utils.flatten import flatten
from django_ninja_admin.utils.lookup import (
    field_name_for_display,
    model_field_from_path,
    single_valued_model_field_from_path,
)

ERROR_PREFIX = "django_ninja_admin"


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
    errors.extend(_check_form_layout(model_admin))
    errors.extend(_check_prepopulated_fields(model_admin))
    errors.extend(_check_list_filters(model_admin))
    errors.extend(_check_radio_fields(model_admin))
    errors.extend(_check_form_option_conflicts(model_admin))
    errors.extend(_check_lookup_fields(model_admin, "search_fields", allow_search_prefixes=True))
    errors.extend(_check_lookup_fields(model_admin, "ordering", allow_descending=True, allow_random=True))
    forward_relation_types = (models.ForeignKey, models.ManyToManyField)
    errors.extend(
        _check_relation_fields(
            model_admin,
            "autocomplete_fields",
            relation_types=forward_relation_types,
            require_registered_remote=True,
        )
    )
    errors.extend(_check_relation_fields(model_admin, "raw_id_fields", relation_types=forward_relation_types))
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
        return [_error(model_admin.__class__, f"The value of '{option}' must be a list or tuple.", "E001")]
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
        errors.append(_error(model_admin.__class__, "The value of 'list_display' must not be empty.", "E091"))
    editable_form_fields = _editable_form_field_names(model_admin)
    excluded_form_fields = set(model_admin.get_exclude(None) or ())
    for item in list_display:
        if callable(item):
            continue
        if not isinstance(item, str):
            errors.append(
                _error(model_admin.__class__, "Items in 'list_display' must be strings or callables.", "E002")
            )
            continue
        if item == "__str__":
            continue
        field = None
        if "__" in item:
            try:
                field = single_valued_model_field_from_path(model_admin.model, item)
            except FieldDoesNotExist:
                pass
        elif _field_or_attr_exists(model_admin, item):
            field = _model_field(model_admin, item)

        if field is None and not _field_or_attr_exists(model_admin, item):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is not a field, method, or attribute.",
                    "E004",
                )
            )
            continue
        if field is not None and (getattr(field, "many_to_many", False) or getattr(field, "one_to_many", False)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is a many-to-many or reverse field.",
                    "E043",
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
                        "E095",
                    )
                )
                continue
            item_key = field_name_for_display(item)
            if item_key in seen_display_links:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The field '{item_key}' is duplicated in 'list_display_links'.",
                        "E079",
                    )
                )
            seen_display_links.add(item_key)
            if not _display_item_in(item, list_display):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The value of 'list_display_links' refers to '{item}', which is not in 'list_display'.",
                        "E005",
                    )
                )

    editable = tuple(model_admin.list_editable or ())
    seen_editable = set()
    for item in editable:
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, "Items in 'list_editable' must be strings.", "E094"))
            continue
        item_key = field_name_for_display(item)
        if item_key in seen_editable:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item_key}' is duplicated in 'list_editable'.",
                    "E093",
                )
            )
        seen_editable.add(item_key)
        if item not in list_display:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not in 'list_display'.",
                    "E006",
                )
            )
            continue
        if configured_list_display_links and item in configured_list_display_links:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is also in 'list_display_links'.",
                    "E007",
                )
            )
        elif list_display and item == list_display[0] and configured_list_display_links == ():
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to the first field in 'list_display' ('{item}'), "
                    "which cannot be used unless 'list_display_links' is set.",
                    "E066",
                )
            )
        field = _model_field(model_admin, item)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not a model field.",
                    "E008",
                )
            )
            continue
        if field.primary_key:
            errors.append(_error(model_admin.__class__, f"The field '{item}' is a primary key.", "E009"))
        if not field.editable:
            errors.append(_error(model_admin.__class__, f"The field '{item}' is not editable.", "E010"))
        if item in excluded_form_fields or (editable_form_fields is not None and item not in editable_form_fields):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not included in the admin form.",
                    "E044",
                )
            )
    return errors


def _check_sortable_by(model_admin):
    value = getattr(model_admin, "sortable_by", None)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return [_error(model_admin.__class__, "The value of 'sortable_by' must be a list or tuple.", "E055")]

    errors = []
    list_display = tuple(model_admin.get_list_display(None))
    for item in value:
        if not isinstance(item, str) and not callable(item):
            errors.append(_error(model_admin.__class__, "Items in 'sortable_by' must be strings or callables.", "E056"))
            continue
        if not _display_item_in(item, list_display):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'sortable_by' refers to '{item}', which is not in 'list_display'.",
                    "E057",
                )
            )
    return errors


def _check_pagination_options(model_admin):
    errors = []
    list_per_page = getattr(model_admin, "list_per_page", None)
    list_max_show_all = getattr(model_admin, "list_max_show_all", None)
    if not _is_integer_option(list_per_page):
        errors.append(_error(model_admin.__class__, "The value of 'list_per_page' must be an integer.", "E067"))
    elif list_per_page < 1:
        errors.append(
            _error(model_admin.__class__, "The value of 'list_per_page' must be greater than zero.", "E104")
        )
    if not _is_integer_option(list_max_show_all):
        errors.append(_error(model_admin.__class__, "The value of 'list_max_show_all' must be an integer.", "E068"))
    elif list_max_show_all < 0:
        errors.append(
            _error(model_admin.__class__, "The value of 'list_max_show_all' must not be negative.", "E105")
        )
    return errors


def _is_integer_option(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_paginator(model_admin):
    paginator = getattr(model_admin, "paginator", None)
    if not isinstance(paginator, type) or not issubclass(paginator, Paginator):
        return [_error(model_admin.__class__, "The value of 'paginator' must inherit from Paginator.", "E090")]
    return []


def _check_boolean_options(model_admin):
    errors = []
    if not isinstance(getattr(model_admin, "save_as", False), bool):
        errors.append(_error(model_admin.__class__, "The value of 'save_as' must be a boolean.", "E069"))
    if not isinstance(getattr(model_admin, "save_as_continue", True), bool):
        errors.append(_error(model_admin.__class__, "The value of 'save_as_continue' must be a boolean.", "E083"))
    if not isinstance(getattr(model_admin, "save_on_top", False), bool):
        errors.append(_error(model_admin.__class__, "The value of 'save_on_top' must be a boolean.", "E070"))
    if not isinstance(getattr(model_admin, "actions_on_top", True), bool):
        errors.append(_error(model_admin.__class__, "The value of 'actions_on_top' must be a boolean.", "E084"))
    if not isinstance(getattr(model_admin, "actions_on_bottom", False), bool):
        errors.append(_error(model_admin.__class__, "The value of 'actions_on_bottom' must be a boolean.", "E085"))
    if not isinstance(getattr(model_admin, "actions_selection_counter", True), bool):
        errors.append(
            _error(model_admin.__class__, "The value of 'actions_selection_counter' must be a boolean.", "E086")
        )
    if not isinstance(getattr(model_admin, "show_full_result_count", True), bool):
        errors.append(_error(model_admin.__class__, "The value of 'show_full_result_count' must be a boolean.", "E087"))
    view_on_site = getattr(model_admin, "view_on_site", True)
    if not callable(view_on_site) and not isinstance(view_on_site, bool):
        errors.append(
            _error(
                model_admin.__class__,
                "The value of 'view_on_site' must be a callable or a boolean.",
                "E071",
            )
        )
    return errors


def _check_show_facets(model_admin):
    from django_ninja_admin.constants import ShowFacets

    if not isinstance(getattr(model_admin, "show_facets", ShowFacets.ALLOW), ShowFacets):
        return [_error(model_admin.__class__, "The value of 'show_facets' must be a ShowFacets value.", "E088")]
    return []


def _check_text_options(model_admin):
    errors = []
    search_help_text = getattr(model_admin, "search_help_text", None)
    if search_help_text is not None and not isinstance(search_help_text, str):
        errors.append(
            _error(model_admin.__class__, "The value of 'search_help_text' must be a string or None.", "E089")
        )
    empty_value_display = getattr(model_admin, "empty_value_display", None)
    if empty_value_display is not None and not isinstance(empty_value_display, str):
        errors.append(
            _error(model_admin.__class__, "The value of 'empty_value_display' must be a string or None.", "E097")
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
        return [_error(model_admin.__class__, "The value of 'form_class' must inherit from ModelForm.", "E058")]

    form_model = getattr(getattr(form_class, "_meta", None), "model", None)
    if form_model is not None and form_model is not model_admin.model:
        return [
            _error(
                model_admin.__class__,
                f"The value of 'form_class' declares model '{form_model._meta.label}', "
                f"but this admin is registered for '{model_admin.model._meta.label}'.",
                "E059",
            )
        ]
    return []


def _check_formfield_overrides(model_admin):
    value = getattr(model_admin, "formfield_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [_error(model_admin.__class__, "The value of 'formfield_overrides' must be a mapping.", "E060")]

    errors = []
    for field_class, overrides in value.items():
        if not isinstance(field_class, type) or not issubclass(field_class, models.Field):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'formfield_overrides' must be Django model field classes.",
                    "E061",
                )
            )
            continue
        if not isinstance(overrides, Mapping):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_class.__name__}' must be a mapping of formfield keyword arguments.",
                    "E062",
                )
            )
            continue
        for key in overrides:
            if not isinstance(key, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Keys in the override for '{field_class.__name__}' must be strings.",
                        "E063",
                    )
                )
    return errors


def _check_schema_field_overrides(model_admin):
    value = getattr(model_admin, "schema_field_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [_error(model_admin.__class__, "The value of 'schema_field_overrides' must be a mapping.", "E098")]

    errors = []
    for field_name, override in value.items():
        if not isinstance(field_name, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'schema_field_overrides' must be field names.",
                    "E099",
                )
            )
        if isinstance(override, tuple) and len(override) not in {1, 2}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_name}' must be a type annotation or a one/two-item tuple.",
                    "E100",
                )
            )
    return errors


def _check_form_schema_field_overrides(model_admin):
    value = getattr(model_admin, "form_schema_field_overrides", {}) or {}
    if not isinstance(value, Mapping):
        return [_error(model_admin.__class__, "The value of 'form_schema_field_overrides' must be a mapping.", "E101")]

    errors = []
    for field_name, override in value.items():
        if not isinstance(field_name, str):
            errors.append(
                _error(
                    model_admin.__class__,
                    "Keys in 'form_schema_field_overrides' must be field names.",
                    "E102",
                )
            )
        if isinstance(override, tuple) and len(override) not in {1, 2}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The override for '{field_name}' must be a type annotation or a one/two-item tuple.",
                    "E103",
                )
            )
    return errors


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
                "E011",
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
                    "E092",
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
                    "E012",
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
                    "E014",
                )
            )
        elif not field.editable:
            errors.append(
                _error(model_admin.__class__, f"The form layout includes non-editable field '{item}'.", "E015")
            )
        elif _is_manual_through_many_to_many(field):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The form layout includes many-to-many field '{item}', which uses a custom through model.",
                    "E078",
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
        return fields, [_error(model_admin.__class__, "The value of 'fieldsets' must be a list or tuple.", "E013")]

    seen_fields = set()
    for index, fieldset in enumerate(fieldsets):
        if not isinstance(fieldset, (list, tuple)) or len(fieldset) != 2:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}]' must be a two-item tuple.",
                    "E013",
                )
            )
            continue

        _name, options = fieldset
        if not isinstance(options, Mapping):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]' must be a dictionary.",
                    "E013",
                )
            )
            continue
        if "fields" not in options:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]' must contain a 'fields' option.",
                    "E013",
                )
            )
            continue
        if not isinstance(options["fields"], (list, tuple)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'fieldsets[{index}][1]['fields']' must be a list or tuple.",
                    "E013",
                )
            )
            continue

        for field_name in flatten(options["fields"]):
            if not isinstance(field_name, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Items in 'fieldsets[{index}][1]['fields']' must be strings.",
                        "E013",
                    )
                )
                continue
            fields.append(field_name)
            if field_name in seen_fields:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The field '{field_name}' is duplicated in 'fieldsets'.",
                        "E064",
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
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", "E048"))
            continue
        if option in {"fields", "exclude"}:
            if item in seen_fields:
                code = "E065" if option == "fields" else "E080"
                errors.append(
                    _error(model_admin.__class__, f"The field '{item}' is duplicated in '{option}'.", code)
                )
            seen_fields.add(item)
        if require_model_field and _model_field(model_admin, item) is None:
            errors.append(
                _error(model_admin.__class__, f"The value of '{option}' refers to unknown field '{item}'.", "E049")
            )
    return errors


def _check_prepopulated_fields(model_admin):
    value = getattr(model_admin, "prepopulated_fields", {}) or {}
    if not isinstance(value, dict):
        return [_error(model_admin.__class__, "The value of 'prepopulated_fields' must be a dictionary.", "E050")]

    errors = []
    for field_name, source_fields in value.items():
        if not isinstance(field_name, str):
            errors.append(_error(model_admin.__class__, "Keys in 'prepopulated_fields' must be field names.", "E051"))
            continue
        field = _model_field(model_admin, field_name)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields' refers to unknown field '{field_name}'.",
                    "E051",
                )
            )
            continue
        if isinstance(field, (models.DateTimeField, models.ForeignKey, models.ManyToManyField)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields' refers to '{field_name}', which cannot be prepopulated.",
                    "E052",
                )
            )

        if not isinstance(source_fields, (list, tuple)):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'prepopulated_fields[{field_name!r}]' must be a list or tuple.",
                    "E053",
                )
            )
            continue
        for source_field in source_fields:
            if not isinstance(source_field, str):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"Items in 'prepopulated_fields[{field_name!r}]' must be strings.",
                        "E054",
                    )
                )
                continue
            if _model_field(model_admin, source_field) is None:
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The value of 'prepopulated_fields[{field_name!r}]' refers to unknown field "
                        f"'{source_field}'.",
                        "E054",
                    )
                )
    return errors


def _check_list_filters(model_admin):
    errors = []
    for item in model_admin.get_list_filter(None):
        if isinstance(item, type) and issubclass(item, SimpleListFilter):
            if getattr(item, "parameter_name", None) is None:
                errors.append(
                    _error(model_admin.__class__, f"The list filter {item.__name__!r} has no parameter_name.", "E016")
                )
            continue
        if isinstance(item, (tuple, list)):
            if len(item) != 2:
                errors.append(
                    _error(
                        model_admin.__class__,
                        "Field-based 'list_filter' entries must be two-item tuples.",
                        "E017",
                    )
                )
                continue
            field_path, filter_class = item
            if not isinstance(filter_class, type) or not issubclass(filter_class, FieldListFilter):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter for '{field_path}' must use a FieldListFilter subclass.",
                        "E017",
                    )
                )
        else:
            field_path = item
        if not isinstance(field_path, str):
            errors.append(_error(model_admin.__class__, "Items in 'list_filter' must be strings or filters.", "E018"))
            continue
        errors.extend(_check_field_path(model_admin, field_path, "list_filter", "E019"))
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
                "E045",
            )
        ]

    errors = []
    for item in value:
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, "Items in 'list_select_related' must be strings.", "E045"))
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
                    "E046",
                )
            ]
        if not getattr(field, "is_relation", False) or getattr(field, "many_to_many", False):
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_select_related' refers to '{field_path}', "
                    "which is not a select_related relation.",
                    "E046",
                )
            ]
        related_model = getattr(field, "related_model", None)
        if related_model is None:
            return [
                _error(
                    model_admin.__class__,
                    f"The value of 'list_select_related' refers to unknown relation '{field_path}'.",
                    "E046",
                )
            ]
        opts = related_model._meta
    return []


def _check_lookup_fields(
    model_admin,
    option,
    *,
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
                "E072",
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
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", "E020"))
            continue
        if allow_descending:
            field_path = field_path.removeprefix("-")
        if allow_random and field_path == "?":
            continue
        if allow_search_prefixes and field_path[:1] in {"^", "=", "@"}:
            field_path = field_path[1:]
        errors.extend(
            _check_field_path(model_admin, field_path, option, "E021", allow_final_lookup=allow_search_prefixes)
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
):
    errors = []
    for item in getattr(model_admin, option) or ():
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", "E022"))
            continue
        field = _model_field(model_admin, item)
        if field is None:
            errors.append(
                _error(model_admin.__class__, f"The value of '{option}' refers to unknown field '{item}'.", "E023")
            )
            continue
        if relation_types is not None and not isinstance(field, relation_types):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' must be a forward ForeignKey, OneToOneField, or ManyToManyField.",
                    "E025",
                )
            )
            continue
        if many_to_many_only and not isinstance(field, models.ManyToManyField):
            errors.append(_error(model_admin.__class__, f"The field '{item}' must be a many-to-many field.", "E024"))
            continue
        if many_to_many_only and not field.remote_field.through._meta.auto_created:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{item}' uses a custom through model and cannot use '{option}'.",
                    "E047",
                )
            )
            continue
        if not many_to_many_only and not getattr(field, "remote_field", None):
            errors.append(_error(model_admin.__class__, f"The field '{item}' must be a relation field.", "E025"))
            continue
        if require_registered_remote:
            remote_model = field.remote_field.model
            try:
                remote_admin = model_admin.admin_site.get_model_admin(remote_model)
            except NotRegistered:
                errors.append(
                    _error(model_admin.__class__, f"The related model for '{item}' is not registered.", "E026")
                )
                continue
            if not remote_admin.get_search_fields(None):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The related admin for '{item}' must define search_fields.",
                        "E027",
                    )
                )
    return errors


def _check_date_hierarchy(model_admin):
    field_name = getattr(model_admin, "date_hierarchy", None)
    if field_name is None:
        return []
    if not isinstance(field_name, str):
        return [_error(model_admin.__class__, "The value of 'date_hierarchy' must be a field path string.", "E096")]
    try:
        field = model_field_from_path(model_admin.model, field_name)
    except FieldDoesNotExist:
        return [
            _error(
                model_admin.__class__,
                f"The value of 'date_hierarchy' refers to unknown field '{field_name}'.",
                "E028",
            )
        ]
    if not isinstance(field, (models.DateField, models.DateTimeField)):
        return [_error(model_admin.__class__, f"The field '{field_name}' is not a date or datetime field.", "E029")]
    return []


def _check_radio_fields(model_admin):
    from django_ninja_admin.admins.model import HORIZONTAL, VERTICAL

    value = getattr(model_admin, "radio_fields", {}) or {}
    if not isinstance(value, dict):
        return [_error(model_admin.__class__, "The value of 'radio_fields' must be a dictionary.", "E034")]

    errors = []
    for field_name, orientation in value.items():
        if not isinstance(field_name, str):
            errors.append(_error(model_admin.__class__, "Keys in 'radio_fields' must be field names.", "E035"))
            continue
        field = _model_field(model_admin, field_name)
        if field is None:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'radio_fields' refers to unknown field '{field_name}'.",
                    "E036",
                )
            )
            continue
        if not getattr(field, "remote_field", None) and not getattr(field, "choices", None):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The field '{field_name}' must be a relation field or define choices for 'radio_fields'.",
                    "E037",
                )
            )
        if orientation not in {HORIZONTAL, VERTICAL}:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'radio_fields[{field_name!r}]' must be HORIZONTAL or VERTICAL.",
                    "E038",
                )
            )
    return errors


def _check_form_option_conflicts(model_admin):
    conflicts = [
        ("autocomplete_fields", "raw_id_fields", "E039"),
        ("autocomplete_fields", "radio_fields", "E040"),
        ("raw_id_fields", "radio_fields", "E041"),
        ("filter_horizontal", "filter_vertical", "E042"),
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
        return [_error(model_admin.__class__, "The value of 'actions' must be a list, tuple, or None.", "E082")]
    for item in model_admin.actions:
        action = model_admin.get_action(item) if callable(item) or isinstance(item, str) else None
        if action is None:
            errors.append(_error(model_admin.__class__, f"The action '{item}' is not a registered action.", "E030"))
            continue
        func = action[0]
        for permission in getattr(func, "allowed_permissions", ()):
            if not isinstance(permission, str) or not hasattr(model_admin, f"has_{permission}_permission"):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The action '{action[1]}' references unknown permission '{permission}'.",
                        "E064",
                    )
                )
    return errors


def _check_inlines(model_admin):
    from django_ninja_admin.admins.inline import InlineModelAdmin

    errors = []
    inlines = model_admin.inlines or ()
    if not isinstance(inlines, (list, tuple)):
        return [_error(model_admin.__class__, "The value of 'inlines' must be a list or tuple.", "E081")]

    for inline_class in inlines:
        if not isinstance(inline_class, type) or not issubclass(inline_class, InlineModelAdmin):
            errors.append(_error(model_admin.__class__, "Items in 'inlines' must subclass InlineModelAdmin.", "E031"))
            continue
        inline_model = getattr(inline_class, "model", None)
        if not isinstance(inline_model, ModelBase):
            errors.append(_error(inline_class, "Inline classes must define a concrete model.", "E032"))
            continue
        try:
            fk = _get_foreign_key(model_admin.model, inline_model, fk_name=getattr(inline_class, "fk_name", None))
        except ValueError as exc:
            errors.append(_error(inline_class, str(exc), "E033"))
            fk = None
        for option in ("fields", "exclude", "readonly_fields", "fieldsets"):
            errors.extend(_check_inline_sequence_option(inline_class, option))
        exclude = getattr(inline_class, "exclude", None)
        if fk is not None and isinstance(exclude, (list, tuple)) and fk.name in exclude:
            errors.append(
                _error(
                    inline_class,
                    f"Cannot exclude the parent foreign key field '{fk.name}' from inline forms.",
                    "E077",
                )
            )
        extra = getattr(inline_class, "extra", None)
        min_num = getattr(inline_class, "min_num", None)
        max_num = getattr(inline_class, "max_num", None)
        if not _is_integer_option(extra):
            errors.append(_error(inline_class, "The value of 'extra' must be an integer.", "E073"))
        elif extra < 0:
            errors.append(_error(inline_class, "The value of 'extra' must not be negative.", "E106"))
        if min_num is not None and not _is_integer_option(min_num):
            errors.append(_error(inline_class, "The value of 'min_num' must be an integer or None.", "E074"))
        elif min_num is not None and min_num < 0:
            errors.append(_error(inline_class, "The value of 'min_num' must not be negative.", "E107"))
        if max_num is not None and not _is_integer_option(max_num):
            errors.append(_error(inline_class, "The value of 'max_num' must be an integer or None.", "E075"))
        elif max_num is not None and max_num < 0:
            errors.append(_error(inline_class, "The value of 'max_num' must not be negative.", "E108"))
        if (
            _is_integer_option(min_num)
            and _is_integer_option(max_num)
            and min_num >= 0
            and max_num >= 0
            and min_num > max_num
        ):
            errors.append(_error(inline_class, "The value of 'min_num' must not exceed 'max_num'.", "E109"))
        if not isinstance(getattr(inline_class, "can_delete", True), bool):
            errors.append(_error(inline_class, "The value of 'can_delete' must be a boolean.", "E110"))
        if not isinstance(getattr(inline_class, "show_change_link", False), bool):
            errors.append(_error(inline_class, "The value of 'show_change_link' must be a boolean.", "E111"))
        formset = getattr(inline_class, "formset", None)
        if not isinstance(formset, type) or not issubclass(formset, BaseInlineFormSet):
            errors.append(_error(inline_class, "The value of 'formset' must inherit from BaseInlineFormSet.", "E076"))
        form_class = getattr(inline_class, "form_class", None)
        if form_class is not None:
            if not isinstance(form_class, type) or not issubclass(form_class, BaseModelForm):
                errors.append(_error(inline_class, "The value of 'form_class' must inherit from ModelForm.", "E058"))
            else:
                form_model = getattr(getattr(form_class, "_meta", None), "model", None)
                if form_model is not None and form_model is not inline_model:
                    errors.append(
                        _error(
                            inline_class,
                            f"The value of 'form_class' declares model '{form_model._meta.label}', "
                            f"but this admin is registered for '{inline_model._meta.label}'.",
                            "E059",
                        )
                    )
    return errors


def _check_inline_sequence_option(inline_class, option):
    value = getattr(inline_class, option, None)
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return [_error(inline_class, f"The value of '{option}' must be a list or tuple.", "E112")]
    return []
