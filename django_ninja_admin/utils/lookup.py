from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db.models import Model


def model_field_from_path(model, field_path):
    opts = model._meta
    path_parts = field_path.split("__")
    for index, path_part in enumerate(path_parts):
        if path_part == "pk":
            path_part = opts.pk.name
        field = opts.get_field(path_part)
        has_more_parts = index < len(path_parts) - 1
        if has_more_parts and hasattr(field, "path_infos"):
            opts = field.path_infos[-1].to_opts
        elif has_more_parts:
            raise FieldDoesNotExist(field_path)
    return field


def field_name_for_display(name):
    if isinstance(name, str):
        return name
    return getattr(name, "__name__", name.__class__.__name__)


def display_attr_for_field(name, model, model_admin=None):
    if not isinstance(name, str) and callable(name):
        return name
    if model_admin is not None:
        attr = getattr(model_admin, name, None)
        if attr is not None and callable(attr):
            return attr
    attr = getattr(model, name, None)
    return attr.fget if isinstance(attr, property) else attr


def label_for_field(name, model, model_admin=None):
    attr = display_attr_for_field(name, model, model_admin)
    if attr is not None:
        short_description = getattr(attr, "short_description", None)
        if short_description:
            return short_description
    if isinstance(name, str):
        try:
            field = model._meta.get_field(name)
            return str(field.verbose_name).title()
        except FieldDoesNotExist:
            pass
    name = field_name_for_display(name)
    return getattr(attr, "short_description", None) or name.replace("_", " ").title()


def display_metadata_for_field(name, model, model_admin=None):
    attr = display_attr_for_field(name, model, model_admin)
    return {
        "boolean": bool(getattr(attr, "boolean", False)),
        "empty_value_display": getattr(attr, "empty_value_display", None),
    }


def lookup_field(name, obj, model_admin=None):
    if not isinstance(name, str) and callable(name):
        return name(obj)
    try:
        field = obj._meta.get_field(name)
        value = getattr(obj, name)
        if field.choices:
            return obj._get_FIELD_display(field)
        if isinstance(value, Model):
            return str(value)
        return value
    except FieldDoesNotExist:
        pass
    except ObjectDoesNotExist:
        return None

    if model_admin is not None and hasattr(model_admin, name):
        attr = getattr(model_admin, name)
        return attr(obj)
    attr = getattr(obj, name)
    return attr() if callable(attr) else attr
