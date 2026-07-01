from decimal import Decimal

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.forms.models import ModelChoiceField, ModelMultipleChoiceField, model_to_dict

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
    attrs = {
        "related_model": f"{opts.app_label}.{opts.model_name}",
        "related_app_label": opts.app_label,
        "related_model_name": opts.model_name,
        "related_object_name": opts.object_name,
        "related_verbose_name": str(opts.verbose_name),
        "related_verbose_name_plural": str(opts.verbose_name_plural),
        "to_field_name": field.to_field_name or model._meta.pk.name,
        "multiple": isinstance(field, ModelMultipleChoiceField),
    }
    if isinstance(field, ModelChoiceField):
        attrs["empty_label"] = field.empty_label
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
        "css": {
            medium: [_media_asset_path(media, asset) for asset in css[medium]]
            for medium in sorted(css)
        },
        "js": [_media_asset_path(media, asset) for asset in media._js],
    }


def _validator_names(field):
    return [validator.__class__.__name__ for validator in getattr(field, "validators", ())]


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


def field_description(name, field, *, read_only=False, current_value=None, model_field=None):
    widget = field.widget
    attrs = {
        "required": field.required,
        "label": field.label or name.replace("_", " ").title(),
        "help_text": str(field.help_text or ""),
        "read_only": read_only,
        "disabled": getattr(field, "disabled", False),
        "validators": _validator_names(field),
        **_widget_metadata(widget),
    }
    attrs.update(_model_field_metadata(model_field))
    subwidgets = _multiwidget_metadata(widget)
    if subwidgets:
        attrs["subwidgets"] = subwidgets
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
    selected_options = _relation_selected_options(field, current_value)
    if selected_options:
        attrs["selected_options"] = selected_options
    return {"name": name, "type": field.__class__.__name__, "attrs": attrs}


def form_field_descriptions(
    form_class,
    *,
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
    form = form_class(instance=instance, initial=initial)
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
):
    attrs = description["attrs"]
    if name in autocomplete_fields:
        attrs["admin_widget"] = "autocomplete"
        if source_model is not None:
            attrs["autocomplete"] = {
                "app_label": source_model._meta.app_label,
                "model_name": source_model._meta.model_name,
                "field_name": name,
            }
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
