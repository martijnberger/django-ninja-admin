import pytest
from django import forms
from pydantic import ValidationError

from django_ninja_admin.schemas import AdminWriteSchema
from django_ninja_admin.utils.form_schemas import create_form_schema, form_schema_field_definitions


def test_form_schema_compiler_preserves_required_disabled_and_partial_fields():
    disabled = forms.CharField(required=True)
    disabled.disabled = True
    form_fields = {
        "name": forms.CharField(required=True),
        "summary": forms.CharField(required=False),
        "disabled": disabled,
    }
    calls = []

    def resolve_field_type(name, _field, choices_as_literal):
        calls.append((name, choices_as_literal))
        return str

    definitions = form_schema_field_definitions(
        form_fields,
        ("name", "summary", "disabled"),
        resolve_field_type=resolve_field_type,
        partial=False,
    )
    schema = create_form_schema(
        "ExampleWriteSchema",
        base_schema=AdminWriteSchema,
        field_definitions=definitions,
        example={"name": "Example"},
    )

    assert calls == [("name", True), ("summary", True), ("disabled", True)]
    assert schema.model_validate({"name": "Example"}).model_dump() == {
        "name": "Example",
        "summary": None,
        "disabled": None,
    }
    assert schema.model_json_schema()["examples"] == [{"name": "Example"}]
    with pytest.raises(ValidationError):
        schema.model_validate({"name": "Example", "unknown": "rejected"})


def test_form_schema_compiler_supports_bulk_style_extra_fields_and_non_literal_choices():
    form_fields = {"status": forms.ChoiceField(choices=[("ready", "Ready")], required=True)}
    choices_as_literal = []
    definitions = form_schema_field_definitions(
        form_fields,
        ("status",),
        resolve_field_type=lambda _name, _field, as_literal: choices_as_literal.append(as_literal) or str,
        partial=True,
        choices_as_literal=False,
        extra_fields={"pk": (int, ...)},
    )
    schema = create_form_schema(
        "ExampleBulkRow",
        base_schema=AdminWriteSchema,
        field_definitions=definitions,
        example={"pk": 1, "status": "ready"},
    )

    assert choices_as_literal == [False]
    assert schema.model_validate({"pk": 1}).model_dump() == {"pk": 1, "status": None}
