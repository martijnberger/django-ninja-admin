from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}
UNORDERED_SCALAR_LIST_KEYS = {"enum", "required", "tags"}
TOP_LEVEL_CONTRACT_KEYS = ("security", "servers", "tags")


@dataclass(frozen=True)
class OpenAPIDifference:
    kind: str
    location: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenAPIDiffReport:
    expected: str
    actual: str
    differences: tuple[OpenAPIDifference, ...]

    @property
    def has_differences(self) -> bool:
        return bool(self.differences)

    @property
    def counts(self) -> dict[str, int]:
        counts: defaultdict[str, int] = defaultdict(int)
        for difference in self.differences:
            counts[difference.kind] += 1
        return dict(sorted(counts.items()))


def load_openapi(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise ValueError(f"{path} does not contain a JSON object.")
    return document


def normalize_openapi(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, Mapping):
        return {key: normalize_openapi(value[key], parent_key=str(key)) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [normalize_openapi(item, parent_key=parent_key) for item in value]
        if parent_key in UNORDERED_SCALAR_LIST_KEYS and all(_is_scalar(item) for item in normalized):
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
        return normalized
    return value


def diff_openapi(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    expected_name: str = "expected",
    actual_name: str = "actual",
) -> OpenAPIDiffReport:
    normalized_expected = normalize_openapi(expected)
    normalized_actual = normalize_openapi(actual)
    differences: list[OpenAPIDifference] = []
    differences.extend(_diff_operations(normalized_expected, normalized_actual))
    differences.extend(_diff_path_metadata(normalized_expected, normalized_actual))
    differences.extend(_diff_components(normalized_expected, normalized_actual))
    differences.extend(_diff_top_level(normalized_expected, normalized_actual))
    differences.sort(key=lambda difference: (difference.kind, difference.location, difference.details))
    return OpenAPIDiffReport(expected=expected_name, actual=actual_name, differences=tuple(differences))


def render_text(report: OpenAPIDiffReport) -> str:
    lines = [
        "OpenAPI Diff Report",
        f"Expected: {report.expected}",
        f"Actual: {report.actual}",
        f"Differences: {len(report.differences)}",
    ]
    if not report.differences:
        return "\n".join([*lines, "No semantic contract differences found."])

    lines.append("Counts:")
    for kind, count in report.counts.items():
        lines.append(f"  {kind}: {count}")

    current_kind = None
    for difference in report.differences:
        if difference.kind != current_kind:
            current_kind = difference.kind
            lines.append("")
            lines.append(f"{difference.kind}:")
        detail = f" ({', '.join(difference.details)})" if difference.details else ""
        lines.append(f"  {difference.location}{detail}")
    return "\n".join(lines)


def report_to_dict(report: OpenAPIDiffReport) -> dict[str, Any]:
    return {
        "expected": report.expected,
        "actual": report.actual,
        "difference_count": len(report.differences),
        "counts": report.counts,
        "differences": [asdict(difference) for difference in report.differences],
    }


def _diff_operations(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[OpenAPIDifference]:
    expected_operations = _collect_operations(expected)
    actual_operations = _collect_operations(actual)
    differences: list[OpenAPIDifference] = []
    for location in sorted(actual_operations.keys() - expected_operations.keys()):
        differences.append(OpenAPIDifference("added_operation", location))
    for location in sorted(expected_operations.keys() - actual_operations.keys()):
        differences.append(OpenAPIDifference("removed_operation", location))
    for location in sorted(expected_operations.keys() & actual_operations.keys()):
        expected_operation = expected_operations[location]
        actual_operation = actual_operations[location]
        if expected_operation != actual_operation:
            differences.append(
                OpenAPIDifference(
                    "changed_operation",
                    location,
                    tuple(_changed_keys(expected_operation, actual_operation)),
                )
            )
    return differences


def _diff_path_metadata(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[OpenAPIDifference]:
    expected_metadata = _collect_path_metadata(expected)
    actual_metadata = _collect_path_metadata(actual)
    differences: list[OpenAPIDifference] = []
    for location in sorted(actual_metadata.keys() - expected_metadata.keys()):
        differences.append(OpenAPIDifference("added_path_metadata", location))
    for location in sorted(expected_metadata.keys() - actual_metadata.keys()):
        differences.append(OpenAPIDifference("removed_path_metadata", location))
    for location in sorted(expected_metadata.keys() & actual_metadata.keys()):
        if expected_metadata[location] != actual_metadata[location]:
            differences.append(
                OpenAPIDifference(
                    "changed_path_metadata",
                    location,
                    tuple(_changed_keys(expected_metadata[location], actual_metadata[location])),
                )
            )
    return differences


def _diff_components(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[OpenAPIDifference]:
    expected_components = _collect_components(expected)
    actual_components = _collect_components(actual)
    differences: list[OpenAPIDifference] = []
    for location in sorted(actual_components.keys() - expected_components.keys()):
        differences.append(OpenAPIDifference("added_component", location))
    for location in sorted(expected_components.keys() - actual_components.keys()):
        differences.append(OpenAPIDifference("removed_component", location))
    for location in sorted(expected_components.keys() & actual_components.keys()):
        expected_component = expected_components[location]
        actual_component = actual_components[location]
        if expected_component != actual_component:
            differences.append(
                OpenAPIDifference(
                    "changed_component",
                    location,
                    tuple(_changed_keys(expected_component, actual_component)),
                )
            )
    return differences


def _diff_top_level(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[OpenAPIDifference]:
    differences: list[OpenAPIDifference] = []
    for key in TOP_LEVEL_CONTRACT_KEYS:
        if expected.get(key) != actual.get(key):
            differences.append(OpenAPIDifference("changed_top_level", key))
    return differences


def _collect_operations(document: Mapping[str, Any]) -> dict[str, Any]:
    operations = {}
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS:
                operations[f"{method.upper()} {path}"] = operation
    return operations


def _collect_path_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {}
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, Mapping):
            continue
        path_metadata = {key: value for key, value in path_item.items() if key.lower() not in HTTP_METHODS}
        if path_metadata:
            metadata[path] = path_metadata
    return metadata


def _collect_components(document: Mapping[str, Any]) -> dict[str, Any]:
    components = {}
    for group, group_components in document.get("components", {}).items():
        if not isinstance(group_components, Mapping):
            continue
        for name, component in group_components.items():
            components[f"{group}.{name}"] = component
    return components


def _changed_keys(expected: Any, actual: Any) -> list[str]:
    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        return ["value"]
    keys = sorted(set(expected) | set(actual))
    return [str(key) for key in keys if expected.get(key) != actual.get(key)]


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Semantically compare two OpenAPI JSON documents.")
    parser.add_argument("expected", type=Path, help="Baseline OpenAPI JSON document.")
    parser.add_argument("actual", type=Path, help="Candidate OpenAPI JSON document.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON instead of text.")
    parser.add_argument("--fail-on-diff", action="store_true", help="Exit non-zero when differences are found.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = diff_openapi(
        load_openapi(args.expected),
        load_openapi(args.actual),
        expected_name=str(args.expected),
        actual_name=str(args.actual),
    )
    if args.json:
        print(json.dumps(report_to_dict(report), indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 1 if args.fail_on_diff and report.has_differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
