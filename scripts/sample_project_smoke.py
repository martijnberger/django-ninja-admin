from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def write_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the sample project smoke check.")

    with tempfile.TemporaryDirectory(prefix="django-ninja-admin-sample-") as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        project_dir = tmp_path / "project"
        venv_dir = tmp_path / ".venv"
        uv_env = os.environ.copy()
        smoke_cache_dir = Path(tempfile.gettempdir()) / "django-ninja-admin-uv-cache"
        uv_env["UV_CACHE_DIR"] = os.environ.get("DJANGO_NINJA_ADMIN_SMOKE_UV_CACHE", str(smoke_cache_dir))

        run([uv, "build", "--wheel", "--out-dir", str(dist_dir)], env=uv_env)
        wheels = sorted(dist_dir.glob("django_ninja_admin-*.whl"))
        if not wheels:
            raise SystemExit("No django-ninja-admin wheel was built.")

        run([uv, "venv", "--python", sys.executable, str(venv_dir)], env=uv_env)
        python = venv_python(venv_dir)
        run([uv, "pip", "install", "--python", str(python), str(wheels[-1])], env=uv_env)

        write_sample_project(project_dir)
        run([str(python), str(project_dir / "sample_smoke.py")], cwd=project_dir)


def write_sample_project(project_dir: Path) -> None:
    write_file(project_dir / "sample_project" / "__init__.py", "")
    write_file(project_dir / "sample_app" / "__init__.py", "")
    write_file(
        project_dir / "sample_app" / "apps.py",
        """
        from django.apps import AppConfig


        class SampleAppConfig(AppConfig):
            default_auto_field = "django.db.models.BigAutoField"
            name = "sample_app"
        """,
    )
    write_file(
        project_dir / "sample_app" / "models.py",
        """
        from django.db import models


        class Product(models.Model):
            name = models.CharField(max_length=100)
            price = models.DecimalField(max_digits=8, decimal_places=2)

            def __str__(self):
                return self.name
        """,
    )
    write_file(
        project_dir / "sample_app" / "admin.py",
        """
        from django_ninja_admin import ModelAdmin, site

        from .models import Product


        class ProductAdmin(ModelAdmin):
            list_display = ("name", "price")
            search_fields = ("name",)
            ordering = ("name",)


        site.register(Product, ProductAdmin)
        """,
    )
    write_file(
        project_dir / "sample_project" / "settings.py",
        """
        SECRET_KEY = "sample-smoke"
        DEBUG = True
        ROOT_URLCONF = "sample_project.urls"
        USE_TZ = True
        DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": "db.sqlite3",
            }
        }
        INSTALLED_APPS = [
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "django_ninja_admin",
            "sample_app.apps.SampleAppConfig",
        ]
        MIDDLEWARE = [
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ]
        TEMPLATES = [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ],
                },
            }
        ]
        MIGRATION_MODULES = {"sample_app": None}
        PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
        """,
    )
    write_file(
        project_dir / "sample_project" / "urls.py",
        """
        from django.urls import path
        from django_ninja_admin import autodiscover, site

        autodiscover()

        urlpatterns = [
            path("admin-api/", site.urls),
        ]
        """,
    )
    write_file(
        project_dir / "sample_smoke.py",
        """
        import os

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sample_project.settings")

        import django
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.test import Client

        django.setup()

        from sample_app.models import Product

        call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
        Product.objects.create(name="Demo product", price="12.50")

        user = get_user_model().objects.create_user("admin", password="pw", is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(user)

        docs = client.get("/admin-api/docs")
        assert docs.status_code == 200, docs.content

        schema = client.get("/admin-api/openapi.json")
        assert schema.status_code == 200, schema.content
        paths = schema.json()["paths"]
        assert "/admin-api/sample_app/product" in paths

        apps = client.get("/admin-api/apps")
        assert apps.status_code == 200, apps.content
        assert any(app["app_label"] == "sample_app" for app in apps.json())

        changelist = client.get("/admin-api/sample_app/product")
        assert changelist.status_code == 200, changelist.content
        assert changelist.json()["config"]["result_count"] == 1
        """,
    )


if __name__ == "__main__":
    main()
