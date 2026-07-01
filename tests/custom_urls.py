from django.urls import path
from ninja import Schema
from ninja.security import APIKeyHeader

from django_ninja_admin import ModelAdmin, NinjaAdminSite
from tests.testapp.models import Category, CategorySlugLink, Product


class ProductStatsResponse(Schema):
    count: int


class SiteStatusResponse(Schema):
    site: str


class PublicStatusResponse(Schema):
    public: str


class AuthStatusResponse(Schema):
    auth: str


class PrimaryTokenAuth(APIKeyHeader):
    param_name = "X-Primary-Token"

    def authenticate(self, request, key):
        if key == "primary":
            return "primary"
        return None


class SecondaryTokenAuth(APIKeyHeader):
    param_name = "X-Secondary-Token"

    def authenticate(self, request, key):
        if key == "secondary":
            return "secondary"
        return None


class CustomProductAdmin(ModelAdmin):
    list_display = ("name",)

    def stats(self, request):
        return {"count": Product.objects.count()}

    def auto_stats(self, request):
        return {"count": Product.objects.count()}

    def get_urls(self):
        @self.route(
            "/decorated-stats",
            response=ProductStatsResponse,
            operation_id="custom_product_decorated_stats",
            tags=["custom.product"],
        )
        @self.admin_view
        def decorated_stats(request):
            return {"count": Product.objects.count()}

        return [
            self.route(
                "/stats",
                self.admin_view(self.stats),
                response=ProductStatsResponse,
                operation_id="custom_product_stats",
                summary="Product stats",
                description="Custom product statistics.",
                tags=["custom.product"],
            ),
            self.route(
                "/auto-stats",
                self.admin_view(self.auto_stats),
                response=ProductStatsResponse,
                tags=["custom.product"],
            ),
            self.route(
                "/auto-multi-stats",
                self.admin_view(self.auto_stats),
                methods=("GET", "POST"),
                response=ProductStatsResponse,
                tags=["custom.product"],
            ),
            decorated_stats,
        ]


class SearchableCategoryAdmin(ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


class CategorySlugLinkAdmin(ModelAdmin):
    list_display = ("name", "category")
    autocomplete_fields = ("category",)


class CustomAdminSite(NinjaAdminSite):
    def status(self, request):
        return {"site": "ok"}

    def auto_status(self, request):
        return {"site": "auto"}

    def token_status(self, request):
        return {"auth": request.auth}

    def public_status(self, request):
        return {"public": "ok"}

    def hidden_status(self, request):
        return {"hidden": "ok"}

    def get_urls(self):
        @self.route(
            "/decorated-status",
            response=SiteStatusResponse,
            operation_id="custom_site_decorated_status",
            tags=["custom.site"],
        )
        @self.admin_view
        def decorated_status(request):
            return {"site": "decorated"}

        @self.route(
            "/decorated-auto-status",
            response=SiteStatusResponse,
            tags=["custom.site"],
        )
        @self.admin_view
        def decorated_auto_status(request):
            return {"site": "decorated-auto"}

        return [
            self.route(
                "/status",
                self.admin_view(self.status),
                response=SiteStatusResponse,
                operation_id="custom_site_status",
                tags=["custom.site"],
            ),
            self.route(
                "/auto-status",
                self.admin_view(self.auto_status),
                response=SiteStatusResponse,
                tags=["custom.site"],
            ),
            self.route(
                "/token-status",
                self.token_status,
                response=AuthStatusResponse,
                operation_id="custom_token_status",
                tags=["custom.auth"],
                auth=[PrimaryTokenAuth(), SecondaryTokenAuth()],
            ),
            self.route(
                "/public-status",
                self.public_status,
                response=PublicStatusResponse,
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
            decorated_status,
            decorated_auto_status,
        ]


custom_site = CustomAdminSite(name="custom_admin", include_auth=False)
custom_site.register(Category, ModelAdmin)
custom_site.register(Product, CustomProductAdmin)

slug_autocomplete_site = NinjaAdminSite(name="slug_autocomplete_admin", include_auth=False)
slug_autocomplete_site.register(Category, SearchableCategoryAdmin)
slug_autocomplete_site.register(CategorySlugLink, CategorySlugLinkAdmin)


class MultiAuthAdminSite(NinjaAdminSite):
    def whoami(self, request):
        return {"auth": request.auth}

    def get_urls(self):
        return [
            self.route(
                "/whoami",
                self.whoami,
                response=AuthStatusResponse,
                operation_id="multi_auth_whoami",
                tags=["custom.auth"],
            )
        ]


multi_auth_site = MultiAuthAdminSite(
    name="multi_auth_admin",
    auth=[PrimaryTokenAuth(), SecondaryTokenAuth()],
    include_auth=False,
)

urlpatterns = [
    path("custom-admin/", custom_site.urls),
    path("slug-autocomplete-admin/", slug_autocomplete_site.urls),
    path("multi-auth-admin/", multi_auth_site.urls),
]
