from typing import Any, cast

from django import forms


def payload_data(payload, *, exclude_unset=True):
    data = cast(Any, getattr(payload, "data", {}))
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="python", exclude_unset=exclude_unset)
    return data


def payload_inlines(payload):
    inlines = cast(Any, getattr(payload, "inlines", None))
    if hasattr(inlines, "model_dump"):
        return inlines.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
    return inlines


def normalize_form_data(form_class, data):
    normalized = dict(data)
    for field_name, field in form_class.base_fields.items():
        if field_name in normalized:
            normalized[field_name] = normalize_form_value(field, normalized[field_name])
        if isinstance(field, forms.FileField) and field_name in normalized and normalized[field_name] is None:
            normalized.pop(field_name)
            normalized[f"{field_name}-clear"] = "on"
        if isinstance(field, forms.MultiValueField) and field_name in normalized:
            expand_multivalue_form_data(normalized, field_name, field)
    return normalized


def normalize_form_value(field, value):
    if value is None:
        return value
    if isinstance(field, (forms.URLField, forms.GenericIPAddressField, forms.UUIDField)) and not isinstance(
        value,
        str,
    ):
        return str(value)
    return value


def expand_multivalue_form_data(data, field_name, field):
    value = data[field_name]
    values = None
    if value is None:
        values = [""] * len(field.fields)
    elif isinstance(value, (list, tuple)):
        values = value
    elif hasattr(field.widget, "decompress"):
        try:
            values = field.widget.decompress(value)
        except (AttributeError, TypeError, ValueError):
            values = None
    if values is None:
        return
    data.pop(field_name, None)
    for index, item in enumerate(values):
        data[f"{field_name}_{index}"] = item


def copy_form_row(formset_data, prefix, index, row, form_fields):
    for name, value in row.items():
        if name in {"pk", "id"} or name not in form_fields:
            continue
        field = form_fields[name]
        value = normalize_form_value(field, value)
        if isinstance(field, forms.FileField) and value is None:
            formset_data[f"{prefix}-{index}-{name}-clear"] = "on"
            continue
        if isinstance(field, forms.MultiValueField):
            expanded = {name: value}
            expand_multivalue_form_data(expanded, name, field)
            for expanded_name, expanded_value in expanded.items():
                formset_data[f"{prefix}-{index}-{expanded_name}"] = expanded_value
            continue
        formset_data[f"{prefix}-{index}-{name}"] = value
