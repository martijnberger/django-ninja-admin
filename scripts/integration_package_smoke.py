from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_utils import build_or_resolve_wheel, smoke_uv_env

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test an installed optional integration profile.")
    parser.add_argument("profile", choices=("mcp", "all"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run integration package smoke checks.")

    with tempfile.TemporaryDirectory(prefix=f"django-veo-admin-api-{args.profile}-") as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        venv_dir = tmp_path / ".venv"
        uv_env = smoke_uv_env()
        wheel = build_or_resolve_wheel(uv, dist_dir, env=uv_env)

        run([uv, "venv", "--python", sys.executable, str(venv_dir)], env=uv_env)
        python = venv_python(venv_dir)
        run(
            [uv, "pip", "install", "--python", str(python), f"{wheel}[{args.profile}]"],
            env=uv_env,
        )

        env = os.environ.copy()
        env["DJANGO_VEO_ADMIN_API_SMOKE_PROFILE"] = args.profile
        run([str(python), "-c", SMOKE_CODE], cwd=tmp_path, env=env)


SMOKE_CODE = """
import importlib.util
import os

import django
from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import models
from django.test import RequestFactory
from mcp import Client

profile = os.environ["DJANGO_VEO_ADMIN_API_SMOKE_PROFILE"]
if profile == "mcp":
    assert importlib.util.find_spec("ninja") is None

settings.configure(
    SECRET_KEY="integration-smoke",
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django_veo_admin_api",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
django.setup()

from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.integrations.mcp import MCPAdminServer


class StaffUser:
    is_authenticated = True
    is_active = True
    is_staff = True
    is_superuser = True

    def has_perm(self, permission, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True


class SmokeRecord(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "auth"


core_site = CoreAdminSite(include_auth=False)
core_site.register(SmokeRecord, ModelAdmin)


def request_factory(info):
    request = RequestFactory().get("/mcp")
    request.user = StaffUser()
    return request


adapter = MCPAdminServer(core_site, request_factory)


async def exercise():
    async with Client(adapter.server) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} >= {"admin.apps", "admin.permissions"}
        assert "admin.auth.smokerecord.create" in {tool.name for tool in tools.tools}
        result = await client.call_tool("admin.permissions")
        assert result.is_error is False
        assert result.structured_content["data"]["is_staff"] is True


async_to_sync(exercise)()

if profile == "all":
    from django_veo_admin_api.integrations.ninja import NinjaAdminSite

    ninja_site = NinjaAdminSite(auth=None, include_auth=False)
    ninja_site.register(SmokeRecord, ModelAdmin)
    assert ninja_site._registry is not core_site._registry
    core_admin = core_site.get_model_admin(SmokeRecord)
    ninja_admin = ninja_site.get_model_admin(SmokeRecord)
    assert core_admin.get_output_schema(None).model_json_schema() == ninja_admin.get_output_schema(
        None
    ).model_json_schema()
    assert core_admin.get_mutation_payload_schema(
        None, change=False, partial=False
    ).model_json_schema() == ninja_admin.get_mutation_payload_schema(
        None, change=False, partial=False
    ).model_json_schema()
"""


if __name__ == "__main__":
    main()
