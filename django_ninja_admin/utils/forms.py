from decimal import Decimal

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.forms.models import ModelChoiceField, ModelMultipleChoiceField, model_to_dict

from django_ninja_admin.utils.format_error import format_error
from django_ninja_admin.utils.lookup import display_metadata_for_field, label_for_field, lookup_field


def file_value_metadata(value):
    name = getattr(value, "name", "") or ""
    if not name:
        return None
    try:
        url = value.url
    except (OSError, ValueError):
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


def _jsonish_value(value):
    if callable(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonish_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonish_value(item) for key, item in value.items()}
    return str(value)


def _relation_metadata(field):
    if not isinstance(field, (ModelChoiceField, ModelMultipleChoiceField)):
        return {}
    model = field.queryset.model
    attrs = {
        "related_model": f"{model._meta.app_label}.{model._meta.model_name}",
        "to_field_name": field.to_field_name or model._meta.pk.name,
        "multiple": isinstance(field, ModelMultipleChoiceField),
    }
    if isinstance(field, ModelChoiceField):
        attrs["empty_label"] = field.empty_label
    return attrs


def _validator_names(field):
    return [validator.__class__.__name__ for validator in getattr(field, "validators", ())]


def _model_field_for_name(model, name):
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
        "blank": bool(getattr(field, "blank", False)),
        "null": bool(getattr(field, "null", False)),
        "editable": bool(getattr(field, "editable", True)),
        "primary_key": bool(getattr(field, "primary_key", False)),
        "unique": bool(getattr(field, "unique", False)),
        "db_index": bool(getattr(field, "db_index", False)),
    }
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
    return attrs


def field_description(name, field, *, read_only=False, current_value=None, model_field=None):
    widget = field.widget
    attrs = {
        "required": field.required,
        "label": field.label or name.replace("_", " ").title(),
        "help_text": str(field.help_text or ""),
        "read_only": read_only,
        "disabled": getattr(field, "disabled", False),
        "widget": widget.__class__.__name__,
        "widget_attrs": _jsonish_value(getattr(widget, "attrs", {})),
        "is_hidden": widget.is_hidden,
        "multiple": getattr(widget, "allow_multiple_selected", False),
        "validators": _validator_names(field),
    }
    attrs.update(_model_field_metadata(model_field))
    if getattr(widget, "input_type", None):
        attrs["input_type"] = widget.input_type
    if hasattr(widget, "needs_multipart_form"):
        attrs["needs_multipart_form"] = widget.needs_multipart_form
    if getattr(field, "choices", None):
        attrs["choices"] = [(_choice_value(value), str(label)) for value, label in field.choices]
    if getattr(field, "initial", None) not in (None, ""):
        initial = _jsonish_value(field.initial)
        if initial is not None:
            attrs["initial"] = initial
    current = _jsonish_value(current_value)
    if current not in (None, ""):
        attrs["value"] = current
    if getattr(field, "max_length", None) is not None:
        attrs["max_length"] = field.max_length
    if getattr(field, "min_length", None) is not None:
        attrs["min_length"] = field.min_length
    if getattr(field, "min_value", None) is not None:
        attrs["min_value"] = _jsonish_value(field.min_value)
    if getattr(field, "max_value", None) is not None:
        attrs["max_value"] = _jsonish_value(field.max_value)
    if getattr(field, "max_digits", None) is not None:
        attrs["max_digits"] = field.max_digits
    if getattr(field, "decimal_places", None) is not None:
        attrs["decimal_places"] = field.decimal_places
    if isinstance(field, forms.FileField):
        attrs["allow_empty_file"] = getattr(field, "allow_empty_file", False)
        if isinstance(field, forms.ImageField):
            attrs["image"] = True
            attrs["accepted_content_types"] = ["image/*"]
            current_file = image_value_metadata(current_value)
        else:
            current_file = file_value_metadata(current_value)
        if current_file is not None:
            attrs["current_file"] = current_file
    attrs.update(_relation_metadata(field))
    return {"name": name, "type": field.__class__.__name__, "attrs": attrs}


def form_field_descriptions(
    form_class,
    *,
    readonly_fields=(),
    instance=None,
    model_admin=None,
    empty_value_display="-",
    autocomplete_fields=(),
    raw_id_fields=(),
    filter_horizontal=(),
    filter_vertical=(),
    radio_fields=None,
    prepopulated_fields=None,
):
    form = form_class(instance=instance)
    model = getattr(getattr(form_class, "_meta", None), "model", None)
    autocomplete_fields = set(autocomplete_fields or ())
    raw_id_fields = set(raw_id_fields or ())
    filter_horizontal = set(filter_horizontal or ())
    filter_vertical = set(filter_vertical or ())
    radio_fields = radio_fields or {}
    prepopulated_fields = prepopulated_fields or {}
    descriptions = []
    for name, field in form.fields.items():
        current_value = form.initial.get(name)
        description = field_description(
            name,
            field,
            read_only=name in readonly_fields,
            current_value=current_value,
            model_field=_model_field_for_name(model, name),
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
        )
        descriptions.append(description)
    for name in readonly_fields:
        if name not in form.fields:
            model_field = _model_field_for_name(model, name)
            display_metadata = display_metadata_for_field(name, model, model_admin)
            readonly_attrs = {
                "required": False,
                "label": label_for_field(name, model, model_admin),
                "help_text": "",
                "read_only": True,
                **_model_field_metadata(model_field),
                **display_metadata,
            }
            if instance is not None:
                value = _readonly_value(name, instance, model_admin, model_field)
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
):
    attrs = description["attrs"]
    if name in autocomplete_fields:
        attrs["admin_widget"] = "autocomplete"
    if name in raw_id_fields:
        attrs["admin_widget"] = "raw_id"
    if name in filter_horizontal:
        attrs["admin_widget"] = "filter_horizontal"
    if name in filter_vertical:
        attrs["admin_widget"] = "filter_vertical"
    if name in radio_fields:
        attrs["admin_widget"] = "radio"
        attrs["radio_orientation"] = radio_fields[name]
    if name in prepopulated_fields:
        attrs["prepopulated_from"] = list(prepopulated_fields[name])


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
