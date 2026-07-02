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


def smoke_django_requirements() -> list[str]:
    requirement = os.environ.get("DJANGO_NINJA_ADMIN_SMOKE_DJANGO")
    return [requirement] if requirement else []


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the generated-client smoke check.")

    with tempfile.TemporaryDirectory(prefix="django-ninja-admin-client-") as tmp:
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
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                *smoke_django_requirements(),
                str(wheels[-1]),
            ],
            env=uv_env,
        )

        write_sample_project(project_dir)
        run([str(python), str(project_dir / "generated_client_smoke.py")], cwd=project_dir)


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


        class Category(models.Model):
            name = models.CharField(max_length=100)

            def __str__(self):
                return self.name


        class Product(models.Model):
            IN_STOCK = "in_stock"
            OUT_OF_STOCK = "out_of_stock"
            STOCK_CHOICES = (
                (IN_STOCK, "In stock"),
                (OUT_OF_STOCK, "Out of stock"),
            )

            name = models.CharField(max_length=100)
            category = models.ForeignKey(Category, on_delete=models.CASCADE)
            price = models.DecimalField(max_digits=8, decimal_places=2)
            stock_status = models.CharField(max_length=20, choices=STOCK_CHOICES, default=IN_STOCK)

            def __str__(self):
                return self.name
        """,
    )
    write_file(
        project_dir / "sample_app" / "admin.py",
        """
        from typing import Literal

        from ninja import Schema

        from django_ninja_admin import ModelAdmin, action, site

        from .models import Category, Product


        class StockStatusActionData(Schema):
            status: Literal["in_stock", "out_of_stock"]
            note: str | None = None


        class StockStatusActionResult(Schema):
            updated: int
            status: str
            note: str | None = None


        class CategoryAdmin(ModelAdmin):
            list_display = ("name",)
            search_fields = ("name",)


        class ProductAdmin(ModelAdmin):
            list_display = ("name", "category", "price", "stock_status")
            list_editable = ("stock_status",)
            search_fields = ("name",)
            actions = ["set_stock_status"]

            @action(
                description="Set stock status",
                permissions=["change"],
                input_schema=StockStatusActionData,
                response_schema=StockStatusActionResult,
            )
            def set_stock_status(self, request, queryset, data):
                updated = queryset.update(stock_status=data.status)
                return {"updated": updated, "status": data.status, "note": data.note}


        site.register(Category, CategoryAdmin)
        site.register(Product, ProductAdmin)
        """,
    )
    write_file(
        project_dir / "sample_project" / "settings.py",
        """
        SECRET_KEY = "generated-client-smoke"
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
        project_dir / "generated_client_smoke.py",
        """
        import json
        import os

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sample_project.settings")

        import django
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.test import Client

        django.setup()

        from sample_app.models import Category, Product


        class OpenAPIConsumer:
            def __init__(self, client, schema):
                self.client = client
                self.schema = schema
                self.operations = {}
                for path, path_item in schema["paths"].items():
                    for method, operation in path_item.items():
                        if method.lower() not in {"delete", "get", "patch", "post", "put"}:
                            continue
                        operation_id = operation.get("operationId")
                        if operation_id:
                            self.operations[operation_id] = (method.upper(), path, operation)

            def request(self, operation_id, *, path_params=None, payload=None, query=None):
                method, path, _operation = self.operations[operation_id]
                for name, value in (path_params or {}).items():
                    path = path.replace("{" + name + "}", str(value))
                if query:
                    query_string = "&".join(f"{key}={value}" for key, value in query.items())
                    path = f"{path}?{query_string}"
                if payload is None:
                    return self.client.generic(method, path)
                return self.client.generic(
                    method,
                    path,
                    data=json.dumps(payload),
                    content_type="application/json",
                )

            def example(self, operation_id, name):
                _method, _path, operation = self.operations[operation_id]
                return operation["requestBody"]["content"]["application/json"]["examples"][name]["value"].copy()


        call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
        category = Category.objects.create(name="Cameras")
        Product.objects.create(name="Existing product", category=category, price="12.50")

        user = get_user_model().objects.create_user("admin", password="pw", is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(user)

        schema_response = client.get("/admin-api/openapi.json")
        assert schema_response.status_code == 200, schema_response.content
        consumer = OpenAPIConsumer(client, schema_response.json())

        expected_operations = {
            "sample_app_product_list",
            "sample_app_product_create",
            "sample_app_product_detail",
            "sample_app_product_partial_update",
            "sample_app_product_bulk_update",
            "sample_app_product_action",
            "sample_app_product_change_form",
        }
        assert expected_operations <= set(consumer.operations)

        list_response = consumer.request("sample_app_product_list")
        assert list_response.status_code == 200, list_response.content

        create_payload = consumer.example("sample_app_product_create", "create")
        create_payload["data"].update(
            {
                "name": "Created from OpenAPI",
                "category": category.pk,
                "price": "19.95",
                "stock_status": "in_stock",
            }
        )
        created_response = consumer.request("sample_app_product_create", payload=create_payload)
        assert created_response.status_code == 201, created_response.content
        created = created_response.json()["data"]
        product_id = created["id"]
        assert created["name"] == "Created from OpenAPI"

        detail_response = consumer.request("sample_app_product_detail", path_params={"object_id": product_id})
        assert detail_response.status_code == 200, detail_response.content
        assert detail_response.json()["id"] == product_id

        patch_payload = consumer.example("sample_app_product_partial_update", "partial_update")
        patch_payload["data"] = {"name": "Patched from OpenAPI"}
        patched_response = consumer.request(
            "sample_app_product_partial_update",
            path_params={"object_id": product_id},
            payload=patch_payload,
        )
        assert patched_response.status_code == 200, patched_response.content
        assert patched_response.json()["data"]["name"] == "Patched from OpenAPI"

        bulk_payload = consumer.example("sample_app_product_bulk_update", "bulk_update")
        bulk_payload["data"] = [{"pk": product_id, "stock_status": "out_of_stock"}]
        bulk_response = consumer.request("sample_app_product_bulk_update", payload=bulk_payload)
        assert bulk_response.status_code == 200, bulk_response.content
        assert bulk_response.json()["data"]["0"]["stock_status"] == "out_of_stock"

        action_payload = consumer.example("sample_app_product_action", "action")
        action_payload.update(
            {
                "action": "set_stock_status",
                "selected_ids": [product_id],
                "data": {"status": "in_stock", "note": "schema consumer"},
            }
        )
        action_response = consumer.request("sample_app_product_action", payload=action_payload)
        assert action_response.status_code == 200, action_response.content
        assert action_response.json() == {"updated": 1, "status": "in_stock", "note": "schema consumer"}
        assert Product.objects.get(pk=product_id).stock_status == "in_stock"

        form_response = consumer.request("sample_app_product_change_form", path_params={"object_id": product_id})
        assert form_response.status_code == 200, form_response.content
        assert form_response.json()["form"]["model"] == "sample_app.product"
        """,
    )


if __name__ == "__main__":
    main()
