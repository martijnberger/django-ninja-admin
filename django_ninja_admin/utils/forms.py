from decimal import Decimal

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.core.validators import (
    FileExtensionValidator,
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    StepValueValidator,
)
from django.db import models
from django.forms.models import ModelChoiceField, ModelMultipleChoiceField, model_to_dict
from django.utils.functional import Promise

from django_ninja_admin.utils.format_error import format_error
from django_ninja_admin.utils.lookup import (
    display_metadata_for_field,
    field_name_for_display,
    label_for_field,
    lookup_field,
)


def file_value_metadata(value):
    name = getattr(value, "name", "") or ""
    if not name:
        return None
    try:
        url = value.url
    except (NotImplementedError, OSError, ValueError):
        url = None
    return {"name": name, "url": url}


def image_value_metadata(value):
    metadata = file_value_metadata(value)
    if metadata is None:
        return None
    for dimension in ("width", "height"):
        try:
            metadata[dimension] = getattr(value, dimension)
        except Exception:
            metadata[dimension] = None
    return metadata


def model_data_for_form(instance, fields):
    data = model_to_dict(instance, fields=fields)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = str(value)
        elif hasattr(value, "name") and hasattr(value, "storage"):
            data[key] = value.name or ""
        elif isinstance(value, list):
            data[key] = [item.pk if hasattr(item, "pk") else item for item in value]
    return data


def _choice_value(value):
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else None


def _choice_option(value, label, *, coerce=None):
    raw = getattr(value, "value", value)
    option = {"value": _choice_value(value), "raw_value": _jsonish_value(raw), "label": str(label)}
    if coerce is not None:
        try:
            option["coerced_value"] = _jsonish_value(coerce(raw))
        except (TypeError, ValueError):
            pass
    return option


def _choice_metadata(choices, *, coerce=None):
    flat_choices = []
    choice_options = []
    choice_groups = []
    ungrouped_options = []

    def add_flat(option):
        flat_choices.append((option["value"], option["label"]))
        choice_options.append(option)

    def flush_ungrouped():
        nonlocal ungrouped_options
        if ungrouped_options:
            choice_groups.append({"label": None, "options": ungrouped_options})
            ungrouped_options = []

    for value, label in choices:
        if isinstance(label, (list, tuple)):
            flush_ungrouped()
            options = [_choice_option(child_value, child_label, coerce=coerce) for child_value, child_label in label]
            for option in options:
                add_flat(option)
            choice_groups.append({"label": str(value), "options": options})
            continue
        option = _choice_option(value, label, coerce=coerce)
        add_flat(option)
        ungrouped_options.append(option)
    flush_ungrouped()
    if len(choice_groups) > 1 or any(group["label"] for group in choice_groups):
        return flat_choices, choice_options, choice_groups
    return flat_choices, choice_options, []


def _jsonish_value(value):
    if isinstance(value, Promise):
        return str(value)
    if callable(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Q):
        return {
            "connector": value.connector,
            "negated": value.negated,
            "children": [_jsonish_q_child(child) for child in value.children],
        }
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonish_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonish_value(item) for key, item in value.items()}
    return str(value)


def _jsonish_q_child(child):
    if isinstance(child, tuple) and len(child) == 2 and isinstance(child[0], str):
        return {"lookup": child[0], "value": _jsonish_value(child[1])}
    return _jsonish_value(child)


def _relation_metadata(field):
    if not isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
        return {}
    model = field.queryset.model
    opts = model._meta
    to_field_name = field.to_field_name or model._meta.pk.name
    attrs = {
        "related_model": f"{opts.app_label}.{opts.model_name}",
        "related_app_label": opts.app_label,
        "related_model_name": opts.model_name,
        "related_object_name": opts.object_name,
        "related_verbose_name": str(opts.verbose_name),
        "related_verbose_name_plural": str(opts.verbose_name_plural),
        "to_field_name": to_field_name,
        **_relation_target_field_metadata(model, to_field_name),
        "multiple": isinstance(field, ModelMultipleChoiceField),
    }
    if isinstance(field, ModelChoiceField):
        attrs["empty_label"] = _jsonish_value(field.empty_label)
    return attrs


