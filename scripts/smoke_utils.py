from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEEL_ENV_VAR = "DJANGO_NINJA_ADMIN_WHEEL"


def smoke_uv_env() -> dict[str, str]:
    env = os.environ.copy()
    smoke_cache_dir = Path(tempfile.gettempdir()) / "django-ninja-admin-uv-cache"
    env["UV_CACHE_DIR"] = os.environ.get("DJANGO_NINJA_ADMIN_SMOKE_UV_CACHE", str(smoke_cache_dir))
    return env


def resolve_prebuilt_wheel(env_var: str = WHEEL_ENV_VAR) -> Path | None:
    value = os.environ.get(env_var)
    if not value:
        return None

    path = Path(value)
    if path.is_dir():
        wheels = sorted(path.glob("django_ninja_admin-*.whl"))
        if not wheels:
            raise SystemExit(f"{env_var}={path} does not contain a django-ninja-admin wheel.")
        return wheels[-1].resolve()

    if not path.is_file():
        raise SystemExit(f"{env_var}={path} does not exist.")
    if path.suffix != ".whl" or not path.name.startswith("django_ninja_admin-"):
        raise SystemExit(f"{env_var}={path} is not a django-ninja-admin wheel.")
    return path.resolve()


def build_or_resolve_wheel(uv: str, dist_dir: Path, *, env: dict[str, str]) -> Path:
    prebuilt_wheel = resolve_prebuilt_wheel()
    if prebuilt_wheel is not None:
        return prebuilt_wheel

    subprocess.run([uv, "build", "--wheel", "--out-dir", str(dist_dir)], cwd=ROOT, env=env, check=True)
    wheels = sorted(dist_dir.glob("django_ninja_admin-*.whl"))
    if not wheels:
        raise SystemExit("No django-ninja-admin wheel was built.")
    return wheels[-1]
