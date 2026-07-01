from __future__ import annotations

from collections.abc import Mapping

from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.base import ModelBase
from django.forms.models import BaseModelForm, _get_foreign_key

from django_ninja_admin.exceptions import NotRegistered
from django_ninja_admin.filters import FieldListFilter, SimpleListFilter
from django_ninja_admin.utils.flatten_fieldsets import flatten_fieldsets
from django_ninja_admin.utils.lookup import field_name_for_display

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
    errors.extend(_check_display_options(model_admin))
    errors.extend(_check_sortable_by(model_admin))
    errors.extend(_check_form_class(model_admin))
    errors.extend(_check_formfield_overrides(model_admin))
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
        if "__" in item:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which must not contain '__'.",
                    "E003",
                )
            )
            continue
        if not _field_or_attr_exists(model_admin, item):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is not a field, method, or attribute.",
                    "E004",
                )
            )
            continue
        field = _model_field(model_admin, item)
        if field is not None and getattr(field, "many_to_many", False):
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_display' refers to '{item}', which is a many-to-many field.",
                    "E043",
                )
            )

    list_display_links = model_admin.get_list_display_links(None, list_display)
    if list_display_links is not None:
        for item in list_display_links:
            if not _display_item_in(item, list_display):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The value of 'list_display_links' refers to '{item}', which is not in 'list_display'.",
                        "E005",
                    )
                )

    editable = tuple(model_admin.list_editable or ())
    for item in editable:
        if item not in list_display:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is not in 'list_display'.",
                    "E006",
                )
            )
            continue
        if list_display_links and item in list_display_links:
            errors.append(
                _error(
                    model_admin.__class__,
                    f"The value of 'list_editable' refers to '{item}', which is also in 'list_display_links'.",
                    "E007",
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


def _editable_form_field_names(model_admin):
    if model_admin.fields is not None:
        return set(model_admin.fields)
    if model_admin.fieldsets is not None:
        try:
            return set(flatten_fieldsets(model_admin.fieldsets))
        except (KeyError, TypeError, ValueError):
            return None
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
    for item in readonly_fields:
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
        fields = list(model_admin.fields)
    elif model_admin.fieldsets is not None:
        try:
            fields = flatten_fieldsets(model_admin.fieldsets)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(
                _error(model_admin.__class__, f"The value of 'fieldsets' is malformed: {exc}.", "E013")
            )
    for item in fields:
        if not isinstance(item, str):
            continue
        if item in readonly_fields:
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

    return errors


def _check_form_option_items(model_admin, option, *, require_model_field=False):
    errors = []
    for item in getattr(model_admin, option, None) or ():
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", "E048"))
            continue
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
        if isinstance(item, (tuple, list)) and len(item) == 2:
            field_path, filter_class = item
            if not isinstance(filter_class, type) or not issubclass(filter_class, (FieldListFilter, SimpleListFilter)):
                errors.append(
                    _error(
                        model_admin.__class__,
                        f"The list filter for '{field_path}' does not use a supported filter class.",
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
    for item in getattr(model_admin, option) or ():
        if not isinstance(item, str):
            errors.append(_error(model_admin.__class__, f"Items in '{option}' must be strings.", "E020"))
            continue
        field_path = item
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
    if not field_name:
        return []
    field = _model_field(model_admin, field_name)
    if field is None:
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
    for inline_class in model_admin.inlines or ():
        if not isinstance(inline_class, type) or not issubclass(inline_class, InlineModelAdmin):
            errors.append(_error(model_admin.__class__, "Items in 'inlines' must subclass InlineModelAdmin.", "E031"))
            continue
        inline_model = getattr(inline_class, "model", None)
        if not isinstance(inline_model, ModelBase):
            errors.append(_error(inline_class, "Inline classes must define a concrete model.", "E032"))
            continue
        try:
            _get_foreign_key(model_admin.model, inline_model, fk_name=getattr(inline_class, "fk_name", None))
        except ValueError as exc:
            errors.append(_error(inline_class, str(exc), "E033"))
    return errors