def _relation_selected_options(field, current_value):
    if not isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
        return []
    if current_value in (None, ""):
        return []
    values = current_value if isinstance(field, ModelMultipleChoiceField) else [current_value]
    values = list(values)
    if not values:
        return []

    model = field.queryset.model
    lookup_field = field.to_field_name or model._meta.pk.name
    objects_by_value = {}
    unresolved = []
    for value in values:
        if hasattr(value, "_meta"):
            option_value = getattr(value, lookup_field)
            objects_by_value[str(option_value)] = value
        else:
            unresolved.append(value)
    if unresolved:
        objects_by_value.update(
            {
                str(getattr(obj, lookup_field)): obj
                for obj in field.queryset.filter(**{f"{lookup_field}__in": unresolved})
            }
        )

    selected = []
    for value in values:
        option_value = getattr(value, lookup_field) if hasattr(value, "_meta") else value
        obj = objects_by_value.get(str(option_value))
        if obj is not None:
            selected.append({"id": str(option_value), "text": str(obj)})
    return selected


def _media_asset_path(media, asset):
    if hasattr(asset, "path"):
        return str(asset.path)
    return media.absolute_path(str(asset))


def form_media_description(form):
    media = form.media
    css = media._css
    return {
        "css": {medium: [_media_asset_path(media, asset) for asset in css[medium]] for medium in sorted(css)},
        "js": [_media_asset_path(media, asset) for asset in media._js],
    }


def fieldset_layout_description(fieldsets):
    return [
        {
            "name": str(name) if name is not None else None,
            "classes": [str(class_name) for class_name in _fieldset_classes(options.get("classes", ()))],
            "description": str(options["description"]) if options.get("description") is not None else None,
            "fields": [field for row in _fieldset_rows(options.get("fields", ())) for field in row["fields"]],
            "rows": _fieldset_rows(options.get("fields", ())),
        }
        for name, options in fieldsets
    ]


def _fieldset_classes(classes):
    if classes in (None, ""):
        return []
    if isinstance(classes, str):
        return [classes]
    return list(classes)


def _fieldset_rows(fields):
    rows = []
    for item in fields:
        row_fields = item if isinstance(item, (list, tuple)) else (item,)
        rows.append({"fields": [field_name_for_display(field) for field in row_fields]})
    return rows


def _validator_names(field):
    return [validator.__class__.__name__ for validator in getattr(field, "validators", ())]


def _validator_details(field):
    details = []
    for validator in getattr(field, "validators", ()):
        detail = {"class": validator.__class__.__name__}
        for attr_name in ("code", "message", "limit_value"):
            value = _jsonish_value(getattr(validator, attr_name, None))
            if value is not None:
                detail[attr_name] = value
        regex = getattr(validator, "regex", None)
        pattern = getattr(regex, "pattern", regex)
        if isinstance(pattern, str):
            detail["pattern"] = pattern
        details.append(detail)
    return details


def _validator_limit_value(validator):
    value = getattr(validator, "limit_value", None)
    if callable(value):
        try:
            return value()
        except Exception:
            return None
    return value


def _string_length_bounds(field):
    min_length = getattr(field, "min_length", None)
    max_length = getattr(field, "max_length", None)
    for validator in getattr(field, "validators", ()):
        limit_value = _validator_limit_value(validator)
        if limit_value is None:
            continue
        if isinstance(validator, MinLengthValidator):
            min_length = max(min_length if min_length is not None else limit_value, limit_value)
        elif isinstance(validator, MaxLengthValidator):
            max_length = min(max_length if max_length is not None else limit_value, limit_value)
    return min_length, max_length


def _numeric_bounds(field):
    min_value = getattr(field, "min_value", None)
    max_value = getattr(field, "max_value", None)
    for validator in getattr(field, "validators", ()):
        limit_value = _validator_limit_value(validator)
        if limit_value is None:
            continue
        if isinstance(validator, MinValueValidator):
            min_value = max(min_value if min_value is not None else limit_value, limit_value)
        elif isinstance(validator, MaxValueValidator):
            max_value = min(max_value if max_value is not None else limit_value, limit_value)
    return min_value, max_value


def _model_field_for_name(model, name):
    if not isinstance(name, str):
        return None
    if model is None:
        return None
    try:
        return model._meta.get_field(name)
    except FieldDoesNotExist:
        return None


