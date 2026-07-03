from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder

from scripts.openapi_diff import diff_openapi, load_openapi, normalize_openapi, render_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "tests" / "golden" / "openapi.json"


def configure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def export_openapi() -> dict[str, Any]:
    configure_django()
    from django_ninja_admin import site

    document = site.api.get_openapi_schema(path_prefix="/admin-api")
    wire_document = json.loads(json.dumps(document, cls=DjangoJSONEncoder))
    return normalize_openapi(wire_document)


def write_snapshot(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(document, indent=2, sort_keys=True)}\n", encoding="utf-8")


def check_snapshot(path: Path, document: dict[str, Any]) -> int:
    expected = load_openapi(path)
    report = diff_openapi(expected, document, expected_name=str(path), actual_name="generated test OpenAPI")
    if report.has_differences:
        print(render_text(report))
        return 1
    print("OpenAPI snapshot matches.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check or update the test-project OpenAPI golden snapshot.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="Path to the golden OpenAPI JSON.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check the generated OpenAPI against the golden snapshot.")
    mode.add_argument("--update", action="store_true", help="Regenerate the golden OpenAPI snapshot.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    document = export_openapi()
    if args.update:
        write_snapshot(args.snapshot, document)
        print(f"Wrote OpenAPI snapshot to {args.snapshot}.")
        return 0
    return check_snapshot(args.snapshot, document)


if __name__ == "__main__":
    raise SystemExit(main())
