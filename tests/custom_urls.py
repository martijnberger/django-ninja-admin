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
            )
        ]


class CustomAdminSite(NinjaAdminSite):
    def status(self, request):
        return {"site": "ok"}

    def get_urls(self):
        return [
            self.route(
                "/status",
                self.admin_view(self.status),
                response=dict[str, str],
                operation_id="custom_site_status",
            )
        ]


custom_site = CustomAdminSite(name="custom_admin", include_auth=False)
custom_site.register(Category, ModelAdmin)
custom_site.register(Product, CustomProductAdmin)

urlpatterns = [
    path("custom-admin/", custom_site.urls),
]