def _model_field_metadata(field):
    if field is None:
        return {}
    attrs = {
        "model_field_name": field.name,
        "model_field_class": field.__class__.__name__,
        "internal_type": field.get_internal_type() if hasattr(field, "get_internal_type") else field.__class__.__name__,
        "blank": bool(getattr(field, "blank", False)),
        "null": bool(getattr(field, "null", False)),
        "editable": bool(getattr(field, "editable", True)),
        "primary_key": bool(getattr(field, "primary_key", False)),
        "unique": bool(getattr(field, "unique", False)),
        "db_index": bool(getattr(field, "db_index", False)),
    }
    if getattr(field, "attname", None):
        attrs["attname"] = field.attname
    if getattr(field, "column", None):
        attrs["column"] = field.column
    if getattr(field, "default", None) is not None and field.default is not models.NOT_PROVIDED:
        default = _jsonish_value(field.default)
        if default is not None:
            attrs["default"] = default
    if isinstance(field, models.FileField):
        attrs["upload_to"] = str(getattr(field, "upload_to", ""))
    if isinstance(field, models.ImageField):
        attrs["image"] = True
        attrs["width_field"] = getattr(field, "width_field", None) or None
        attrs["height_field"] = getattr(field, "height_field", None) or None
    if hasattr(field, "get_limit_choices_to"):
        limit_choices_to = _jsonish_value(field.get_limit_choices_to())
        if limit_choices_to not in (None, {}, []):
            attrs["limit_choices_to"] = limit_choices_to
    return attrs


def _widget_metadata(widget):
    metadata = {
        "widget": widget.__class__.__name__,
        "widget_attrs": _jsonish_value(getattr(widget, "attrs", {})),
        "is_hidden": widget.is_hidden,
        "is_localized": bool(getattr(widget, "is_localized", False)),
        "multiple": getattr(widget, "allow_multiple_selected", False),
    }
    if getattr(widget, "template_name", None):
        metadata["template_name"] = widget.template_name
    if getattr(widget, "use_fieldset", False):
        metadata["use_fieldset"] = True
    if getattr(widget, "input_type", None):
        metadata["input_type"] = widget.input_type
    if getattr(widget, "format", None):
        metadata["format"] = widget.format
    if hasattr(widget, "needs_multipart_form"):
        metadata["needs_multipart_form"] = widget.needs_multipart_form
    if getattr(widget, "option_template_name", None):
        metadata["option_template_name"] = widget.option_template_name
    if hasattr(widget, "add_id_index"):
        metadata["add_id_index"] = bool(widget.add_id_index)
    checked_attribute = getattr(widget, "checked_attribute", None)
    if checked_attribute:
        metadata["checked_attribute"] = _jsonish_value(checked_attribute)
    if getattr(widget, "supports_microseconds", True) is False:
        metadata["supports_microseconds"] = False
    return metadata


def _multiwidget_metadata(widget):
    widgets = getattr(widget, "widgets", None)
    if not widgets:
        return []
    widget_names = getattr(widget, "widgets_names", [f"_{index}" for index, _item in enumerate(widgets)])
    return [
        {"name_suffix": name_suffix, **_widget_metadata(subwidget)}
        for name_suffix, subwidget in zip(widget_names, widgets, strict=False)
    ]


def _select_date_metadata(name, field, current_value):
    widget = field.widget
    if not isinstance(widget, forms.SelectDateWidget):
        return {}
    order = list(widget._parse_date_fmt()) or ["month", "day", "year"]
    select_date = {
        "order": order,
        "field_names": {
            "year": widget.year_field % name,
            "month": widget.month_field % name,
            "day": widget.day_field % name,
        },
        "years": [_jsonish_value(year) for year in widget.years],
        "months": [{"value": _jsonish_value(value), "label": str(label)} for value, label in widget.months.items()],
        "days": list(range(1, 32)),
        "empty_choices": {
            "year": {"value": _jsonish_value(widget.year_none_value[0]), "label": str(widget.year_none_value[1])},
            "month": {"value": _jsonish_value(widget.month_none_value[0]), "label": str(widget.month_none_value[1])},
            "day": {"value": _jsonish_value(widget.day_none_value[0]), "label": str(widget.day_none_value[1])},
        },
    }
    if current_value not in (None, ""):
        selected = {
            key: _jsonish_value(value)
            for key, value in widget.format_value(current_value).items()
            if value not in (None, "")
        }
        if selected:
            select_date["selected"] = selected
    return {"select_date": select_date}


def _input_formats(field):
    input_formats = getattr(field, "input_formats", None)
    if input_formats is not None:
        return [str(item) for item in input_formats]
    fields = getattr(field, "fields", None)
    if not fields:
        return []
    return [
        {
            "index": index,
            "input_formats": [str(item) for item in getattr(subfield, "input_formats", ())],
        }
        for index, subfield in enumerate(fields)
        if getattr(subfield, "input_formats", None) is not None
    ]


