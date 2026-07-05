from django.urls import path
from ninja import Schema, Status
from ninja.security import APIKeyHeader
from ninja.throttling import BaseThrottle
from pydantic import ConfigDict

from django_ninja_admin import ModelAdmin, NinjaAdminSite, action
from django_ninja_admin.schemas import ErrorResponse
from tests.testapp.models import Category, CategoryLimitedLink, CategorySlugLink, Product, ProductReview


class ClosedSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class ProductStatsResponse(ClosedSchema):
    count: int


class ProductThresholdPayload(ClosedSchema):
    minimum_price: int


class SiteStatusResponse(ClosedSchema):
    site: str


class SiteEchoPayload(ClosedSchema):
    message: str
    repeat: int = 1


class SiteEchoResponse(ClosedSchema):
    echoed: list[str]


class PublicStatusResponse(ClosedSchema):
    public: str


class AuthStatusResponse(ClosedSchema):
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

    def no_content_stats(self, request):
        return Status(204, None)

    def threshold_stats(self, request, payload: ProductThresholdPayload):
        return {"count": Product.objects.filter(price__gte=payload.minimum_price).count()}

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
            self.route(
                "/no-content-stats",
                self.admin_view(self.no_content_stats),
                response={204: None},
                operation_id="custom_product_no_content_stats",
                tags=["custom.product"],
            ),
            self.route(
                "/threshold-stats",
                self.admin_view(self.threshold_stats),
                methods="POST",
                response=ProductStatsResponse,
                operation_id="custom_product_threshold_stats",
                tags=["custom.product"],
            ),
            decorated_stats,
        ]


class NoActionsProductAdmin(ModelAdmin):
    list_display = ("name",)
    actions = None


class SearchableCategoryAdmin(ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


class EditableSlugCategoryAdmin(SearchableCategoryAdmin):
    list_display_links = ("slug",)
    list_editable = ("name",)
    ordering = ("slug",)
    actions = ("mark_reviewed",)

    @action(description="Mark selected categories reviewed", permissions=["change"])
    def mark_reviewed(self, request, queryset):
        queryset.update(name="Reviewed")


class CategorySlugLinkAdmin(ModelAdmin):
    list_display = ("name", "category")
    autocomplete_fields = ("category",)


class CategoryLimitedLinkAdmin(ModelAdmin):
    list_display = ("name", "category")
    autocomplete_fields = ("category",)


class ReverseAutocompleteProductAdmin(ModelAdmin):
    list_display = ("name",)
    autocomplete_fields = ("reviews",)


class SearchableReviewAdmin(ModelAdmin):
    list_display = ("note",)
    search_fields = ("note",)


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

    def string_method_status(self, request):
        return {"site": "string-method"}

    def token_status(self, request):
        return {"auth": request.auth}

    def public_status(self, request):
        return {"public": "ok"}

    def default_status(self, request):
        return {"site": "default", "metadata": {"source": "default-response"}}

    def no_content_status(self, request):
        return Status(204, None)

    def echo_status(self, request, payload: SiteEchoPayload):
        return {"echoed": [payload.message] * payload.repeat}

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
                "/string-method-status",
                self.admin_view(self.string_method_status),
                methods="post",
                response=SiteStatusResponse,
                operation_id="custom_string_method_status",
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
                "/no-content-status",
                self.admin_view(self.no_content_status),
                response={204: None},
                operation_id="custom_no_content_status",
                tags=["custom.site"],
            ),
            self.route(
                "/echo-status",
                self.admin_view(self.echo_status),
                methods="POST",
                response=SiteEchoResponse,
                operation_id="custom_echo_status",
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

reverse_autocomplete_site = NinjaAdminSite(name="reverse_autocomplete_admin", include_auth=False)
reverse_autocomplete_site.register(Product, ReverseAutocompleteProductAdmin)
reverse_autocomplete_site.register(ProductReview, SearchableReviewAdmin)


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
    changelist_throttle = [OneRequestPerPathThrottle()]


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
                throttle=[OneRequestPerPathThrottle()],
            )
        ]


throttled_site = ThrottledAdminSite(
    name="throttled_admin",
    auth=None,
    include_auth=False,
    history_throttle=[OneRequestPerPathThrottle()],
    autocomplete_throttle=[OneRequestPerPathThrottle()],
)
throttled_site.register(Category, SearchableCategoryAdmin)
throttled_site.register(Product, ThrottledProductAdmin)

no_actions_site = NinjaAdminSite(name="no_actions_admin", include_auth=False)
no_actions_site.register(Product, NoActionsProductAdmin)


urlpatterns = [
    path("custom-admin/", custom_site.urls),
    path("slug-autocomplete-admin/", slug_autocomplete_site.urls),
    path("slug-editable-admin/", slug_editable_site.urls),
    path("reverse-autocomplete-admin/", reverse_autocomplete_site.urls),
    path("multi-auth-admin/", multi_auth_site.urls),
    path("context-admin/", context_site.urls),
    path("locked-context-admin/", locked_context_site.urls),
    path("public-permissions-admin/", public_permissions_site.urls),
    path("auth-models-admin/", auth_models_site.urls),
    path("throttled-admin/", throttled_site.urls),
    path("no-actions-admin/", no_actions_site.urls),
]
