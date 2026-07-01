from decimal import Decimal

from django.forms.models import model_to_dict

from django_ninja_admin.utils.format_error import format_error


def model_data_for_form(instance, fields):
    data = model_to_dict(instance, fields=fields)
    for key, value in list(data.items()):
        if isinstance(value, Decimal):
            data[key] = str(value)
    return data


def _choice_value(value):
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else None


def field_description(name, field, *, read_only=False):
    attrs = {
        "required": field.required,
        "label": field.label or name.replace("_", " ").title(),
        "help_text": str(field.help_text or ""),
        "read_only": read_only,
        "widget": field.widget.__class__.__name__,
    }
    if getattr(field, "choices", None):
        attrs["choices"] = [(_choice_value(value), str(label)) for value, label in field.choices]
    if getattr(field, "initial", None) not in (None, ""):
        attrs["initial"] = field.initial
    if getattr(field, "max_length", None) is not None:
        attrs["max_length"] = field.max_length
    return {"name": name, "type": field.__class__.__name__, "attrs": attrs}


def form_field_descriptions(form_class, *, readonly_fields=(), instance=None):
    form = form_class(instance=instance)
    descriptions = []
    for name, field in form.fields.items():
        descriptions.append(field_description(name, field, read_only=name in readonly_fields))
    for name in readonly_fields:
        if name not in form.fields:
            descriptions.append(
                {
                    "name": name,
                    "type": "ReadonlyField",
                    "attrs": {
                        "required": False,
                        "label": name.replace("_", " ").title(),
                        "help_text": "",
                        "read_only": True,
                    },
                }
            )
    return descriptions


def form_errors(form):
    return format_error(form.errors)


class RequestDataFormMixin:
    def clean(self):
        cleaned = super().clean()
        return cleaned