def _filepath_metadata(field):
    if not isinstance(field, forms.FilePathField):
        return {}
    attrs = {
        "path": _jsonish_value(getattr(field, "path", None)),
        "recursive": bool(getattr(field, "recursive", False)),
        "allow_files": bool(getattr(field, "allow_files", True)),
        "allow_folders": bool(getattr(field, "allow_folders", False)),
    }
    match = _jsonish_value(getattr(field, "match", None))
    if match not in (None, ""):
        attrs["match"] = match
    return {key: value for key, value in attrs.items() if value is not None}


def _combo_metadata(field):
    if not isinstance(field, forms.ComboField):
        return {}
    return {
        "combo_fields": [
            {
                "index": index,
                "type": description["type"],
                "attrs": description["attrs"],
            }
            for index, subfield in enumerate(field.fields)
            for description in [field_description(str(index), subfield)]
        ]
    }


def _step_metadata(field):
    if getattr(field, "step_size", None) is None:
        return {}
    attrs = {"step_size": _jsonish_value(field.step_size)}
    for validator in getattr(field, "validators", ()):
        if isinstance(validator, StepValueValidator) and getattr(validator, "offset", None) is not None:
            attrs["step_offset"] = _jsonish_value(validator.offset)
            break
    return attrs


def _file_upload_metadata(field):
    if not isinstance(field, forms.FileField):
        return {}
    attrs = {"allow_empty_file": getattr(field, "allow_empty_file", False)}
    allowed_extensions = []
    for validator in getattr(field, "validators", ()):
        if not isinstance(validator, FileExtensionValidator):
            continue
        for extension in getattr(validator, "allowed_extensions", ()) or ():
            extension = str(extension).lstrip(".").lower()
            if extension and extension not in allowed_extensions:
                allowed_extensions.append(extension)
    if allowed_extensions:
        attrs["allowed_extensions"] = allowed_extensions
        attrs["accepted_extensions"] = [f".{extension}" for extension in allowed_extensions]
    return attrs


def _clearable_file_widget_metadata(name, widget, *, bound_field=None):
    if not isinstance(widget, forms.ClearableFileInput):
        return {}
    html_name = bound_field.html_name if bound_field is not None else name
    return {
        "clearable_file_input": True,
        "initial_text": str(widget.initial_text),
        "input_text": str(widget.input_text),
        "clear_checkbox_label": str(widget.clear_checkbox_label),
        "clear_checkbox_name": widget.clear_checkbox_name(html_name),
        "clear_checkbox_id": widget.clear_checkbox_id(html_name),
    }


def _bound_field_metadata(bound_field):
    if bound_field is None:
        return {}
    attrs = {
        "html_name": bound_field.html_name,
        "auto_id": bound_field.auto_id,
        "id_for_label": bound_field.id_for_label,
        "aria_describedby": bound_field.aria_describedby,
    }
    if getattr(bound_field.form, "prefix", None):
        attrs["form_prefix"] = bound_field.form.prefix
    css_classes = bound_field.css_classes()
    if css_classes:
        attrs["css_classes"] = css_classes
    if getattr(bound_field.field, "show_hidden_initial", False):
        attrs["html_initial_name"] = bound_field.html_initial_name
        attrs["html_initial_id"] = bound_field.html_initial_id
    return {key: value for key, value in attrs.items() if value not in (None, "")}


def _rendered_widget_attrs(bound_field):
    if bound_field is None:
        return {}
    widget = bound_field.field.widget
    try:
        attrs = {}
        if bound_field.auto_id and "id" not in getattr(widget, "attrs", {}):
            attrs["id"] = bound_field.auto_id
        render_attrs = bound_field.build_widget_attrs(attrs, widget)
        return _jsonish_value(widget.build_attrs(getattr(widget, "attrs", {}), render_attrs))
    except Exception:
        return {}


def _bound_subwidget_metadata(bound_field):
    if bound_field is None:
        return []
    widget = bound_field.field.widget
    if not getattr(bound_field.field, "choices", None) and not getattr(widget, "choices", None):
        return []
    subwidgets = []
    for subwidget in bound_field.subwidgets:
        data = subwidget.data
        item = {
            "name": data.get("name"),
            "value": _jsonish_value(data.get("value")),
            "label": str(data.get("label", "")),
            "selected": bool(data.get("selected", False)),
            "index": str(data.get("index", "")),
            "attrs": _jsonish_value(data.get("attrs", {})),
        }
        for key in ("type", "template_name", "wrap_label"):
            if key in data:
                item[key] = _jsonish_value(data[key])
        if subwidget.id_for_label:
            item["id_for_label"] = subwidget.id_for_label
        subwidgets.append({key: value for key, value in item.items() if value not in (None, "")})
    return subwidgets


