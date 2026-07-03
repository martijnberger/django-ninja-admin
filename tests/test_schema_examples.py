from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from django_ninja_admin.utils.schema_examples import (
    pydantic_model_example,
    schema_example,
    schema_type_example,
)


def test_schema_example_returns_first_declared_example():
    class ExampleSchema(BaseModel):
        model_config = {"json_schema_extra": {"examples": [{"name": "declared"}]}}

        name: str

    assert schema_example(ExampleSchema) == {"name": "declared"}


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
