from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from django.forms import Field as DjangoFormField
from pydantic import ConfigDict, create_model

type SchemaFieldDefinition = tuple[Any, Any]
type FormFieldTypeResolver = Callable[[str, DjangoFormField | None, bool], Any]

PydanticCreateModel = cast(Any, create_model)


def form_schema_field_definitions(
    form_fields: Mapping[str, DjangoFormField],
    field_names: Sequence[str],
    *,
    resolve_field_type: FormFieldTypeResolver,
    partial: bool,
    choices_as_literal: bool = True,
    extra_fields: Mapping[str, SchemaFieldDefinition] | None = None,
) -> dict[str, SchemaFieldDefinition]:
    """Build closed Pydantic field definitions from Django form fields."""
    definitions = dict(extra_fields or {})
    for field_name in field_names:
        form_field = form_fields.get(field_name)
        field_type = resolve_field_type(field_name, form_field, choices_as_literal)
        required = bool(
            form_field and form_field.required and not getattr(form_field, "disabled", False) and not partial
        )
        definitions[field_name] = (field_type, ...) if required else (field_type | None, None)
    return definitions


def create_form_schema(
    name: str,
    *,
    base_schema: type[Any],
    field_definitions: Mapping[str, SchemaFieldDefinition],
    example: Mapping[str, Any],
):
    """Create a closed Pydantic model with one stable request example."""
    return PydanticCreateModel(
        name,
        __base__=base_schema,
        __config__=ConfigDict(json_schema_extra={"examples": [dict(example)]}),
        **field_definitions,
    )
