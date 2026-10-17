from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, create_model

type SchemaFieldDefinition = tuple[Any, Any]

PydanticCreateModel = cast(Any, create_model)


def create_contract_model(
    name: str,
    *,
    base: type[BaseModel],
    fields: Mapping[str, SchemaFieldDefinition],
) -> type[BaseModel]:
    """Compile a Pydantic contract without importing a transport framework."""
    return PydanticCreateModel(
        name,
        __base__=base,
        __module__=base.__module__,
        **fields,
    )