def _rendered_optgroups_metadata(bound_field):
    if bound_field is None:
        return []
    widget = bound_field.field.widget
    if not getattr(bound_field.field, "choices", None) and not getattr(widget, "choices", None):
        return []
    if not hasattr(widget, "optgroups"):
        return []
    try:
        attrs = {}
        if bound_field.auto_id:
            attrs["id"] = bound_field.auto_id
        value = widget.format_value(bound_field.value())
        optgroups = widget.optgroups(bound_field.html_name, value, bound_field.build_widget_attrs(attrs, widget))
    except Exception:
        return []

    groups = []
    for group_name, options, group_index in optgroups:
        if group_name is None:
            continue
        group_options = []
        for option in options:
            item = {
                "name": option.get("name"),
                "value": _jsonish_value(option.get("value")),
                "label": str(option.get("label", "")),
                "selected": bool(option.get("selected", False)),
                "index": str(option.get("index", "")),
                "attrs": _jsonish_value(option.get("attrs", {})),
            }
            for key in ("type", "template_name", "wrap_label"):
                if key in option:
                    item[key] = _jsonish_value(option[key])
            group_options.append({key: value for key, value in item.items() if value not in (None, "")})
        if group_options:
            groups.append(
                {
                    "label": str(group_name),
                    "index": _jsonish_value(group_index),
                    "options": group_options,
                }
            )
    return groups


def _rendered_subwidgets_metadata(bound_field):
    if bound_field is None:
        return []
    try:
        bound_widgets = list(bound_field.subwidgets)
    except Exception:
        return []
    rendered = []
    for bound_widget in bound_widgets:
        for index, subwidget in enumerate(bound_widget.data.get("subwidgets") or []):
            attrs = _jsonish_value(subwidget.get("attrs", {}))
            item = {
                "index": index,
                "name": subwidget.get("name"),
                "value": _jsonish_value(subwidget.get("value")),
                "attrs": attrs,
                "is_hidden": bool(subwidget.get("is_hidden", False)),
                "required": bool(subwidget.get("required", False)),
            }
            if isinstance(attrs, dict) and attrs.get("id") not in (None, ""):
                item["auto_id"] = str(attrs["id"])
                item["id_for_label"] = str(attrs["id"])
            for key in ("type", "template_name"):
                if key in subwidget:
                    item[key] = _jsonish_value(subwidget[key])
            rendered.append({key: value for key, value in item.items() if value not in (None, "")})
    return rendered


def _hidden_initial_metadata(name, field, *, bound_field=None):
    if not getattr(field, "show_hidden_initial", False):
        return {}
    hidden_initial_name = (
        bound_field.html_initial_name
        if bound_field is not None and bound_field.html_initial_name
        else f"initial-{name}"
    )
    hidden_widget = field.hidden_widget()
    attrs = {
        "show_hidden_initial": True,
        "hidden_initial_name": hidden_initial_name,
        "hidden_initial_widget": _widget_metadata(hidden_widget),
    }
    if bound_field is not None and bound_field.html_initial_id:
        attrs["hidden_initial_id"] = bound_field.html_initial_id
    return attrs


