from __future__ import annotations

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


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the package smoke check.")

    with tempfile.TemporaryDirectory(prefix="django-veo-admin-api-smoke-") as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        venv_dir = tmp_path / ".venv"
        uv_env = smoke_uv_env()
        wheel = build_or_resolve_wheel(uv, dist_dir, env=uv_env)

        run([uv, "venv", "--python", sys.executable, str(venv_dir)], env=uv_env)
        python = venv_python(venv_dir)
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                str(wheel),
            ],
            env=uv_env,
        )

        smoke_code = """
import importlib.metadata
import importlib.util
import sys

import django
from django.conf import settings

assert importlib.util.find_spec("ninja") is None

if not settings.configured:
    settings.configure(
        SECRET_KEY="smoke",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django_veo_admin_api",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[],
        ALLOWED_HOSTS=["*"],
        USE_TZ=True,
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    )
django.setup()

import django_veo_admin_api
from django_veo_admin_api import (
    ModelAdmin,
    ShowFacets,
    TabularInline,
    action,
    display,
)
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import AdminSchema

assert "ninja" not in sys.modules
assert ModelAdmin is not None
assert ShowFacets.ALLOW.value == "ALLOW"
assert TabularInline is not None
assert callable(action)
assert callable(display)
assert AdminSchema.model_json_schema()["type"] == "object"
assert AdminRequestContext is not None
assert OperationResult is not None

try:
    django_veo_admin_api.NinjaAdminSite
except ImportError as exc:
    assert str(exc) == (
        "Django Ninja is required for django_veo_admin_api.integrations.ninja; "
        "install it with `pip install 'django-veo-admin-api[ninja]'`."
    )
else:
    raise AssertionError("NinjaAdminSite unexpectedly imported without the ninja extra")

metadata = importlib.metadata.metadata("django-veo-admin-api")
requires = metadata.get_all("Requires-Dist") or []
assert any(requirement.lower().startswith("django") for requirement in requires)
assert any(requirement.lower().startswith("pydantic") for requirement in requires)
assert all(
    "extra == 'ninja'" in requirement.lower() or 'extra == "ninja"' in requirement.lower()
    for requirement in requires
    if requirement.lower().startswith("django-ninja")
)
for dependency in requires:
    lowered = dependency.lower()
    assert "djangorestframework" not in lowered
    assert "drf-spectacular" not in lowered
"""
        run([str(python), "-c", smoke_code], cwd=tmp_path)


if __name__ == "__main__":
    main()
