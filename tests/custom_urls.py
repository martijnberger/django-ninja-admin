from django.urls import path
from ninja import Schema
from ninja.security import APIKeyHeader
from ninja.throttling import BaseThrottle

from django_ninja_admin import ModelAdmin, NinjaAdminSite
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category, CategoryLimitedLink, CategorySlugLink, Product


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


class OneRequestPerPathThrottle(BaseThrottle):
    def __init__(self):
        self.seen_paths = set()

    def allow_request(self, request):
        if request.path in self.seen_paths:
            return False
        self.seen_paths.add(request.path)
        return True

    def wait(self):
        return 1


class CustomProductAdmin(ModelAdmin):
    list_display = ("name",)

    def stats(self, request):
        return {"count": Product.objects.count()}

    async def async_stats(self, request):
        return {"count": await Product.objects.acount()}

    def auto_stats(self, request):
        return {"count": Product.objects.count()}

    def default_stats(self, request):
        return {"count": Product.objects.count(), "metadata": {"source": "default-response"}}

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
                "/async-stats",
                self.admin_view(self.async_stats),
                response=ProductStatsResponse,
                operation_id="custom_product_async_stats",
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
            self.route(
                "/default-stats",
                self.admin_view(self.default_stats),
                operation_id="custom_product_default_stats",
                tags=["custom.product"],
            ),
            decorated_stats,
        ]


class SearchableCategoryAdmin(ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


class EditableSlugCategoryAdmin(SearchableCategoryAdmin):
    list_display_links = ("slug",)
    list_editable = ("name",)
    ordering = ("slug",)


class CategorySlugLinkAdmin(ModelAdmin):
    list_display = ("name", "category")
    autocomplete_fields = ("category",)


class CategoryLimitedLinkAdmin(ModelAdmin):
    list_display = ("name", "category")
    autocomplete_fields = ("category",)


class CustomAdminSite(NinjaAdminSite):
    def status(self, request):
        return {"site": "ok"}

    async def async_status(self, request):
        return {"site": "async"}

    def auto_status(self, request):
        return {"site": "auto"}

    def mapped_status(self, request):
        return {"site": "mapped"}

    def explicit_multi_status(self, request):
        return {"site": "explicit-multi"}

    def token_status(self, request):
        return {"auth": request.auth}

    def public_status(self, request):
        return {"public": "ok"}

    def default_status(self, request):
        return {"site": "default", "metadata": {"source": "default-response"}}

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
                "/async-status",
                self.admin_view(self.async_status),
                response=SiteStatusResponse,
                operation_id="custom_site_async_status",
                tags=["custom.site"],
            ),
            self.route(
                "/auto-status",
                self.admin_view(self.auto_status),
                response=SiteStatusResponse,
                tags=["custom.site"],
            ),
            self.route(
                "/mapped-status",
                self.admin_view(self.mapped_status),
                response={200: SiteStatusResponse, 418: ErrorResponse},
                operation_id="custom_mapped_status",
                tags=["custom.site"],
            ),
            self.route(
                "/explicit-multi-status",
                self.admin_view(self.explicit_multi_status),
                methods=("GET", "POST"),
                response=SiteStatusResponse,
                operation_id="custom_explicit_multi_status",
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
                "/default-status",
                self.admin_view(self.default_status),
                operation_id="custom_default_status",
                tags=["custom.site"],
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
slug_autocomplete_site.register(CategoryLimitedLink, CategoryLimitedLinkAdmin)

slug_editable_site = NinjaAdminSite(name="slug_editable_admin", include_auth=False)
slug_editable_site.register(Category, EditableSlugCategoryAdmin)
slug_editable_site.register(CategorySlugLink, CategorySlugLinkAdmin)


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


class CustomContextAdminSite(NinjaAdminSite):
    site_title = "Custom Context Title"
    site_header = "Custom Context Header"
    site_url = "/dashboard/"
    enable_nav_sidebar = False


context_site = CustomContextAdminSite(name="context_admin", include_auth=False)
context_site.register(Category, ModelAdmin)


class LockedContextAdminSite(NinjaAdminSite):
    def has_permission(self, request):
        return False


locked_context_site = LockedContextAdminSite(name="locked_context_admin", include_auth=False)


public_permissions_site = NinjaAdminSite(name="public_permissions_admin", auth=None, include_auth=False)
auth_models_site = NinjaAdminSite(name="auth_models_admin", auth=None, include_auth=True)


class ThrottledProductAdmin(ModelAdmin):
    list_display = ("name",)
    autocomplete_fields = ("category",)
    changelist_throttle = OneRequestPerPathThrottle()


class ThrottledAdminSite(NinjaAdminSite):
    def status(self, request):
        return {"site": "limited"}

    def get_urls(self):
        return [
            self.route(
                "/limited-status",
                self.status,
                response=SiteStatusResponse,
                operation_id="throttled_limited_status",
                auth=None,
                throttle=OneRequestPerPathThrottle(),
            )
        ]


throttled_site = ThrottledAdminSite(
    name="throttled_admin",
    auth=None,
    include_auth=False,
    history_throttle=OneRequestPerPathThrottle(),
    autocomplete_throttle=OneRequestPerPathThrottle(),
)
throttled_site.register(Category, SearchableCategoryAdmin)
throttled_site.register(Product, ThrottledProductAdmin)


urlpatterns = [
    path("custom-admin/", custom_site.urls),
    path("slug-autocomplete-admin/", slug_autocomplete_site.urls),
    path("slug-editable-admin/", slug_editable_site.urls),
    path("multi-auth-admin/", multi_auth_site.urls),
    path("context-admin/", context_site.urls),
    path("locked-context-admin/", locked_context_site.urls),
    path("public-permissions-admin/", public_permissions_site.urls),
    path("auth-models-admin/", auth_models_site.urls),
    path("throttled-admin/", throttled_site.urls),
]
