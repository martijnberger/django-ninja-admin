from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import TypeAdapter
from pydantic.errors import PydanticSchemaGenerationError, PydanticUserError


def iter_contract_schemas(schema: Any, label: str) -> Iterator[tuple[str, Any]]:
    if schema is None:
        return
    if isinstance(schema, Mapping):
        for status_code, status_schema in schema.items():
            yield f"{label}[{status_code}]", status_schema
        return
    yield label, schema


def open_object_schema_paths(schema_type: Any) -> list[str]:
    try:
        json_schema = TypeAdapter(schema_type).json_schema()
    except (PydanticSchemaGenerationError, PydanticUserError, TypeError, ValueError):
        return []

    paths = []

    def walk(node, path):
        if isinstance(node, Mapping):
            if node.get("type") == "object":
                additional_properties = node.get("additionalProperties", None)
                if (
                    ("properties" in node and additional_properties is not False)
                    or ("properties" not in node and "additionalProperties" not in node)
                    or additional_properties is True
                    or additional_properties == {}
                ):
                    paths.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(json_schema, "")
    return paths
