from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the installed sample project smoke checks.")
    parser.add_argument("--full", action="store_true", help="Run the fuller sample project acceptance flow.")
    return parser.parse_args(argv)


def run_sample_project(
    write_project: Callable[[Path], None],
    *,
    smoke_script_name: str,
    temp_prefix: str,
    check_name: str,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(f"uv is required to run the {check_name}.")

    with tempfile.TemporaryDirectory(prefix=temp_prefix) as tmp:
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

        write_project(project_dir)
        run([str(python), str(project_dir / smoke_script_name)], cwd=project_dir)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.full:
        run_sample_project(
            write_full_sample_project,
            smoke_script_name="sample_full.py",
            temp_prefix="django-ninja-admin-full-sample-",
            check_name="full sample project check",
        )
        return

    run_sample_project(
        write_sample_project,
        smoke_script_name="sample_smoke.py",
        temp_prefix="django-ninja-admin-sample-",
        check_name="sample project smoke check",
    )


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


def write_full_sample_project(project_dir: Path) -> None:
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
        from django.urls import reverse


        class Category(models.Model):
            name = models.CharField(max_length=100)

            def __str__(self):
                return self.name


        class Tag(models.Model):
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
            category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="products")
            tags = models.ManyToManyField(Tag, blank=True, related_name="products")
            price = models.DecimalField(max_digits=8, decimal_places=2)
            stock_status = models.CharField(max_length=20, choices=STOCK_CHOICES, default=IN_STOCK)
            manual = models.FileField(upload_to="manuals", blank=True)

            def __str__(self):
                return self.name

            def get_absolute_url(self):
                return reverse("product-detail", kwargs={"pk": self.pk})


        class ProductImage(models.Model):
            product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
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
        from pydantic import ConfigDict

        from django_ninja_admin import ModelAdmin, TabularInline, action, site

        from .models import Category, Product, ProductImage, Tag


        class ClosedSchema(Schema):
            model_config = ConfigDict(extra="forbid")


        class ProductStatsResponse(ClosedSchema):
            count: int


        class StockStatusActionData(ClosedSchema):
            status: Literal["in_stock", "out_of_stock"]
            note: str | None = None


        class StockStatusActionResult(ClosedSchema):
            updated: int
            status: str
            note: str | None = None


        class CategoryAdmin(ModelAdmin):
            list_display = ("name",)
            search_fields = ("name",)


        class TagAdmin(ModelAdmin):
            list_display = ("name",)
            search_fields = ("name",)


        class ProductImageInline(TabularInline):
            model = ProductImage
            extra = 1


        class ProductAdmin(ModelAdmin):
            list_display = ("name", "category", "price", "stock_status")
            list_filter = ("stock_status", "category")
            list_editable = ("stock_status",)
            search_fields = ("name", "category__name")
            autocomplete_fields = ("category",)
            filter_horizontal = ("tags",)
            ordering = ("name",)
            inlines = [ProductImageInline]
            actions = ["set_stock_status"]

            def stats(self, request):
                return {"count": Product.objects.count()}

            def get_urls(self):
                return [
                    self.route(
                        "/stats",
                        self.admin_view(self.stats),
                        response=ProductStatsResponse,
                        operation_id="sample_product_stats",
                        tags=["sample.product"],
                    )
                ]

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
        site.register(Tag, TagAdmin)
        site.register(Product, ProductAdmin)
        """,
    )
    write_file(
        project_dir / "sample_project" / "settings.py",
        """
        SECRET_KEY = "sample-full"
        DEBUG = True
        ROOT_URLCONF = "sample_project.urls"
        USE_TZ = True
        DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
        SITE_ID = 1
        MEDIA_URL = "/media/"
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
            "django.contrib.sites",
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
        from django.http import HttpResponse
        from django.urls import path
        from django_ninja_admin import autodiscover, site

        autodiscover()


        def product_detail(request, pk):
            return HttpResponse(f"product {pk}")


        urlpatterns = [
            path("admin-api/", site.urls),
            path("products/<int:pk>/", product_detail, name="product-detail"),
        ]
        """,
    )
    write_file(
        project_dir / "sample_full.py",
        """
        import json
        import os

        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sample_project.settings")

        import django
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.management import call_command
        from django.test import Client

        django.setup()

        from django.contrib.contenttypes.models import ContentType
        from django.contrib.sites.models import Site
        from sample_app.models import Category, Product, ProductImage, Tag


        def assert_status(response, status):
            assert response.status_code == status, response.content


        call_command("migrate", interactive=False, run_syncdb=True, verbosity=0)
        Site.objects.update_or_create(pk=1, defaults={"domain": "example.test", "name": "Sample"})

        cameras = Category.objects.create(name="Cameras")
        lenses = Category.objects.create(name="Lenses")
        featured = Tag.objects.create(name="Featured")
        clearance = Tag.objects.create(name="Clearance")
        existing = Product.objects.create(
            name="Existing camera",
            category=cameras,
            price="12.50",
            stock_status=Product.IN_STOCK,
        )
        existing.tags.set([featured])
        ProductImage.objects.create(product=existing, title="Front")

        user = get_user_model().objects.create_user("admin", password="pw", is_staff=True, is_superuser=True)
        client = Client()
        client.force_login(user)

        docs = client.get("/admin-api/docs")
        assert_status(docs, 200)

        schema = client.get("/admin-api/openapi.json")
        assert_status(schema, 200)
        paths = schema.json()["paths"]
        assert "/admin-api/sample_app/product" in paths
        assert "/admin-api/sample_app/product/multipart" in paths
        assert "/admin-api/sample_app/product/stats" in paths

        context = client.get("/admin-api/context")
        assert_status(context, 200)
        assert context.json()["has_permission"] is True

        apps = client.get("/admin-api/apps")
        assert_status(apps, 200)
        assert any(app["app_label"] == "sample_app" for app in apps.json())

        permissions = client.get("/admin-api/permissions")
        assert_status(permissions, 200)
        assert any(
            item["app_label"] == "sample_app" and item["model_name"] == "product"
            for item in permissions.json()["models"]
        )

        add_form = client.get("/admin-api/sample_app/product/form")
        assert_status(add_form, 200)
        fields_by_name = {field["name"]: field for field in add_form.json()["form"]["fields"]}
        assert fields_by_name["category"]["attrs"]["admin_widget"] == "autocomplete"
        assert fields_by_name["tags"]["attrs"]["admin_widget"] == "filter_horizontal"
        assert fields_by_name["tags"]["attrs"]["filtered_select"]["url"] == "/admin-api/sample_app/tag"
        assert fields_by_name["tags"]["attrs"]["filtered_select"]["query"] == {"_to_field": "id"}
        assert fields_by_name["manual"]["attrs"]["needs_multipart_form"] is True
        inline = next(item for item in add_form.json()["inlines"] if item["model"] == "sample_app.productimage")
        assert inline["formset_prefix"] == "images"
        assert inline["empty_form"]

        create = client.post(
            "/admin-api/sample_app/product",
            data={
                "data": {
                    "name": "Created camera",
                    "category": cameras.pk,
                    "tags": [featured.pk, clearance.pk],
                    "price": "29.95",
                    "stock_status": Product.IN_STOCK,
                },
                "inlines": {"sample_app.productimage": {"add": [{"title": "Created front"}]}},
            },
            content_type="application/json",
        )
        assert_status(create, 201)
        created_id = create.json()["data"]["id"]
        assert ProductImage.objects.filter(product_id=created_id, title="Created front").exists()

        multipart = client.post(
            "/admin-api/sample_app/product/multipart",
            data={
                "data": json.dumps(
                    {
                        "name": "Manual camera",
                        "category": lenses.pk,
                        "tags": [featured.pk],
                        "price": "39.95",
                        "stock_status": Product.IN_STOCK,
                    }
                ),
                "manual": SimpleUploadedFile("manual.txt", b"manual", content_type="text/plain"),
            },
        )
        assert_status(multipart, 201)
        manual_id = multipart.json()["data"]["id"]
        assert Product.objects.get(pk=manual_id).manual.name.startswith("manuals/manual")

        change_form = client.get(f"/admin-api/sample_app/product/{created_id}/form")
        assert_status(change_form, 200)
        change_fields_by_name = {field["name"]: field for field in change_form.json()["form"]["fields"]}
        assert change_fields_by_name["category"]["attrs"]["selected_options"] == [
            {
                "id": str(cameras.pk),
                "text": "Cameras",
                "detail_url": f"/admin-api/sample_app/category/{cameras.pk}",
                "change_form_url": f"/admin-api/sample_app/category/{cameras.pk}/form",
            }
        ]
        tag_options = {
            item["text"]: item for item in change_fields_by_name["tags"]["attrs"]["selected_options"]
        }
        assert set(tag_options) == {"Featured", "Clearance"}
        for tag in [featured, clearance]:
            assert tag_options[tag.name]["detail_url"] == f"/admin-api/sample_app/tag/{tag.pk}"
            assert tag_options[tag.name]["change_form_url"] == f"/admin-api/sample_app/tag/{tag.pk}/form"

        autocomplete = client.get(
            "/admin-api/autocomplete",
            {"app_label": "sample_app", "model_name": "product", "field_name": "category", "term": "Cam"},
        )
        assert_status(autocomplete, 200)
        assert autocomplete.json()["results"] == [{"id": str(cameras.pk), "text": "Cameras"}]

        changelist = client.get("/admin-api/sample_app/product", {"q": "camera", "stock_status__exact": "in_stock"})
        assert_status(changelist, 200)
        assert changelist.json()["config"]["result_count"] >= 3
        assert changelist.json()["list_editing_formset_prefix"] == "form"
        assert any(
            field["name"] == "stock_status"
            for row in changelist.json()["list_editing_formset"]
            for field in row
        )

        bulk = client.put(
            "/admin-api/sample_app/product/bulk",
            data={"data": [{"pk": created_id, "stock_status": Product.OUT_OF_STOCK}]},
            content_type="application/json",
        )
        assert_status(bulk, 200)
        assert Product.objects.get(pk=created_id).stock_status == Product.OUT_OF_STOCK

        action = client.post(
            "/admin-api/sample_app/product/actions",
            data={
                "action": "set_stock_status",
                "selected_ids": [created_id],
                "data": {"status": Product.IN_STOCK, "note": "full sample"},
            },
            content_type="application/json",
        )
        assert_status(action, 200)
        assert action.json() == {"updated": 1, "status": Product.IN_STOCK, "note": "full sample"}
        assert Product.objects.get(pk=created_id).stock_status == Product.IN_STOCK

        stats = client.get("/admin-api/sample_app/product/stats")
        assert_status(stats, 200)
        assert stats.json()["count"] == Product.objects.count()

        history = client.get("/admin-api/history", {"app_label": "sample_app", "model": "product"})
        assert_status(history, 200)
        assert history.json()["pagination"]["count"] >= 1

        content_type = ContentType.objects.get_for_model(Product)
        view_on_site = client.get(f"/admin-api/view-on-site/{content_type.pk}/{created_id}")
        assert_status(view_on_site, 200)
        assert view_on_site.json() == {"url": f"http://example.test/products/{created_id}/"}
        """,
    )


if __name__ == "__main__":
    main()
