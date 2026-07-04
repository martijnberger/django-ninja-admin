from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import ceil, floor
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from uuid import UUID

from django import forms
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from pydantic import AnyUrl, IPvAnyAddress, TypeAdapter
from pydantic_core import ValidationError as PydanticCoreValidationError

from django_ninja_admin.schemas import FileFieldValue, ImageFieldValue

RelationField = forms.ModelChoiceField | forms.ModelMultipleChoiceField
FormFieldExample = Callable[[str, forms.Field, Any], Any]
OverrideExample = Callable[[Any], Any]
RelationExample = Callable[[RelationField], Any]
ModelFieldExample = Callable[[models.Field], Any]


def schema_example(schema):
    return (schema.model_json_schema().get("examples") or [{}])[0]


def json_request_examples_extra(**examples):
    openapi_examples = {
        name: {"summary": name.replace("_", " ").title(), "value": value}
        for name, value in examples.items()
        if value is not None
    }
    if not openapi_examples:
        return {}
    return {
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": openapi_examples,
                }
            }
        }
    }


def form_data_example(
    form_fields: Mapping[str, forms.Field],
    *,
    field_example: FormFieldExample,
    selected_fields: Sequence[str] | None = None,
    partial: bool = False,
    overrides: Mapping[str, Any] | None = None,
    exclude_file_fields: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    overrides = overrides or {}
    candidates = _form_example_candidates(
        form_fields,
        selected_fields=selected_fields,
        exclude_file_fields=exclude_file_fields,
    )
    for name, field in candidates:
        if partial and data:
            break
        if partial or field.required:
            data[name] = field_example(name, field, overrides.get(name))
    if not data and candidates:
        name, field = candidates[0]
        data[name] = field_example(name, field, overrides.get(name))
    return data


def form_field_example_value(
    field: forms.Field,
    *,
    override: Any = None,
    override_example: OverrideExample | None = None,
    relation_example: RelationExample | None = None,
    scalar_examples: Mapping[str, Any] | None = None,
    choices_json_safe: bool = False,
    coerce_typed_choice: bool = True,
    null_boolean_example: Any = ...,
) -> Any:
    examples = {
        "decimal": "9.99",
        "integer": 1,
        "float": 1.5,
        "json": {"key": "value"},
        "uuid": "550e8400-e29b-41d4-a716-446655440000",
        "ip": "192.0.2.1",
        "email": "admin@example.com",
        "url": "https://example.com/",
        "split_datetime": ["2026-07-02", "09:30:00"],
        "datetime": "2026-07-02T09:30:00Z",
        "date": "2026-07-02",
        "time": "09:30:00",
        "duration": "1 00:00:00",
    }
    examples.update(scalar_examples or {})
    if override is not None and override_example is not None:
        return override_example(override)
    if relation_example is not None:
        if isinstance(field, forms.ModelMultipleChoiceField):
            return [relation_example(field)]
        if isinstance(field, forms.ModelChoiceField):
            return relation_example(field)
    if isinstance(field, forms.TypedMultipleChoiceField | forms.MultipleChoiceField):
        return [choice_example_value(field.choices, json_safe=choices_json_safe)]
    if isinstance(field, forms.TypedChoiceField):
        value = choice_example_value(field.choices, json_safe=choices_json_safe)
        if coerce_typed_choice and not choices_json_safe:
            return coerce_choice_example(getattr(field, "coerce", None), value)
        return value
    if isinstance(field, forms.ChoiceField):
        return choice_example_value(field.choices, json_safe=choices_json_safe)
    if null_boolean_example is not ... and isinstance(field, forms.NullBooleanField):
        return null_boolean_example
    if isinstance(field, forms.BooleanField):
        return True
    if isinstance(field, forms.DecimalField):
        return examples["decimal"]
    if isinstance(field, forms.IntegerField):
        return examples["integer"]
    if isinstance(field, forms.FloatField):
        return examples["float"]
    if isinstance(field, forms.JSONField):
        return examples["json"]
    if isinstance(field, forms.UUIDField):
        return examples["uuid"]
    if isinstance(field, forms.GenericIPAddressField):
        return examples["ip"]
    if isinstance(field, forms.EmailField):
        return examples["email"]
    if isinstance(field, forms.URLField):
        return examples["url"]
    if isinstance(field, forms.SplitDateTimeField):
        return examples["split_datetime"]
    if isinstance(field, forms.DateTimeField):
        return examples["datetime"]
    if isinstance(field, forms.DateField):
        return examples["date"]
    if isinstance(field, forms.TimeField):
        return examples["time"]
    if isinstance(field, forms.DurationField):
        return examples["duration"]
    return "example"


def relation_form_field_example_value(
    field: RelationField,
    *,
    target_field_example: ModelFieldExample | None = None,
) -> Any:
    target_field = model_choice_target_field(field)
    if target_field_example is not None:
        return target_field_example(target_field)
    return model_identifier_example_value(target_field)


def model_identifier_example_value(field: models.Field) -> Any:
    if isinstance(
        field,
        models.AutoField
        | models.BigAutoField
        | models.SmallAutoField
        | models.IntegerField
        | models.BigIntegerField
        | models.PositiveIntegerField
        | models.PositiveSmallIntegerField
        | models.SmallIntegerField,
    ):
        return 1
    if isinstance(field, models.UUIDField):
        return "550e8400-e29b-41d4-a716-446655440000"
    return "example"


def model_choice_target_field(field):
    model = field.queryset.model
    if field.to_field_name:
        try:
            return model._meta.get_field(field.to_field_name)
        except FieldDoesNotExist:
            pass
    return model._meta.pk


def normalize_schema_override(value):
    if isinstance(value, tuple):
        if len(value) == 2:
            return value
        if len(value) == 1:
            return value[0], None
    return value, None


def schema_override_cache_key(overrides):
    return tuple((name, repr(value)) for name, value in overrides.items())


def schema_override_metadata(override):
    field_type, _default = normalize_schema_override(override)
    return {"schema": TypeAdapter(field_type).json_schema()}


def _form_example_candidates(
    form_fields: Mapping[str, forms.Field],
    *,
    selected_fields: Sequence[str] | None,
    exclude_file_fields: bool,
) -> list[tuple[str, forms.Field]]:
    candidates = []
    field_names = tuple(selected_fields or form_fields.keys())
    for name in field_names:
        field = form_fields.get(name)
        if field is None or getattr(field, "disabled", False):
            continue
        if exclude_file_fields and isinstance(field, forms.FileField):
            continue
        candidates.append((name, field))
    return candidates


def iter_choice_values(choices):
    for value, label in choices:
        if isinstance(label, (list, tuple)):
            yield from iter_choice_values(label)
        else:
            yield value


def choice_example_value(choices, *, json_safe=False):
    for value in iter_choice_values(choices):
        if value not in ("", None):
            return json_example_value(value) if json_safe else value
    return "example"


def coerce_choice_example(coerce, value):
    if coerce is None:
        return value
    try:
        return coerce(value)
    except (TypeError, ValueError):
        return value


def pydantic_type_for_choices(choices, *, as_literal=True):
    literal_type = pydantic_literal_for_choices(choices) if as_literal else None
    if literal_type is not None:
        return literal_type
    value_types = set()
    for value in iter_choice_values(choices):
        if value not in ("", None):
            value_types.add(type(value))
    if not value_types:
        return str
    if value_types <= {int}:
        return int
    if value_types <= {str}:
        return str
    if value_types <= {int, str}:
        return int | str
    if value_types <= {bool}:
        return bool
    return str


def pydantic_literal_for_choices(choices):
    values = pydantic_choice_values(choices)
    if not values:
        return None
    return Literal.__getitem__(tuple(values))


def pydantic_choice_values(choices, *, coerce=None):
    values = []
    seen = set()
    allowed_types = (str, int, bool)
    if coerce is not None:
        allowed_types = (str, int, bool, float, Decimal, UUID)
    for value in iter_choice_values(choices):
        if value in ("", None):
            continue
        if coerce is not None:
            try:
                value = coerce(value)
            except (TypeError, ValueError):
                continue
        elif not isinstance(value, allowed_types):
            value = str(value)
        if not isinstance(value, allowed_types):
            continue
        key = (type(value), value)
        if key not in seen:
            seen.add(key)
            values.append(value)
    return tuple(values)


def schema_type_example(field_type, default):
    if default is not None and default is not ...:
        return default
    origin = get_origin(field_type)
    args = get_args(field_type)
    if origin is Annotated and args:
        return _annotated_schema_type_example(field_type, args[0], args[1:])
    if origin is Literal and args:
        return args[0]
    if origin in {list, set}:
        return [schema_type_example(args[0] if args else str, None)]
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return [schema_type_example(args[0], None)]
        return [schema_type_example(arg, None) for arg in args]
    if origin in {dict}:
        value_type = args[1] if len(args) > 1 else Any
        return {"example": schema_type_example(value_type, None)}
    if args:
        non_null_args = [arg for arg in args if arg is not type(None)]
        if non_null_args:
            return schema_type_example(non_null_args[0], None)
    if field_type is str:
        return "example"
    if field_type is int:
        return 1
    if field_type is float:
        return 1.5
    if field_type is bool:
        return True
    if field_type is Decimal:
        return "9.99"
    if field_type is UUID:
        return "00000000-0000-4000-8000-000000000000"
    if field_type is date:
        return "2026-07-02"
    if field_type is datetime:
        return "2026-07-02T12:00:00+00:00"
    if field_type is time:
        return "12:00:00"
    if field_type is timedelta:
        return "01:00:00"
    if field_type is AnyUrl:
        return "https://example.com/"
    if field_type is IPvAnyAddress:
        return "192.0.2.1"
    if field_type is FileFieldValue:
        return {"name": "files/example.dat", "url": "/media/files/example.dat"}
    if field_type is ImageFieldValue:
        return {
            "name": "images/example.png",
            "url": "/media/images/example.png",
            "width": 640,
            "height": 480,
        }
    return "example"


def _annotated_schema_type_example(field_type, base_type, metadata):
    candidates = [
        schema_type_example(base_type, None),
        *_constraint_example_candidates(base_type, metadata),
    ]
    adapter = TypeAdapter(field_type)
    for candidate in candidates:
        try:
            adapter.validate_python(candidate)
        except PydanticCoreValidationError:
            continue
        return candidate
    return candidates[0]


def _constraint_example_candidates(base_type, metadata):
    constraints = _constraint_metadata(metadata)
    origin = get_origin(base_type)
    args = get_args(base_type)
    if base_type is str:
        min_length = constraints.get("min_length")
        max_length = constraints.get("max_length")
        length = min_length if min_length is not None else 1
        if max_length is not None:
            length = min(length, max_length)
        return ["x" * max(0, length)]
    if base_type is int:
        return _integer_constraint_candidates(constraints)
    if base_type is float:
        return _float_constraint_candidates(constraints)
    if base_type is Decimal:
        return _decimal_constraint_candidates(constraints)
    if origin in {list, set}:
        min_length = constraints.get("min_length") or 1
        item_example = schema_type_example(args[0] if args else str, None)
        return [[item_example for _ in range(min_length)]]
    return []


def _constraint_metadata(metadata):
    constraints = {}
    for item in metadata:
        for nested in getattr(item, "metadata", ()):
            constraints.update(_constraint_metadata((nested,)))
        for name in ("ge", "gt", "le", "lt", "min_length", "max_length"):
            value = getattr(item, name, None)
            if value is not None:
                constraints[name] = value
    return constraints


def _integer_constraint_candidates(constraints):
    candidates = []
    if "ge" in constraints:
        candidates.append(ceil(constraints["ge"]))
    if "gt" in constraints:
        candidates.append(floor(constraints["gt"]) + 1)
    if "le" in constraints:
        candidates.append(floor(constraints["le"]))
    if "lt" in constraints:
        candidates.append(ceil(constraints["lt"]) - 1)
    return candidates


def _float_constraint_candidates(constraints):
    return _ordered_numeric_constraint_candidates(constraints, float, 0.5)


def _decimal_constraint_candidates(constraints):
    return [
        str(candidate)
        for candidate in _ordered_numeric_constraint_candidates(
            constraints,
            Decimal,
            Decimal("0.01"),
        )
    ]


def _ordered_numeric_constraint_candidates(constraints, coerce, exclusive_step):
    lower = None
    upper = None
    if "ge" in constraints:
        lower = coerce(constraints["ge"])
    if "gt" in constraints:
        lower = coerce(constraints["gt"]) + exclusive_step
    if "le" in constraints:
        upper = coerce(constraints["le"])
    if "lt" in constraints:
        upper = coerce(constraints["lt"]) - exclusive_step
    candidates = []
    if lower is not None and upper is not None:
        candidates.append((lower + upper) / 2)
    candidates.extend(candidate for candidate in (lower, upper) if candidate is not None)
    return candidates


def pydantic_model_example(schema):
    return {
        name: annotation_example_value(field.annotation)
        for name, field in schema.model_fields.items()
        if field.is_required()
    }


def annotation_example_value(annotation):
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return json_example_value(args[0]) if args else "example"
    if origin in {Union, UnionType} and args:
        return annotation_example_value(next((arg for arg in args if arg is not type(None)), args[0]))
    if origin in {list, set, tuple, frozenset}:
        return [annotation_example_value(args[0])] if args else ["example"]
    if origin is dict:
        value_type = args[1] if len(args) > 1 else str
        return {"key": annotation_example_value(value_type)}
    if annotation is bool:
        return True
    if annotation is int:
        return 1
    if annotation is float:
        return 1.5
    if annotation is Decimal:
        return "1.00"
    if annotation is UUID:
        return "550e8400-e29b-41d4-a716-446655440000"
    return "example"


def json_example_value(value):
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
