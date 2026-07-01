from django.urls import path

from django_ninja_admin import ModelAdmin, NinjaAdminSite
from tests.testapp.models import Category, Product


class CustomProductAdmin(ModelAdmin):
    list_display = ("name",)

    def stats(self, request):
        return {"count": Product.objects.count()}

    def get_urls(self):
        return [
            self.route(
                "/stats",
                self.admin_view(self.stats),
                response=dict[str, int],
                operation_id="custom_product_stats",
                summary="Product stats",
                description="Custom product statistics.",
                tags=["custom.product"],
            )
        ]


class CustomAdminSite(NinjaAdminSite):
    def status(self, request):
        return {"site": "ok"}

    def public_status(self, request):
        return {"public": "ok"}

    def hidden_status(self, request):
        return {"hidden": "ok"}

    def get_urls(self):
        return [
            self.route(
                "/status",
                self.admin_view(self.status),
                response=dict[str, str],
                operation_id="custom_site_status",
                tags=["custom.site"],
            ),
            self.route(
                "/public-status",
                self.public_status,
                response=dict[str, str],
                operation_id="custom_public_status",
                tags=["custom.public"],
                auth=None,
            ),
            self.route(
                "/hidden-status",
                self.admin_view(self.hidden_status),
                response=dict[str, str],
                operation_id="custom_hidden_status",
                include_in_schema=False,
            ),
        ]


custom_site = CustomAdminSite(name="custom_admin", include_auth=False)
custom_site.register(Category, ModelAdmin)
custom_site.register(Product, CustomProductAdmin)

urlpatterns = [
    path("custom-admin/", custom_site.urls),
]
