from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the distribution check.")

    with tempfile.TemporaryDirectory(prefix="django-ninja-admin-dist-") as tmp:
        dist_dir = Path(tmp) / "dist"
        uv_env = os.environ.copy()
        fallback_cache_dir = Path(tempfile.gettempdir()) / "django-ninja-admin-uv-cache"
        uv_env["UV_CACHE_DIR"] = os.environ.get(
            "DJANGO_NINJA_ADMIN_DIST_UV_CACHE",
            os.environ.get("UV_CACHE_DIR", str(fallback_cache_dir)),
        )
        run([uv, "build", "--sdist", "--wheel", "--out-dir", str(dist_dir)], env=uv_env)

        wheels = sorted(dist_dir.glob("*.whl"))
        sdists = sorted(dist_dir.glob("*.tar.gz"))
        if not wheels:
            raise SystemExit("No wheel artifact was built.")
        if not sdists:
            raise SystemExit("No sdist artifact was built.")

        artifacts = [str(path) for path in (*sdists, *wheels)]
        run([sys.executable, "-m", "twine", "check", *artifacts])


if __name__ == "__main__":
    main()