def field_description(name, field, *, read_only=False, current_value=None, model_field=None, bound_field=None):
    widget = field.widget
    attrs = {
        "required": field.required,
        "label": str(field.label) if field.label else name.replace("_", " ").title(),
        "help_text": str(field.help_text or ""),
        "read_only": read_only,
        "disabled": getattr(field, "disabled", False),
        "localize": bool(getattr(field, "localize", False)),
        "validators": _validator_names(field),
        **_widget_metadata(widget),
    }
    attrs.update(_bound_field_metadata(bound_field))
    rendered_attrs = _rendered_widget_attrs(bound_field)
    if rendered_attrs:
        attrs["rendered_attrs"] = rendered_attrs
    bound_subwidgets = _bound_subwidget_metadata(bound_field)
    if bound_subwidgets:
        attrs["bound_subwidgets"] = bound_subwidgets
    rendered_optgroups = _rendered_optgroups_metadata(bound_field)
    if rendered_optgroups:
        attrs["rendered_optgroups"] = rendered_optgroups
    rendered_subwidgets = _rendered_subwidgets_metadata(bound_field)
    if rendered_subwidgets:
        attrs["rendered_subwidgets"] = rendered_subwidgets
    attrs.update(_hidden_initial_metadata(name, field, bound_field=bound_field))
    if getattr(field, "error_messages", None):
        attrs["error_messages"] = _jsonish_value(field.error_messages)
    if isinstance(field, forms.NullBooleanField):
        attrs["null_boolean"] = True
    validator_details = _validator_details(field)
    if validator_details:
        attrs["validator_details"] = validator_details
    attrs.update(_model_field_metadata(model_field))
    subwidgets = _multiwidget_metadata(widget)
    if subwidgets:
        attrs["subwidgets"] = subwidgets
    attrs.update(_select_date_metadata(name, field, current_value))
    input_formats = _input_formats(field)
    if input_formats:
        attrs["input_formats"] = input_formats
    if getattr(field, "choices", None):
        choice_coerce = getattr(field, "coerce", None)
        choices, choice_options, choice_groups = _choice_metadata(field.choices, coerce=choice_coerce)
        attrs["choices"] = choices
        attrs["choice_options"] = choice_options
        if choice_coerce is not None:
            attrs["choice_coerce"] = getattr(choice_coerce, "__name__", str(choice_coerce))
        if choice_groups:
            attrs["choice_groups"] = choice_groups
    attrs.update(_filepath_metadata(field))
    attrs.update(_combo_metadata(field))
    if getattr(field, "initial", None) not in (None, ""):
        initial = _jsonish_value(field.initial)
        if initial is not None:
            attrs["initial"] = initial
    current = _jsonish_value(current_value)
    if current not in (None, ""):
        attrs["value"] = current
    min_length, max_length = _string_length_bounds(field)
    if max_length is not None:
        attrs["max_length"] = max_length
    if min_length is not None:
        attrs["min_length"] = min_length
    if hasattr(field, "strip"):
        attrs["strip"] = bool(field.strip)
    if hasattr(field, "empty_value"):
        attrs["empty_value"] = _jsonish_value(field.empty_value)
    min_value, max_value = _numeric_bounds(field)
    if min_value is not None:
        attrs["min_value"] = _jsonish_value(min_value)
    if max_value is not None:
        attrs["max_value"] = _jsonish_value(max_value)
    attrs.update(_step_metadata(field))
    if getattr(field, "max_digits", None) is not None:
        attrs["max_digits"] = field.max_digits
    if getattr(field, "decimal_places", None) is not None:
        attrs["decimal_places"] = field.decimal_places
    if isinstance(field, forms.FileField):
        attrs.update(_file_upload_metadata(field))
        attrs.update(_clearable_file_widget_metadata(name, field.widget, bound_field=bound_field))
        if isinstance(field, forms.ImageField):
            attrs["image"] = True
            attrs["accepted_content_types"] = ["image/*"]
            current_file = image_value_metadata(current_value)
        else:
            current_file = file_value_metadata(current_value)
        if current_file is not None:
            attrs["current_file"] = current_file
    attrs.update(_relation_metadata(field))
    selected_options = _relation_selected_options(field, current_value)
    if selected_options:
        attrs["selected_options"] = selected_options
    return {"name": name, "type": field.__class__.__name__, "attrs": attrs}


