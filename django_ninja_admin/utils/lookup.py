from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist
from django.db.models import Model


def label_for_field(name, model, model_admin=None):
    if model_admin is not None:
        attr = getattr(model_admin, name, None)
        if attr is not None and callable(attr):
            return getattr(attr, "short_description", None) or name.replace("_", " ").title()
    try:
        field = model._meta.get_field(name)
        return str(field.verbose_name).title()
    except FieldDoesNotExist:
        attr = getattr(model, name, None)
        return getattr(attr, "short_description", None) or name.replace("_", " ").title()


def lookup_field(name, obj, model_admin=None):
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

