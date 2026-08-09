from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast

from django import forms
from django.core.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
    StepValueValidator,
)
from django.db import models
from pydantic import Field, TypeAdapter
from pydantic_core import SchemaError

INVALID_LIMIT_VALUE = object()


def validator_limit_value(validator):
    limit_value = getattr(validator, "limit_value", None)
    if callable(limit_value):
        try:
            return limit_value()
        except (TypeError, ValueError):
            return INVALID_LIMIT_VALUE
    return limit_value


def get_step_value_validator(field):
    for validator in getattr(field, "validators", ()):
        if isinstance(validator, StepValueValidator):
            return validator
    return None


def step_validator_has_zero_offset(validator):
    offset = getattr(validator, "offset", None)
    if offset is None:
        return True
    try:
        return Decimal(str(offset)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def pydantic_step_value(field, value):
    if isinstance(field, (forms.DecimalField, models.DecimalField)):
        return Decimal(str(value))
    if isinstance(field, (forms.IntegerField, models.IntegerField)):
        return int(value)
    if isinstance(field, (forms.FloatField, models.FloatField)):
        return float(value)
    return value


def pydantic_numeric_bound_value(field, value):
    if isinstance(field, (forms.DecimalField, models.DecimalField)):
        return Decimal(str(value))
    if isinstance(field, (forms.FloatField, models.FloatField)):
        return float(value)
    if isinstance(field, (forms.IntegerField, models.IntegerField)):
        return int(value)
    return value


def pydantic_numeric_validator_constraints(field):
    constraints = {}
    for validator in getattr(field, "validators", ()):
        limit_value = validator_limit_value(validator)
        if limit_value is INVALID_LIMIT_VALUE:
            continue
        if isinstance(validator, MinValueValidator):
            constraints["ge"] = max(
                constraints.get("ge", limit_value),
                pydantic_numeric_bound_value(field, limit_value),
            )
        elif isinstance(validator, MaxValueValidator):
            constraints["le"] = min(
                constraints.get("le", limit_value),
                pydantic_numeric_bound_value(field, limit_value),
            )
    return constraints


def pydantic_numeric_bounds_for_model_field(field):
    bounds = {}
    for validator in getattr(field, "validators", ()):
        limit_value = validator_limit_value(validator)
        if limit_value is INVALID_LIMIT_VALUE:
            continue
        if isinstance(validator, MinValueValidator):
            bound = pydantic_numeric_bound_value(field, limit_value)
            bounds["ge"] = max(bounds.get("ge", bound), bound)
        elif isinstance(validator, MaxValueValidator):
            bound = pydantic_numeric_bound_value(field, limit_value)
            bounds["le"] = min(bounds.get("le", bound), bound)
    return bounds


def pydantic_step_constraint_for_field(field):
    step_validator = get_step_value_validator(field)
    if step_validator is None or not step_validator_has_zero_offset(step_validator):
        return {}
    limit_value = validator_limit_value(step_validator)
    if limit_value is INVALID_LIMIT_VALUE:
        return {}
    return {"multiple_of": pydantic_step_value(field, limit_value)}


def pydantic_string_validator_constraints(field):
    constraints = {}
    field_max_length = getattr(field, "max_length", None)
    for validator in getattr(field, "validators", ()):
        limit_value = validator_limit_value(validator)
        if limit_value is INVALID_LIMIT_VALUE or limit_value is None:
            continue
        limit_value = cast(Any, limit_value)
        if isinstance(validator, MinLengthValidator):
            constraints["min_length"] = max(cast(Any, constraints.get("min_length", limit_value)), limit_value)
        elif isinstance(validator, MaxLengthValidator) and (field_max_length is None or limit_value < field_max_length):
            constraints["max_length"] = min(cast(Any, constraints.get("max_length", limit_value)), limit_value)
    return constraints


def normalize_pydantic_pattern(regex):
    pattern = getattr(regex, "pattern", regex)
    if not isinstance(pattern, str):
        return None
    return pattern.replace(r"\A", "^").replace(r"\Z", r"\z")


def pydantic_pattern_is_supported(pattern):
    try:
        TypeAdapter(Annotated[str, Field(pattern=pattern)])
    except SchemaError:
        return False
    return True


def pydantic_pattern_for_form_field(field):
    pattern = normalize_pydantic_pattern(getattr(field, "regex", None))
    if pattern and pydantic_pattern_is_supported(pattern):
        return pattern
    return pydantic_pattern_for_validators(getattr(field, "validators", ()))


def pydantic_pattern_for_model_field(field):
    return pydantic_pattern_for_validators(getattr(field, "validators", ()))


def pydantic_pattern_for_validators(validators):
    for validator in validators:
        if isinstance(validator, RegexValidator):
            pattern = normalize_pydantic_pattern(getattr(validator, "regex", None))
            if pattern and pydantic_pattern_is_supported(pattern):
                return pattern
    return None