def form_field_descriptions(
    form_class,
    *,
    request=None,
    form=None,
    readonly_fields=(),
    instance=None,
    initial=None,
    model_admin=None,
    empty_value_display="-",
    autocomplete_fields=(),
    raw_id_fields=(),
    filter_horizontal=(),
    filter_vertical=(),
    radio_fields=None,
    prepopulated_fields=None,
):
    if form is None:
        form = form_class(instance=instance, initial=initial)
    model = getattr(getattr(form, "_meta", None), "model", None)
    if model is None:
        model = getattr(getattr(form_class, "_meta", None), "model", None)
    autocomplete_fields = set(autocomplete_fields or ())
    raw_id_fields = set(raw_id_fields or ())
    filter_horizontal = set(filter_horizontal or ())
    filter_vertical = set(filter_vertical or ())
    radio_fields = radio_fields or {}
    prepopulated_fields = prepopulated_fields or {}
    readonly_field_names = {field_name_for_display(field) for field in readonly_fields}
    descriptions = []
    for name, field in form.fields.items():
        current_value = form.initial.get(name)
        description = field_description(
            name,
            field,
            read_only=name in readonly_field_names,
            current_value=current_value,
            model_field=_model_field_for_name(model, name),
            bound_field=form[name],
        )
        _apply_admin_field_metadata(
            description,
            name,
            autocomplete_fields=autocomplete_fields,
            raw_id_fields=raw_id_fields,
            filter_horizontal=filter_horizontal,
            filter_vertical=filter_vertical,
            radio_fields=radio_fields,
            prepopulated_fields=prepopulated_fields,
            source_model=model,
            request=request,
            model_admin=model_admin,
        )
        descriptions.append(description)
    for readonly_field in readonly_fields:
        name = field_name_for_display(readonly_field)
        if name not in form.fields:
            model_field = _model_field_for_name(model, readonly_field)
            display_metadata = display_metadata_for_field(readonly_field, model, model_admin)
            readonly_attrs = {
                "required": False,
                "label": label_for_field(readonly_field, model, model_admin),
                "help_text": "",
                "read_only": True,
                **_model_field_metadata(model_field),
                **display_metadata,
            }
            if getattr(form, "prefix", None):
                readonly_attrs["form_prefix"] = form.prefix
            if instance is not None:
                value = _readonly_value(readonly_field, instance, model_admin, model_field)
                field_empty_value = display_metadata["empty_value_display"] or empty_value_display
                readonly_attrs["value"] = field_empty_value if value in (None, "") else value
            description = {
                "name": name,
                "type": "ReadonlyField",
                "attrs": readonly_attrs,
            }
            _apply_admin_field_metadata(
                description,
                name,
                autocomplete_fields=autocomplete_fields,
                raw_id_fields=raw_id_fields,
                filter_horizontal=filter_horizontal,
                filter_vertical=filter_vertical,
                radio_fields=radio_fields,
                prepopulated_fields=prepopulated_fields,
                source_model=model,
                request=request,
                model_admin=model_admin,
            )
            descriptions.append(description)
    return descriptions


def _readonly_value(name, instance, model_admin, model_field):
    if model_field is not None and isinstance(model_field, models.ImageField):
        return image_value_metadata(getattr(instance, name))
    if model_field is not None and isinstance(model_field, models.FileField):
        return file_value_metadata(getattr(instance, name))
    return _jsonish_value(lookup_field(name, instance, model_admin))


def _apply_admin_field_metadata(
    description,
    name,
    *,
    autocomplete_fields,
    raw_id_fields,
    filter_horizontal,
    filter_vertical,
    radio_fields,
    prepopulated_fields,
    source_model=None,
    request=None,
    model_admin=None,
):
    attrs = description["attrs"]
    if name in autocomplete_fields:
        attrs["admin_widget"] = "autocomplete"
        if source_model is not None:
            attrs["autocomplete"] = _relation_widget_metadata(
                source_model,
                name,
                widget="autocomplete",
                request=request,
                model_admin=model_admin,
            )
    if name in raw_id_fields:
        attrs["admin_widget"] = "raw_id"
        if source_model is not None:
            attrs["raw_id"] = _relation_widget_metadata(
                source_model,
                name,
                widget="raw_id",
                request=request,
                model_admin=model_admin,
            )
    if name in filter_horizontal:
        attrs["admin_widget"] = "filter_horizontal"
        if source_model is not None:
            attrs["filtered_select"] = _filtered_select_metadata(source_model, name, direction="horizontal")
    if name in filter_vertical:
        attrs["admin_widget"] = "filter_vertical"
        if source_model is not None:
            attrs["filtered_select"] = _filtered_select_metadata(source_model, name, direction="vertical")
    if name in radio_fields:
        attrs["admin_widget"] = "radio"
        attrs["radio_orientation"] = radio_fields[name]
        attrs["radio"] = {
            **_source_field_identity(source_model, name),
            "orientation": radio_fields[name],
        }
    if name in prepopulated_fields:
        source_names = list(prepopulated_fields[name])
        attrs["prepopulated_from"] = source_names
        attrs["prepopulated"] = {
            **_source_field_identity(source_model, name),
            "sources": [_prepopulated_source_metadata(source_model, source_name) for source_name in source_names],
        }


def _source_field_identity(source_model, field_name):
    if source_model is None:
        return {"field_name": field_name}
    return {
        "app_label": source_model._meta.app_label,
        "model_name": source_model._meta.model_name,
        "field_name": field_name,
    }


