import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from django_veo_admin_api.core.schema_compiler import create_contract_model


class ClosedContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


def test_contract_compiler_preserves_base_config_and_field_metadata():
    contract = create_contract_model(
        "CompiledContract",
        base=ClosedContract,
        fields={
            "name": (str, Field(..., title="Display name", max_length=20)),
            "count": (int | None, None),
        },
    )

    assert contract.model_validate({"name": "Example"}).model_dump() == {"name": "Example", "count": None}
    assert contract.model_json_schema()["additionalProperties"] is False
    assert contract.model_json_schema()["properties"]["name"] == {
        "maxLength": 20,
        "title": "Display name",
        "type": "string",
    }
    with pytest.raises(ValidationError):
        contract.model_validate({"name": "Example", "unexpected": True})
