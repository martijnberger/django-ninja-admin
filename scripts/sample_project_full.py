from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from sample_project_smoke import run, venv_python, write_file


def main() -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is required to run the full sample project check.")

    with tempfile.TemporaryDirectory(prefix="django-ninja-admin-full-sample-") as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        project_dir = tmp_path / "project"
        venv_dir = tmp_path / ".venv"
        smoke_cache_dir = Path(tempfile.gettempdir()) / "django-ninja-admin-uv-cache"
        uv_env = os.environ.copy()
        uv_env["UV_CACHE_DIR"] = os.environ.get("DJANGO_NINJA_ADMIN_SMOKE_UV_CACHE", str(smoke_cache_dir))

        run([uv, "build", "--wheel", "--out-dir", str(dist_dir)], env=uv_env)
        wheels = sorted(dist_dir.glob("django_ninja_admin-*.whl"))
        if not wheels:
            raise SystemExit("No django-ninja-admin wheel was built.")

        run([uv, "venv", "--python", sys.executable, str(venv_dir)], env=uv_env)
        python = venv_python(venv_dir)
        run([uv, "pip", "install", "--python", str(python), str(wheels[-1])], env=uv_env)

        write_sample_project(project_dir)
        subprocess.run([str(python), str(project_dir / "sample_full.py")], cwd=project_dir, check=True)


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

        from django_ninja_admin import ModelAdmin, TabularInline, action, site

        from .models import Category, Product, ProductImage, Tag


        class ProductStatsResponse(Schema):
            count: int


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
            {"id": str(cameras.pk), "text": "Cameras"}
        ]
        assert {item["text"] for item in change_fields_by_name["tags"]["attrs"]["selected_options"]} == {
            "Featured",
            "Clearance",
        }

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