def _relation_widget_metadata(source_model, field_name, *, widget, request=None, model_admin=None):
    metadata = _source_field_identity(source_model, field_name)
    source_field = _model_field_for_name(source_model, field_name)
    remote_model = getattr(getattr(source_field, "remote_field", None), "model", None)
    to_field_name = None
    if remote_model is not None:
        remote_opts = remote_model._meta
        to_field_name = _relation_to_field_name(source_field, remote_model)
        metadata.update(
            {
                "related_model": f"{remote_opts.app_label}.{remote_opts.model_name}",
                "related_app_label": remote_opts.app_label,
                "related_model_name": remote_opts.model_name,
                "related_object_name": remote_opts.object_name,
                "related_verbose_name": str(remote_opts.verbose_name),
                "related_verbose_name_plural": str(remote_opts.verbose_name_plural),
                "to_field_name": to_field_name,
                **_relation_target_field_metadata(remote_model, to_field_name),
                "multiple": bool(getattr(source_field, "many_to_many", False)),
            }
        )

    base_path = _admin_mount_path(request, source_model, model_admin=model_admin)
    if base_path is None:
        return metadata
    if widget == "autocomplete":
        metadata["url"] = f"{base_path}/autocomplete"
        metadata["query"] = _source_field_identity(source_model, field_name)
    elif widget == "raw_id" and remote_model is not None:
        metadata["url"] = f"{base_path}/{remote_model._meta.app_label}/{remote_model._meta.model_name}"
        if to_field_name is not None:
            metadata["query"] = {"_to_field": to_field_name}
    return metadata


def _relation_to_field_name(source_field, remote_model):
    remote_field = None
    remote_relation = getattr(source_field, "remote_field", None)
    if hasattr(remote_relation, "get_related_field"):
        try:
            remote_field = remote_relation.get_related_field()
        except (AttributeError, FieldDoesNotExist, TypeError, ValueError):
            remote_field = None
    if remote_field is None:
        remote_field = remote_model._meta.pk
    return getattr(remote_field, "attname", remote_field.name)


def _relation_target_field_metadata(model, to_field_name):
    try:
        field = model._meta.get_field(to_field_name)
    except FieldDoesNotExist:
        return {}
    metadata = {
        "to_field_class": field.__class__.__name__,
        "to_field_internal_type": (
            field.get_internal_type() if hasattr(field, "get_internal_type") else field.__class__.__name__
        ),
    }
    if getattr(field, "attname", None):
        metadata["to_field_attname"] = field.attname
    return metadata


def _admin_mount_path(request, source_model, *, model_admin=None):
    path = getattr(request, "path", None) or getattr(request, "path_info", None)
    if not path:
        return None
    for candidate_model in _mount_path_model_candidates(source_model, model_admin):
        marker = f"/{candidate_model._meta.app_label}/{candidate_model._meta.model_name}"
        index = path.find(marker)
        if index >= 0:
            return path[:index].rstrip("/")
    return None


def _mount_path_model_candidates(source_model, model_admin):
    seen = set()
    for candidate_model in (
        source_model,
        getattr(model_admin, "parent_model", None),
        getattr(model_admin, "model", None),
    ):
        if candidate_model is None or id(candidate_model) in seen:
            continue
        seen.add(id(candidate_model))
        yield candidate_model


def _filtered_select_metadata(source_model, field_name, *, direction):
    metadata = {
        **_source_field_identity(source_model, field_name),
        "direction": direction,
        "is_stacked": direction == "vertical",
    }
    field = _model_field_for_name(source_model, field_name)
    if field is not None:
        metadata["verbose_name"] = str(getattr(field, "verbose_name", field_name))
        remote_model = getattr(getattr(field, "remote_field", None), "model", None)
        if remote_model is not None:
            remote_opts = remote_model._meta
            to_field_name = _relation_to_field_name(field, remote_model)
            metadata.update(
                {
                    "related_model": f"{remote_opts.app_label}.{remote_opts.model_name}",
                    "related_app_label": remote_opts.app_label,
                    "related_model_name": remote_opts.model_name,
                    "related_verbose_name": str(remote_opts.verbose_name),
                    "related_verbose_name_plural": str(remote_opts.verbose_name_plural),
                    "to_field_name": to_field_name,
                    **_relation_target_field_metadata(remote_model, to_field_name),
                }
            )
    return metadata


def _prepopulated_source_metadata(source_model, field_name):
    metadata = {"field_name": field_name}
    field = _model_field_for_name(source_model, field_name)
    if field is not None:
        metadata["label"] = str(field.verbose_name)
        metadata["internal_type"] = (
            field.get_internal_type() if hasattr(field, "get_internal_type") else field.__class__.__name__
        )
    return metadata


def form_errors(form):
    return format_error(form.errors)


def formset_errors(formset):
    return {
        "forms": [format_error(errors) for errors in formset.errors],
        "non_form_errors": format_error(formset.non_form_errors()),
    }


class RequestDataFormMixin:
    def clean(self):
        cleaned = super().clean()
        return cleaned
