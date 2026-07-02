from __future__ import annotations

import json
from pathlib import Path

from scripts.openapi_diff import diff_openapi, main, normalize_openapi, render_text, report_to_dict


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def base_document() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Demo", "version": "1.0.0"},
        "tags": [{"name": "products"}],
        "paths": {
            "/products": {
                "parameters": [{"name": "tenant", "in": "header"}],
                "get": {
                    "operationId": "listProducts",
                    "tags": ["products"],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ProductList"}}},
                        }
                    },
                },
                "post": {
                    "operationId": "createProduct",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ProductCreate"},
                                "examples": {"basic": {"value": {"name": "Camera"}}},
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Product": {
                    "type": "object",
                    "required": ["name", "id"],
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "status": {"enum": ["draft", "live"], "type": "string"},
                    },
                },
                "ProductCreate": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {"name": {"type": "string"}},
                },
                "ProductList": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/Product"},
                },
            },
            "securitySchemes": {
                "Session": {"type": "apiKey", "name": "sessionid", "in": "cookie"},
            },
        },
    }


def test_normalize_openapi_ignores_semantically_unordered_scalar_lists():
    document = base_document()
    shuffled = base_document()
    shuffled["components"]["schemas"]["Product"]["required"] = ["id", "name"]
    shuffled["components"]["schemas"]["Product"]["properties"]["status"]["enum"] = ["live", "draft"]

    assert normalize_openapi(document) == normalize_openapi(shuffled)


def test_diff_openapi_detects_route_component_path_and_top_level_changes():
    expected = base_document()
    actual = base_document()
    actual["paths"]["/products"]["get"]["responses"]["200"]["description"] = "Success"
    actual["paths"]["/products"]["parameters"][0]["name"] = "workspace"
    actual["paths"]["/products/{id}"] = {"get": {"operationId": "getProduct", "responses": {"200": {}}}}
    actual["paths"]["/products"].pop("post")
    actual["components"]["schemas"]["Product"]["properties"]["name"]["maxLength"] = 100
    actual["components"]["schemas"]["ProductDetail"] = {"type": "object"}
    actual["components"]["schemas"].pop("ProductList")
    actual["servers"] = [{"url": "https://api.example.test"}]

    report = diff_openapi(expected, actual)

    difference_keys = {(difference.kind, difference.location) for difference in report.differences}
    assert ("added_operation", "GET /products/{id}") in difference_keys
    assert ("removed_operation", "POST /products") in difference_keys
    assert ("changed_operation", "GET /products") in difference_keys
    assert ("changed_path_metadata", "/products") in difference_keys
    assert ("added_component", "schemas.ProductDetail") in difference_keys
    assert ("removed_component", "schemas.ProductList") in difference_keys
    assert ("changed_component", "schemas.Product") in difference_keys
    assert ("changed_top_level", "servers") in difference_keys


def test_render_text_and_json_payload_include_counts():
    expected = base_document()
    actual = base_document()
    actual["paths"]["/products"].pop("post")

    report = diff_openapi(expected, actual, expected_name="before.json", actual_name="after.json")

    text = render_text(report)
    payload = report_to_dict(report)
    assert "Removed_operation" not in text
    assert "removed_operation" in text
    assert "POST /products" in text
    assert payload["difference_count"] == 1
    assert payload["counts"] == {"removed_operation": 1}
    json.dumps(payload)


def test_main_can_fail_on_diff(tmp_path, capsys):
    expected_path = tmp_path / "expected.json"
    actual_path = tmp_path / "actual.json"
    expected = base_document()
    actual = base_document()
    actual["paths"]["/products"].pop("post")
    write_json(expected_path, expected)
    write_json(actual_path, actual)

    exit_code = main([str(expected_path), str(actual_path), "--fail-on-diff"])

    assert exit_code == 1
    assert "Differences: 1" in capsys.readouterr().out


def test_main_passes_for_matching_documents(tmp_path, capsys):
    expected_path = tmp_path / "expected.json"
    actual_path = tmp_path / "actual.json"
    write_json(expected_path, base_document())
    write_json(actual_path, base_document())

    exit_code = main([str(expected_path), str(actual_path)])

    assert exit_code == 0
    assert "No semantic contract differences found." in capsys.readouterr().out
