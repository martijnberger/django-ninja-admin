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

from django_ninja_admin.utils.schema_constraints import (
    normalize_pydantic_pattern,
    pydantic_numeric_bounds_for_model_field,
    pydantic_numeric_validator_constraints,
    pydantic_pattern_for_form_field,
    pydantic_pattern_for_model_field,
    pydantic_pattern_is_supported,
    pydantic_step_constraint_for_field,
    pydantic_string_validator_constraints,
    step_validator_has_zero_offset,
)


def test_numeric_validator_constraints_coerce_form_field_bounds():
    field = forms.IntegerField(validators=[MinValueValidator(lambda: 3), MaxValueValidator(9)])

    assert pydantic_numeric_validator_constraints(field) == {"ge": 3, "le": 9}


def test_numeric_validator_constraints_skip_unresolvable_callable_limit():
    def broken_limit():
        raise ValueError("not ready")

    field = forms.IntegerField(validators=[MinValueValidator(broken_limit), MaxValueValidator(9)])

    assert pydantic_numeric_validator_constraints(field) == {"le": 9}


def test_model_numeric_bounds_use_model_field_types():
    field = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator("1.50")])

    assert pydantic_numeric_bounds_for_model_field(field) == {"ge": field.to_python("1.50")}


def test_string_validator_constraints_respect_field_max_length():
    field = forms.CharField(
        max_length=10,
        validators=[
            MinLengthValidator(3),
            MaxLengthValidator(8),
            MaxLengthValidator(12),
        ],
    )

    assert pydantic_string_validator_constraints(field) == {"min_length": 3, "max_length": 8}


def test_step_constraint_requires_zero_offset():
    assert pydantic_step_constraint_for_field(forms.IntegerField(validators=[StepValueValidator(5)])) == {
        "multiple_of": 5
    }
    assert not step_validator_has_zero_offset(StepValueValidator(5, offset=1))
    assert pydantic_step_constraint_for_field(forms.IntegerField(validators=[StepValueValidator(5, offset=1)])) == {}


def test_pattern_helpers_normalize_and_skip_unsupported_patterns():
    assert normalize_pydantic_pattern(r"\A[A-Z]+\Z") == "^[A-Z]+\\z"
    assert pydantic_pattern_is_supported(r"^[A-Z]+$")
    assert not pydantic_pattern_is_supported(r"(?<=prefix)value")


def test_pattern_helpers_read_form_and_model_regex_validators():
    form_field = forms.RegexField(regex=r"\A[A-Z]+\Z")
    model_field = models.CharField(max_length=20, validators=[RegexValidator(r"\A[a-z]+\Z")])

    assert pydantic_pattern_for_form_field(form_field) == "^[A-Z]+\\z"
    assert pydantic_pattern_for_model_field(model_field) == "^[a-z]+\\z"
