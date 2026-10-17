from __future__ import annotations

import argparse
import difflib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from asgiref.sync import async_to_sync

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "tests" / "golden" / "mcp-tools.json"


def configure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
    import django
    from django.apps import apps

    if not apps.ready:
        django.setup()


def export_manifest() -> dict[str, Any]:
    configure_django()
    from django.test import RequestFactory

    from django_veo_admin_api.core import CoreAdminSite
    from django_veo_admin_api.integrations.mcp import MCPAdminServer
    from tests.testapp.admin import CategoryAdmin, ProductAdmin
    from tests.testapp.models import Category, Product

    class SnapshotUser:
        is_authenticated = True
        is_active = True
        is_staff = True
        is_superuser = True
        pk = "snapshot"

        def has_perm(self, permission, obj=None):
            return True

        def has_module_perms(self, app_label):
            return True

    site = CoreAdminSite(include_auth=False)
    site.register(Category, CategoryAdmin)
    site.register(Product, ProductAdmin)

    def request_factory(info):
        request = RequestFactory().get("/mcp")
        request.user = SnapshotUser()
        return request

    adapter = MCPAdminServer(site, request_factory)

    async def collect_tools():
        return await adapter.server.list_tools()

    tools = async_to_sync(collect_tools)()
    return {
        "protocolVersion": "2026-07-28",
        "tools": [
            tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            for tool in sorted(tools, key=lambda tool: tool.name)
        ],
    }


def write_snapshot(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(manifest), encoding="utf-8")


def check_snapshot(path: Path, manifest: dict[str, Any]) -> int:
    if not path.exists():
        print(f"MCP tool snapshot does not exist: {path}")
        return 1
    expected = json.loads(path.read_text(encoding="utf-8"))
    if expected == manifest:
        print("MCP tool snapshot matches.")
        return 0
    diff = difflib.unified_diff(
        _render(expected).splitlines(),
        _render(manifest).splitlines(),
        fromfile=str(path),
        tofile="generated MCP tool manifest",
        lineterm="",
    )
    print("\n".join(diff))
    return 1


def _render(manifest: dict[str, Any]) -> str:
    return f"{json.dumps(manifest, indent=2, sort_keys=True)}\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check or update the test-project MCP tool manifest.")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT, help="Path to the golden MCP JSON.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Compare generated tools with the golden snapshot.")
    mode.add_argument("--update", action="store_true", help="Regenerate the golden MCP tool snapshot.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = export_manifest()
    if args.update:
        write_snapshot(args.snapshot, manifest)
        print(f"Wrote MCP tool snapshot to {args.snapshot}.")
        return 0
    return check_snapshot(args.snapshot, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
