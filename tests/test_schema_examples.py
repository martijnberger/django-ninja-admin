from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from django import forms
from pydantic import BaseModel, Field, TypeAdapter

from django_ninja_admin.utils.schema_examples import (
    choice_example_value,
    coerce_choice_example,
    form_data_example,
    iter_choice_values,
    json_request_examples_extra,
    model_choice_target_field,
    normalize_schema_override,
    pydantic_choice_values,
    pydantic_model_example,
    pydantic_type_for_choices,
    schema_example,
    schema_override_cache_key,
    schema_override_metadata,
    schema_type_example,
)
from tests.testapp.models import Category


def _field_example(name, _field, override):
    return override or f"{name}-example"


def test_schema_example_returns_first_declared_example():
    class ExampleSchema(BaseModel):
        model_config = {"json_schema_extra": {"examples": [{"name": "declared"}]}}

        name: str

    assert schema_example(ExampleSchema) == {"name": "declared"}


def test_json_request_examples_extra_wraps_named_non_null_examples():
    assert json_request_examples_extra(create={"data": {"name": "Camera"}}, empty=None) == {
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "create": {
                            "summary": "Create",
                            "value": {"data": {"name": "Camera"}},
                        }
                    }
                }
            }
        }
    }


def test_json_request_examples_extra_returns_empty_dict_without_examples():
    assert json_request_examples_extra(create=None) == {}


def test_form_data_example_uses_required_fields_and_overrides():
    form_fields = {
        "name": forms.CharField(required=True),
        "summary": forms.CharField(required=False),
    }

    assert form_data_example(
        form_fields,
        field_example=_field_example,
        overrides={"name": "declared"},
    ) == {"name": "declared"}


def test_form_data_example_partial_uses_first_available_field():
    form_fields = {
        "name": forms.CharField(required=True),
        "summary": forms.CharField(required=True),
    }

    assert form_data_example(form_fields, field_example=_field_example, partial=True) == {"name": "name-example"}


def test_form_data_example_honors_selected_disabled_and_file_fields():
    disabled = forms.CharField(required=True)
    disabled.disabled = True
    form_fields = {
        "name": forms.CharField(required=True),
        "document": forms.FileField(required=True),
        "disabled": disabled,
        "summary": forms.CharField(required=False),
    }

    assert form_data_example(
        form_fields,
        field_example=_field_example,
        selected_fields=("document", "disabled", "summary"),
        exclude_file_fields=True,
    ) == {"summary": "summary-example"}


def test_model_choice_target_field_uses_to_field_name(db):
    field = forms.ModelChoiceField(queryset=Category.objects.all(), to_field_name="slug")

    assert model_choice_target_field(field) is Category._meta.get_field("slug")


def test_model_choice_target_field_falls_back_to_pk_for_missing_to_field(db):
    field = forms.ModelChoiceField(queryset=Category.objects.all(), to_field_name="missing")

    assert model_choice_target_field(field) is Category._meta.pk


def test_schema_override_helpers_normalize_shortcuts_and_cache_keys():
    assert normalize_schema_override((str, ...)) == (str, ...)
    assert normalize_schema_override((int,)) == (int, None)
    assert normalize_schema_override(bool) == (bool, None)
    assert schema_override_cache_key({"flag": bool, "count": (int, 1)}) == (
        ("flag", "<class 'bool'>"),
        ("count", "(<class 'int'>, 1)"),
    )


def test_schema_override_metadata_uses_normalized_type_schema():
    assert schema_override_metadata((bool, False)) == {"schema": {"type": "boolean"}}
    metadata = schema_override_metadata(dict[str, int])

    assert metadata["schema"]["additionalProperties"]["type"] == "integer"


def test_schema_type_example_satisfies_annotated_constraints():
    constrained = Annotated[str, Field(min_length=3, max_length=5)]
    example = schema_type_example(constrained, None)

    assert example == "xxx"
    assert TypeAdapter(constrained).validate_python(example) == "xxx"


def test_schema_type_example_prefers_safe_literal_and_common_scalars():
    assert schema_type_example(Literal["draft", "published"], None) == "draft"
    assert schema_type_example(Decimal, None) == "9.99"
    assert schema_type_example(date, None) == "2026-07-02"
    assert schema_type_example(UUID, None) == "00000000-0000-4000-8000-000000000000"


def test_pydantic_model_example_uses_required_field_annotations():
    class ActionInput(BaseModel):
        names: list[str]
        count: int
        enabled: bool = False

    assert pydantic_model_example(ActionInput) == {"names": ["example"], "count": 1}


def test_choice_helpers_flatten_groups_and_skip_empty_values():
    price = Decimal("1.50")
    choices = [
        ("", "Any"),
        ("group", [("", "Empty"), (price, "Price")]),
    ]

    assert list(iter_choice_values(choices)) == ["", "", price]
    assert choice_example_value(choices) == price
    assert choice_example_value(choices, json_safe=True) == "1.50"


def test_pydantic_choice_values_dedupe_and_normalize_values():
    choices = [(1, "One"), ("1", "One string"), (1, "Duplicate"), (UUID(int=1), "UUID")]

    assert pydantic_choice_values(choices) == (1, "1", "00000000-0000-0000-0000-000000000001")
    assert pydantic_choice_values(choices, coerce=str) == ("1", "00000000-0000-0000-0000-000000000001")


def test_pydantic_choice_type_falls_back_to_scalar_union_when_literals_disabled():
    assert pydantic_type_for_choices([(1, "One"), ("two", "Two")], as_literal=False) == int | str
    assert pydantic_type_for_choices([(True, "Enabled")], as_literal=False) is bool


def test_coerce_choice_example_returns_original_value_when_coercion_fails():
    assert coerce_choice_example(int, "2") == 2
    assert coerce_choice_example(int, "bad") == "bad"
