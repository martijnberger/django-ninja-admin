from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the package smoke check.")

    with tempfile.TemporaryDirectory(prefix="django-ninja-admin-smoke-") as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        install_dir = tmp_path / "install"
        uv_env = os.environ.copy()
        smoke_cache_dir = Path(tempfile.gettempdir()) / "django-ninja-admin-uv-cache"
        uv_env["UV_CACHE_DIR"] = os.environ.get("DJANGO_NINJA_ADMIN_SMOKE_UV_CACHE", str(smoke_cache_dir))
        run([uv, "build", "--wheel", "--out-dir", str(dist_dir)], env=uv_env)

        wheels = sorted(dist_dir.glob("django_ninja_admin-*.whl"))
        if not wheels:
            raise SystemExit("No django-ninja-admin wheel was built.")

        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                sys.executable,
                "--no-deps",
                "--target",
                str(install_dir),
                str(wheels[-1]),
            ],
            env=uv_env,
        )

        env = os.environ.copy()
        pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(install_dir) if not pythonpath else f"{install_dir}{os.pathsep}{pythonpath}"
        smoke_code = f"""
import importlib.metadata
from pathlib import Path

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="smoke",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django_ninja_admin",
        ],
        DATABASES={{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}}},
        ROOT_URLCONF=__name__,
        MIDDLEWARE=[],
        ALLOWED_HOSTS=["*"],
        USE_TZ=True,
        DEFAULT_AUTO_FIELD="django.db.models.AutoField",
    )
django.setup()

import django_ninja_admin
from django_ninja_admin import (
    ModelAdmin,
    NinjaAdminSite,
    ShowFacets,
    TabularInline,
    action,
    display,
    site,
)

package_file = Path(django_ninja_admin.__file__).resolve()
install_root = Path({str(install_dir)!r}).resolve()
assert str(package_file).startswith(str(install_root)), package_file
assert (package_file.parent / "py.typed").is_file()
assert django_ninja_admin.site is site
assert NinjaAdminSite is not None
assert ModelAdmin is not None
assert ShowFacets.ALLOW.value == "ALLOW"
assert TabularInline is not None
assert callable(action)
assert callable(display)

metadata = importlib.metadata.metadata("django-ninja-admin")
requires = metadata.get_all("Requires-Dist") or []
for dependency in requires:
    lowered = dependency.lower()
    assert "djangorestframework" not in lowered
    assert "drf-spectacular" not in lowered
"""
        run([sys.executable, "-c", smoke_code], cwd=tmp_path, env=env)


if __name__ == "__main__":
    main()
