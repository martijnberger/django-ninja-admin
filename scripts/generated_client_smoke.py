from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from smoke_utils import build_or_resolve_wheel, smoke_uv_env

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
                *smoke_django_requirements(),
                str(wheel),
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

            def get_absolute_url(self):
                return f"/products/{self.pk}/"


        class ProductImage(models.Model):
            product = models.ForeignKey(Product, on_delete=models.CASCADE)
            title = models.CharField(max_length=100)

            def __str__(self):
                return self.title
        """,
    )
    write_file(
        project_dir / "sample_app" / "admin.py",
        """
        from typing import Literal

        from ninja import Schema

        from django_ninja_admin import ModelAdmin, TabularInline, action, site

        from .models import Category, Product, ProductImage


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


        class ProductImageInline(TabularInline):
            model = ProductImage
            extra = 0


        class ProductAdmin(ModelAdmin):
            list_display = ("name", "category", "price", "stock_status")
            list_editable = ("stock_status",)
            search_fields = ("name",)
            autocomplete_fields = ("category",)
            actions = ["set_stock_status"]
            inlines = [ProductImageInline]

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
        ALLOWED_HOSTS = ["testserver"]
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
            "django.middleware.csrf.CsrfViewMiddleware",
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
        from urllib.parse import urlencode

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sample_project.settings")

        import django
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.test import Client

        django.setup()

        from django.contrib.contenttypes.models import ContentType

        from sample_app.models import Category, Product, ProductImage


        class OpenAPIConsumer:
            def __init__(self, client, schema):
                self.client = client
                self.schema = schema
                self.operations = {}
                self.path_parameters = {}
                self.query_parameters = {}
                self.parameter_schemas = {}
                for path, path_item in schema["paths"].items():
                    for method, operation in path_item.items():
                        if method.lower() not in {"delete", "get", "patch", "post", "put"}:
                            continue
                        operation_id = operation.get("operationId")
                        if operation_id:
                            self.operations[operation_id] = (method.upper(), path, operation)
                            parameters = operation.get("parameters", [])
                            self.path_parameters[operation_id] = {
                                parameter["name"] for parameter in parameters if parameter.get("in") == "path"
                            }
                            self.query_parameters[operation_id] = {
                                parameter["name"] for parameter in parameters if parameter.get("in") == "query"
                            }
                            self.parameter_schemas[operation_id] = {
                                parameter["name"]: parameter["schema"] for parameter in parameters
                            }

            def request(self, operation_id, *, path_params=None, payload=None, query=None, headers=None):
                method, path, _operation = self.operations[operation_id]
                path_params = path_params or {}
                headers = headers or {}
                unknown_path_params = set(path_params) - self.path_parameters[operation_id]
                if unknown_path_params:
                    raise AssertionError(f"Unknown path params for {operation_id}: {sorted(unknown_path_params)}")
                missing_path_params = self.path_parameters[operation_id] - set(path_params)
                if missing_path_params:
                    raise AssertionError(f"Missing path params for {operation_id}: {sorted(missing_path_params)}")
                for name, value in (path_params or {}).items():
                    path = path.replace("{" + name + "}", str(value))
                if query:
                    unknown_query_params = set(query) - self.query_parameters[operation_id]
                    if unknown_query_params:
                        raise AssertionError(
                            f"Unknown query params for {operation_id}: {sorted(unknown_query_params)}"
                        )
                    path = f"{path}?{urlencode(query, doseq=True)}"
                if payload is None:
                    return self.client.generic(method, path, **headers)
                return self.client.generic(
                    method,
                    path,
                    data=json.dumps(payload),
                    content_type="application/json",
                    **headers,
                )

            def assert_response_matches_schema(self, operation_id, response):
                schema = self.response_schema(operation_id, response.status_code)
                if schema is None:
                    return
                self.validate_schema(schema, response.json(), path=f"{operation_id}.{response.status_code}")

            def response_schema(self, operation_id, status_code):
                _method, _path, operation = self.operations[operation_id]
                response = operation["responses"].get(str(status_code))
                if response is None:
                    raise AssertionError(f"{operation_id} does not advertise HTTP {status_code}")
                media_type = response.get("content", {}).get("application/json")
                if media_type is None:
                    return None
                return media_type.get("schema")

            def resolve_schema(self, schema):
                ref = schema.get("$ref")
                if ref is None:
                    return schema
                prefix = "#/components/schemas/"
                if not ref.startswith(prefix):
                    raise AssertionError(f"Unsupported schema ref: {ref}")
                return self.schema["components"]["schemas"][ref.removeprefix(prefix)]

            def validate_schema(self, schema, value, *, path):
                schema = self.resolve_schema(schema)
                if "anyOf" in schema:
                    failures = []
                    for option in schema["anyOf"]:
                        try:
                            self.validate_schema(option, value, path=path)
                            return
                        except AssertionError as exc:
                            failures.append(str(exc))
                    raise AssertionError(f"{path} did not match anyOf: {failures}")
                for option in schema.get("allOf", []):
                    self.validate_schema(option, value, path=path)
                if "allOf" in schema and "type" not in schema and "properties" not in schema:
                    return
                if "enum" in schema and value not in schema["enum"]:
                    raise AssertionError(f"{path} expected one of {schema['enum']!r}, got {value!r}")
                json_type = schema.get("type")
                if json_type is None and "properties" in schema:
                    json_type = "object"
                if json_type == "null":
                    if value is not None:
                        raise AssertionError(f"{path} expected null, got {type(value).__name__}")
                    return
                if json_type == "object":
                    if not isinstance(value, dict):
                        raise AssertionError(f"{path} expected object, got {type(value).__name__}")
                    properties = schema.get("properties", {})
                    for field_name in schema.get("required", []):
                        if field_name not in value:
                            raise AssertionError(f"{path} missing required field {field_name!r}")
                    for field_name, field_value in value.items():
                        if field_name in properties:
                            self.validate_schema(properties[field_name], field_value, path=f"{path}.{field_name}")
                            continue
                        additional = schema.get("additionalProperties", True)
                        if additional is False:
                            raise AssertionError(f"{path} unexpected field {field_name!r}")
                        if isinstance(additional, dict):
                            self.validate_schema(additional, field_value, path=f"{path}.{field_name}")
                    return
                if json_type == "array":
                    if not isinstance(value, list):
                        raise AssertionError(f"{path} expected array, got {type(value).__name__}")
                    item_schema = schema.get("items")
                    if item_schema is not None:
                        for index, item in enumerate(value):
                            self.validate_schema(item_schema, item, path=f"{path}[{index}]")
                    return
                if json_type == "string":
                    if not isinstance(value, str):
                        raise AssertionError(f"{path} expected string, got {type(value).__name__}")
                    return
                if json_type == "integer":
                    if not isinstance(value, int) or isinstance(value, bool):
                        raise AssertionError(f"{path} expected integer, got {type(value).__name__}")
                    return
                if json_type == "number":
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        raise AssertionError(f"{path} expected number, got {type(value).__name__}")
                    return
                if json_type == "boolean":
                    if not isinstance(value, bool):
                        raise AssertionError(f"{path} expected boolean, got {type(value).__name__}")
                    return
                if json_type is not None:
                    raise AssertionError(f"{path} has unsupported schema type {json_type!r}")

            def example(self, operation_id, name):
                _method, _path, operation = self.operations[operation_id]
                return operation["requestBody"]["content"]["application/json"]["examples"][name]["value"].copy()

            def parameter_type(self, operation_id, name):
                schema = self.parameter_schemas[operation_id][name]
                variants = schema.get("anyOf", [schema])
                return [variant["type"] for variant in variants if variant.get("type") != "null"]

            def non_null_parameter_schema(self, operation_id, name):
                schema = self.parameter_schemas[operation_id][name]
                variants = schema.get("anyOf", [schema])
                return next(variant for variant in variants if variant.get("type") != "null")


        call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
        category = Category.objects.create(name="Cameras")
        Product.objects.create(name="Existing product", category=category, price="12.50")

        user = get_user_model().objects.create_user("admin", password="pw", is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(user)

        schema_response = client.get("/admin-api/openapi.json")
        assert schema_response.status_code == 200, schema_response.content
        consumer = OpenAPIConsumer(client, schema_response.json())
        anonymous_consumer = OpenAPIConsumer(Client(), schema_response.json())

        expected_operations = {
            "admin_context",
            "admin_csrf",
            "admin_login",
            "admin_logout",
            "admin_permissions",
            "admin_list_apps",
            "admin_get_app",
            "admin_history",
            "admin_autocomplete",
            "admin_view_on_site",
            "sample_app_product_list",
            "sample_app_product_create",
            "sample_app_product_detail",
            "sample_app_product_partial_update",
            "sample_app_product_update",
            "sample_app_product_delete",
            "sample_app_product_bulk_update",
            "sample_app_product_action",
            "sample_app_product_change_form",
        }
        assert expected_operations <= set(consumer.operations)
        assert consumer.path_parameters["admin_get_app"] == {"app_label"}
        assert {"app_label", "model", "object_id", "action_flag", "o", "page", "per_page"} <= consumer.query_parameters[
            "admin_history"
        ]
        assert {"app_label", "model_name", "field_name", "term", "page"} <= consumer.query_parameters[
            "admin_autocomplete"
        ]
        assert consumer.path_parameters["admin_view_on_site"] == {"content_type_id", "object_id"}
        assert {"q", "o", "p", "page", "pp", "all", "_facets", "_to_field"} <= consumer.query_parameters[
            "sample_app_product_list"
        ]
        assert consumer.parameter_type("sample_app_product_list", "pp") == ["integer"]
        assert consumer.parameter_type("sample_app_product_list", "all") == ["boolean"]
        assert consumer.parameter_type("sample_app_product_list", "_facets") == ["boolean"]
        assert consumer.non_null_parameter_schema("sample_app_product_list", "p")["pattern"] == (
            r"^(last|[1-9][0-9]*)$"
        )
        assert consumer.non_null_parameter_schema("sample_app_product_list", "page")["pattern"] == (
            r"^(last|[1-9][0-9]*)$"
        )
        assert consumer.non_null_parameter_schema("sample_app_product_list", "pp")["minimum"] == 1
        assert consumer.parameter_schemas["admin_history"]["page"]["minimum"] == 1
        assert consumer.parameter_schemas["admin_history"]["per_page"]["minimum"] == 1
        assert consumer.parameter_schemas["admin_history"]["per_page"]["maximum"] == 100
        assert consumer.parameter_schemas["admin_autocomplete"]["page"]["minimum"] == 1
        components = consumer.schema["components"]["schemas"]
        assert components["CategoryAdminInlineResponse"]["additionalProperties"] is False
        assert components["ProductAdminInlineResponse"]["propertyNames"] == {"const": "sample_app.productimage"}
        assert components["ProductAdminInlineResponse"]["additionalProperties"] == {
            "$ref": "#/components/schemas/ProductImageInlineOperationResults"
        }
        assert components["ActionResponse"]["additionalProperties"] is False
        assert consumer.path_parameters["sample_app_product_detail"] == {"object_id"}
        assert "_to_field" in consumer.query_parameters["sample_app_product_detail"]

        unauthorized_response = anonymous_consumer.request("sample_app_product_list")
        assert unauthorized_response.status_code == 401, unauthorized_response.content
        anonymous_consumer.assert_response_matches_schema("sample_app_product_list", unauthorized_response)

        browser_client = Client(enforce_csrf_checks=True)
        browser_consumer = OpenAPIConsumer(browser_client, schema_response.json())
        csrf_response = browser_consumer.request("admin_csrf")
        assert csrf_response.status_code == 200, csrf_response.content
        browser_consumer.assert_response_matches_schema("admin_csrf", csrf_response)
        csrf_token = csrf_response.json()["csrf_token"]
        assert csrf_token

        bad_login_response = browser_consumer.request(
            "admin_login",
            payload={"username": "admin", "password": "wrong"},
            headers={"HTTP_X_CSRFTOKEN": csrf_token},
        )
        assert bad_login_response.status_code == 400, bad_login_response.content
        browser_consumer.assert_response_matches_schema("admin_login", bad_login_response)

        login_response = browser_consumer.request(
            "admin_login",
            payload={"username": "admin", "password": "pw"},
            headers={"HTTP_X_CSRFTOKEN": csrf_token},
        )
        assert login_response.status_code == 200, login_response.content
        browser_consumer.assert_response_matches_schema("admin_login", login_response)
        login_body = login_response.json()
        assert login_body["is_authenticated"] is True
        assert login_body["has_permission"] is True

        browser_create_payload = consumer.example("sample_app_product_create", "create")
        browser_create_payload["data"].update(
            {
                "name": "Browser session product",
                "category": category.pk,
                "price": "29.95",
                "stock_status": "in_stock",
            }
        )
        browser_create_payload["inlines"] = {}
        browser_create_response = browser_consumer.request(
            "sample_app_product_create",
            payload=browser_create_payload,
            headers={"HTTP_X_CSRFTOKEN": login_body["csrf_token"]},
        )
        assert browser_create_response.status_code == 201, browser_create_response.content
        browser_consumer.assert_response_matches_schema("sample_app_product_create", browser_create_response)
        assert browser_create_response.json()["data"]["name"] == "Browser session product"

        logout_response = browser_consumer.request(
            "admin_logout",
            headers={"HTTP_X_CSRFTOKEN": login_body["csrf_token"]},
        )
        assert logout_response.status_code == 200, logout_response.content
        browser_consumer.assert_response_matches_schema("admin_logout", logout_response)
        assert logout_response.json()["is_authenticated"] is False

        context_response = consumer.request("admin_context")
        assert context_response.status_code == 200, context_response.content
        consumer.assert_response_matches_schema("admin_context", context_response)
        assert context_response.json()["has_permission"] is True

        permissions_response = consumer.request("admin_permissions")
        assert permissions_response.status_code == 200, permissions_response.content
        consumer.assert_response_matches_schema("admin_permissions", permissions_response)
        assert permissions_response.json()["has_permission"] is True

        apps_response = consumer.request("admin_list_apps")
        assert apps_response.status_code == 200, apps_response.content
        consumer.assert_response_matches_schema("admin_list_apps", apps_response)
        assert any(app["app_label"] == "sample_app" for app in apps_response.json())

        app_response = consumer.request("admin_get_app", path_params={"app_label": "sample_app"})
        assert app_response.status_code == 200, app_response.content
        consumer.assert_response_matches_schema("admin_get_app", app_response)
        assert app_response.json()["app_label"] == "sample_app"

        autocomplete_response = consumer.request(
            "admin_autocomplete",
            query={
                "app_label": "sample_app",
                "model_name": "product",
                "field_name": "category",
                "term": "Cam",
                "page": 1,
            },
        )
        assert autocomplete_response.status_code == 200, autocomplete_response.content
        consumer.assert_response_matches_schema("admin_autocomplete", autocomplete_response)
        assert autocomplete_response.json()["results"] == [{"id": str(category.pk), "text": "Cameras"}]

        list_response = consumer.request("sample_app_product_list", query={"q": "Existing", "pp": 1, "_facets": 1})
        assert list_response.status_code == 200, list_response.content
        consumer.assert_response_matches_schema("sample_app_product_list", list_response)
        assert list_response.json()["config"]["result_count"] == 1
        assert list_response.json()["config"]["per_page"] == 1

        missing_response = consumer.request("sample_app_product_detail", path_params={"object_id": 999999})
        assert missing_response.status_code == 404, missing_response.content
        consumer.assert_response_matches_schema("sample_app_product_detail", missing_response)

        create_payload = consumer.example("sample_app_product_create", "create")
        invalid_create_payload = {"data": {**create_payload["data"], "category": 999999}}
        invalid_create_response = consumer.request("sample_app_product_create", payload=invalid_create_payload)
        assert invalid_create_response.status_code == 400, invalid_create_response.content
        consumer.assert_response_matches_schema("sample_app_product_create", invalid_create_response)

        create_payload["data"].update(
            {
                "name": "Created from OpenAPI",
                "category": category.pk,
                "price": "19.95",
                "stock_status": "in_stock",
            }
        )
        create_payload["inlines"] = {"sample_app.productimage": {"add": [{"title": "Inline from OpenAPI"}]}}
        created_response = consumer.request("sample_app_product_create", payload=create_payload)
        assert created_response.status_code == 201, created_response.content
        consumer.assert_response_matches_schema("sample_app_product_create", created_response)
        created = created_response.json()["data"]
        product_id = created["id"]
        assert created["name"] == "Created from OpenAPI"
        created_inline = created_response.json()["inlines"]["sample_app.productimage"]["add"][0]
        assert created_inline["title"] == "Inline from OpenAPI"
        image_id = created_inline["id"]

        detail_response = consumer.request("sample_app_product_detail", path_params={"object_id": product_id})
        assert detail_response.status_code == 200, detail_response.content
        consumer.assert_response_matches_schema("sample_app_product_detail", detail_response)
        assert detail_response.json()["id"] == product_id

        patch_payload = consumer.example("sample_app_product_partial_update", "partial_update")
        patch_payload["data"] = {"name": "Patched from OpenAPI"}
        patch_payload.pop("inlines", None)
        patched_response = consumer.request(
            "sample_app_product_partial_update",
            path_params={"object_id": product_id},
            payload=patch_payload,
        )
        assert patched_response.status_code == 200, patched_response.content
        consumer.assert_response_matches_schema("sample_app_product_partial_update", patched_response)
        assert patched_response.json()["data"]["name"] == "Patched from OpenAPI"

        update_payload = consumer.example("sample_app_product_update", "update")
        update_payload["data"].update(
            {
                "name": "Updated from OpenAPI",
                "category": category.pk,
                "price": "24.95",
                "stock_status": "in_stock",
            }
        )
        update_payload["inlines"] = {
            "sample_app.productimage": {"change": [{"pk": image_id, "title": "Inline changed from OpenAPI"}]}
        }
        updated_response = consumer.request(
            "sample_app_product_update",
            path_params={"object_id": product_id},
            payload=update_payload,
        )
        assert updated_response.status_code == 200, updated_response.content
        consumer.assert_response_matches_schema("sample_app_product_update", updated_response)
        assert updated_response.json()["data"]["name"] == "Updated from OpenAPI"
        assert updated_response.json()["inlines"]["sample_app.productimage"]["change"][0]["title"] == (
            "Inline changed from OpenAPI"
        )
        assert ProductImage.objects.get(pk=image_id).title == "Inline changed from OpenAPI"

        bulk_payload = consumer.example("sample_app_product_bulk_update", "bulk_update")
        bulk_payload["data"] = [{"pk": product_id, "stock_status": "out_of_stock"}]
        bulk_response = consumer.request("sample_app_product_bulk_update", payload=bulk_payload)
        assert bulk_response.status_code == 200, bulk_response.content
        consumer.assert_response_matches_schema("sample_app_product_bulk_update", bulk_response)
        assert bulk_response.json()["data"]["0"]["stock_status"] == "out_of_stock"

        action_payload = consumer.example("sample_app_product_action", "action")
        action_payload.update(
            {
                "action": "set_stock_status",
                "selected_ids": [product_id],
                "data": {"status": "in_stock", "note": "schema consumer"},
            }
        )
        invalid_action_payload = {**action_payload, "data": {"status": "not_a_stock_status"}}
        invalid_action_response = consumer.request("sample_app_product_action", payload=invalid_action_payload)
        assert invalid_action_response.status_code == 422, invalid_action_response.content
        consumer.assert_response_matches_schema("sample_app_product_action", invalid_action_response)

        action_response = consumer.request("sample_app_product_action", payload=action_payload)
        assert action_response.status_code == 200, action_response.content
        consumer.assert_response_matches_schema("sample_app_product_action", action_response)
        assert action_response.json() == {"updated": 1, "status": "in_stock", "note": "schema consumer"}
        assert Product.objects.get(pk=product_id).stock_status == "in_stock"

        form_response = consumer.request("sample_app_product_change_form", path_params={"object_id": product_id})
        assert form_response.status_code == 200, form_response.content
        consumer.assert_response_matches_schema("sample_app_product_change_form", form_response)
        assert form_response.json()["form"]["model"] == "sample_app.product"

        history_response = consumer.request(
            "admin_history",
            query={"app_label": "sample_app", "model": "product", "object_id": product_id, "per_page": 5},
        )
        assert history_response.status_code == 200, history_response.content
        consumer.assert_response_matches_schema("admin_history", history_response)
        assert history_response.json()["pagination"]["count"] >= 1
        assert all(item["model"] == "sample_app.product" for item in history_response.json()["results"])

        product_content_type = ContentType.objects.get_for_model(Product)
        view_on_site_response = consumer.request(
            "admin_view_on_site",
            path_params={"content_type_id": product_content_type.pk, "object_id": product_id},
        )
        assert view_on_site_response.status_code == 200, view_on_site_response.content
        consumer.assert_response_matches_schema("admin_view_on_site", view_on_site_response)
        assert view_on_site_response.json()["url"].endswith(f"/products/{product_id}/")

        delete_response = consumer.request("sample_app_product_delete", path_params={"object_id": product_id})
        assert delete_response.status_code == 204, delete_response.content
        consumer.assert_response_matches_schema("sample_app_product_delete", delete_response)
        assert not Product.objects.filter(pk=product_id).exists()
        assert not ProductImage.objects.filter(pk=image_id).exists()
        """,
    )


if __name__ == "__main__":
    main()
