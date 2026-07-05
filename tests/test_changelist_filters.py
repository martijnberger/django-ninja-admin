from datetime import UTC, datetime

import pytest
from django.contrib.admin.options import ModelAdmin as DjangoModelAdmin
from django.contrib.admin.sites import AdminSite as DjangoAdminSite
from django.contrib.auth import get_user_model
from django.db import models
from django.test import RequestFactory, override_settings
from django.test.utils import isolate_apps
from django.utils import timezone

from django_ninja_admin import (
    AllValuesFieldListFilter,
    EmptyFieldListFilter,
    ModelAdmin,
    NinjaAdminSite,
    RelatedOnlyFieldListFilter,
    ShowFacets,
    SimpleListFilter,
    site,
)
from django_ninja_admin.changelist import ChangeList
from tests.testapp.models import Category, CategorySlugLink, Product, ProductImage


def test_changelist_facets_and_date_hierarchy(admin_client, sample):
    alpha_date = datetime(2024, 1, 15, 10, 0, tzinfo=UTC)
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=alpha_date)
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 2, 20, 10, 0, tzinfo=UTC))
    Product.objects.create(
        name="Tripod",
        category=sample.category,
        price="6.00",
        description="Stable",
        created_at=datetime(2025, 3, 5, 10, 0, tzinfo=UTC),
    )

    response = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["show_facets"] is True
    assert body["config"]["facets_optional"] is True
    assert body["config"]["add_facets_query_string"] is None
    assert body["config"]["remove_facets_query_string"] == "?"
    assert body["config"]["has_filters"] is True
    assert body["config"]["has_active_filters"] is False
    assert body["config"]["clear_all_filters_query_string"] is None
    stock_filter = next(item for item in body["config"]["filters"] if item["parameter_name"] == "stock_status__exact")
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["In Stock"] == 2
    assert body["config"]["date_hierarchy"]["level"] == "year"
    assert body["config"]["date_hierarchy"]["field_type"] == "DateTimeField"
    assert body["config"]["date_hierarchy"]["timezone"] == timezone.get_current_timezone_name()
    assert body["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert body["config"]["date_hierarchy"]["back_query_string"] is None
    assert [choice["value"] for choice in body["config"]["date_hierarchy"]["choices"]] == [2024, 2025]

    by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2024&_facets=1")
    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == 2
    assert by_year.json()["config"]["has_active_filters"] is True
    assert by_year.json()["config"]["clear_all_filters_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["remove_facets_query_string"] == "?created_at__year=2024"
    assert by_year.json()["config"]["date_hierarchy"]["level"] == "month"
    assert by_year.json()["config"]["date_hierarchy"]["clear_query_string"] == "?_facets=1"
    assert by_year.json()["config"]["date_hierarchy"]["back_query_string"] == "?_facets=1"
    assert [choice["value"] for choice in by_year.json()["config"]["date_hierarchy"]["choices"]] == [1, 2]

    by_month = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1")
    assert by_month.status_code == 200
    assert by_month.json()["config"]["result_count"] == 1
    assert by_month.json()["config"]["date_hierarchy"]["level"] == "day"
    assert by_month.json()["config"]["date_hierarchy"]["clear_query_string"] == "?"
    assert by_month.json()["config"]["date_hierarchy"]["back_query_string"] == "?created_at__year=2024"
    assert by_month.json()["config"]["date_hierarchy"]["choices"][0]["value"] == 15

    by_day = admin_client.get("/admin-api/testapp/product?created_at__year=2024&created_at__month=1&created_at__day=15")
    assert by_day.status_code == 200
    assert by_day.json()["config"]["date_hierarchy"]["back_query_string"] == (
        "?created_at__year=2024&created_at__month=1"
    )
    assert by_day.json()["config"]["date_hierarchy"]["choices"][0]["selected"] is True

    bad_day = admin_client.get(
        "/admin-api/testapp/product?created_at__year=2024&created_at__month=2&created_at__day=31"
    )
    assert bad_day.status_code == 400
    assert bad_day.json()["errors"] == [{"message": "Invalid day.", "param": "created_at__day"}]


def test_changelist_date_hierarchy_selects_lowest_useful_initial_level(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 2, 20, 10, 0, tzinfo=UTC))

    same_year = admin_client.get("/admin-api/testapp/product")

    assert same_year.status_code == 200
    same_year_hierarchy = same_year.json()["config"]["date_hierarchy"]
    assert same_year_hierarchy["level"] == "month"
    assert same_year_hierarchy["params"] == {"year": 2024}
    assert same_year_hierarchy["clear_query_string"] == "?"
    assert same_year_hierarchy["back_query_string"] == "?"
    assert [(choice["value"], choice["query_string"]) for choice in same_year_hierarchy["choices"]] == [
        (1, "?created_at__year=2024&created_at__month=1"),
        (2, "?created_at__year=2024&created_at__month=2"),
    ]

    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2024, 1, 20, 10, 0, tzinfo=UTC))
    same_month = admin_client.get("/admin-api/testapp/product")

    assert same_month.status_code == 200
    same_month_hierarchy = same_month.json()["config"]["date_hierarchy"]
    assert same_month_hierarchy["level"] == "day"
    assert same_month_hierarchy["params"] == {"year": 2024, "month": 1}
    assert same_month_hierarchy["clear_query_string"] == "?"
    assert same_month_hierarchy["back_query_string"] == "?created_at__year=2024"
    assert [(choice["value"], choice["query_string"]) for choice in same_month_hierarchy["choices"]] == [
        (15, "?created_at__year=2024&created_at__month=1&created_at__day=15"),
        (20, "?created_at__year=2024&created_at__month=1&created_at__day=20"),
    ]


def test_changelist_date_hierarchy_uses_active_timezone(admin_client, sample):
    boundary = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
    Product.objects.all().update(created_at=boundary)

    with timezone.override("America/Los_Angeles"):
        response = admin_client.get("/admin-api/testapp/product")
        by_year = admin_client.get("/admin-api/testapp/product?created_at__year=2023")
        request = RequestFactory().get("/admin-api/testapp/product?created_at__year=2023")
        request.user = get_user_model().objects.get(username="admin")
        changelist = ChangeList(request, site.get_model_admin(Product))
        start, end = changelist.date_hierarchy_bounds({"year": 2023})

    assert response.status_code == 200
    hierarchy = response.json()["config"]["date_hierarchy"]
    assert hierarchy["field_type"] == "DateTimeField"
    assert hierarchy["timezone"] == "America/Los_Angeles"
    assert hierarchy["level"] == "day"
    assert hierarchy["params"] == {"year": 2023, "month": 12}
    assert [choice["value"] for choice in hierarchy["choices"]] == [31]

    assert by_year.status_code == 200
    assert by_year.json()["config"]["result_count"] == Product.objects.count()
    by_year_hierarchy = by_year.json()["config"]["date_hierarchy"]
    assert by_year_hierarchy["timezone"] == "America/Los_Angeles"
    assert by_year_hierarchy["level"] == "month"
    assert [choice["value"] for choice in by_year_hierarchy["choices"]] == [12]
    assert start.isoformat() == "2023-01-01T00:00:00-08:00"
    assert end.isoformat() == "2024-01-01T00:00:00-08:00"


def test_changelist_date_hierarchy_handles_max_year_bounds(admin_client, sample):
    year = admin_client.get("/admin-api/testapp/product?created_at__year=9999")
    day = admin_client.get("/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31")

    assert year.status_code == 200
    assert year.json()["config"]["result_count"] == 0
    assert day.status_code == 200
    assert day.json()["config"]["result_count"] == 0

    request = RequestFactory().get(
        "/admin-api/testapp/product?created_at__year=9999&created_at__month=12&created_at__day=31"
    )
    request.user = get_user_model().objects.get(username="admin")
    changelist = ChangeList(request, site.get_model_admin(Product))
    start, end = changelist.date_hierarchy_bounds({"year": 9999, "month": 12, "day": 31})

    assert start.isoformat().startswith("9999-12-31T00:00:00")
    assert end is None


def test_changelist_show_facets_modes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.NEVER)
    never = admin_client.get("/admin-api/testapp/product?_facets=1")
    assert never.status_code == 200
    assert never.json()["config"]["show_facets"] is False
    assert never.json()["config"]["facets_optional"] is False
    assert never.json()["config"]["add_facets_query_string"] is None
    assert never.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in never.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert all(choice["count"] is None for choice in stock_filter["choices"])

    monkeypatch.setattr(product_admin, "show_facets", ShowFacets.ALWAYS)
    always = admin_client.get("/admin-api/testapp/product")
    assert always.status_code == 200
    assert always.json()["config"]["show_facets"] is True
    assert always.json()["config"]["facets_optional"] is False
    assert always.json()["config"]["add_facets_query_string"] is None
    assert always.json()["config"]["remove_facets_query_string"] is None
    stock_filter = next(
        item for item in always.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert {choice["display"]: choice["count"] for choice in stock_filter["choices"]}["Out of Stock"] == 1


def test_changelist_facet_counts_cache_equivalent_query_strings(db, sample, monkeypatch):
    request = RequestFactory().get("/admin-api/testapp/product?_facets=1")
    request.user = get_user_model().objects.create_user(
        "facet-cache-admin",
        password="pw",
        is_staff=True,
        is_superuser=True,
    )
    changelist = ChangeList(request, site.get_model_admin(Product))
    calls = 0

    class CountingQuerySet:
        def count(self):
            return 7

    def get_queryset(params, filter_specs, *, apply_date_hierarchy=True, apply_ordering=True):
        nonlocal calls
        calls += 1
        return CountingQuerySet()

    monkeypatch.setattr(changelist, "get_queryset", get_queryset)

    first = changelist.count_for_query_string("?stock_status__exact=in_stock&price__gte=1&_facets=1&o=1&p=2")
    second = changelist.count_for_query_string("?price__gte=1&stock_status__exact=in_stock")

    assert first == 7
    assert second == 7
    assert calls == 1


def test_changelist_date_hierarchy_supports_relation_paths(admin_client, sample):
    class RelatedDateHierarchyImageAdmin(ModelAdmin):
        date_hierarchy = "product__created_at"
        ordering = ("title",)

    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.filter(pk=beta.pk).update(created_at=datetime(2025, 2, 20, 10, 0, tzinfo=UTC))
    ProductImage.objects.create(product=beta, title="Beta image")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(ProductImage, RelatedDateHierarchyImageAdmin)
    model_admin = admin_site.get_model_admin(ProductImage)
    user = get_user_model().objects.get(username="admin")

    request = RequestFactory().get("/admin-api/testapp/productimage")
    request.user = user
    changelist = ChangeList(request, model_admin)

    description = changelist.date_hierarchy_description()
    assert description["field"] == "product__created_at"
    assert description["field_type"] == "DateTimeField"
    assert description["timezone"] == timezone.get_current_timezone_name()
    assert description["level"] == "year"
    assert [choice["value"] for choice in description["choices"]] == [2024, 2025]

    by_year_request = RequestFactory().get("/admin-api/testapp/productimage?product__created_at__year=2024")
    by_year_request.user = user
    by_year = ChangeList(by_year_request, model_admin)
    by_year_description = by_year.date_hierarchy_description()

    assert by_year.result_count == 1
    assert by_year_description["level"] == "month"
    assert by_year_description["choices"][0]["query_string"] == (
        "?product__created_at__year=2024&product__created_at__month=1"
    )


def test_date_field_list_filter_uses_bounded_ranges(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("created_at",))
    monkeypatch.setattr(
        "django_ninja_admin.filters.timezone.now",
        lambda: datetime(2024, 1, 15, 12, 0, tzinfo=UTC),
    )
    Product.objects.all().update(created_at=datetime(2024, 1, 15, 10, 0, tzinfo=UTC))
    Product.objects.create(
        name="Future",
        category=sample.category,
        price="7.00",
        created_at=datetime(2024, 2, 1, 10, 0, tzinfo=UTC),
    )

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    date_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "created at")
    this_month = next(choice for choice in date_filter["choices"] if choice["display"] == "This month")
    assert "created_at__gte=" in this_month["query_string"]
    assert "created_at__lt=" in this_month["query_string"]

    filtered = admin_client.get(f"/admin-api/testapp/product{this_month['query_string']}")
    assert filtered.status_code == 200
    assert filtered.json()["config"]["result_count"] == 2
    assert [row["cells"]["name"] for row in filtered.json()["rows"]] == ["Alpha", "Beta"]

    repeated_since = admin_client.get(
        "/admin-api/testapp/product",
        {
            "created_at__gte": [
                "2024-02-01 00:00:00+00:00",
                "2025-01-01 00:00:00+00:00",
            ],
        },
    )
    assert repeated_since.status_code == 200
    assert repeated_since.json()["config"]["result_count"] == 1
    assert repeated_since.json()["rows"][0]["cells"]["name"] == "Future"

    hidden_invalid_since = admin_client.get(
        "/admin-api/testapp/product",
        {
            "created_at__gte": [
                "not-a-date",
                "2024-01-01 00:00:00+00:00",
            ],
        },
    )
    assert hidden_invalid_since.status_code == 400
    assert hidden_invalid_since.json()["errors"] == [{"message": "Invalid lookup value.", "param": "created_at__gte"}]

    stale_response = admin_client.get(
        "/admin-api/testapp/product",
        {
            "created_at__gte": "2023-01-01 00:00:00+00:00",
            "created_at__lt": "2023-02-01 00:00:00+00:00",
        },
    )
    stale_filter = next(item for item in stale_response.json()["config"]["filters"] if item["title"] == "created at")
    stale_any_date = next(choice for choice in stale_filter["choices"] if choice["display"] == "Any date")
    stale_this_month = next(choice for choice in stale_filter["choices"] if choice["display"] == "This month")
    assert stale_any_date["query_string"] == "?"
    assert "2023" not in stale_this_month["query_string"]


def test_changelist_allows_local_field_lookup_suffixes(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?price__gte=10")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert response.json()["rows"][0]["cells"]["name"] == "Alpha"


def _lookup_allowed_decisions(model, lookup, value, *, list_filter=()):
    request = RequestFactory().get(f"/admin-api/{model._meta.app_label}/{model._meta.model_name}")
    admin_attrs = {"list_filter": list_filter}
    NinjaModelAdmin = type("NinjaLookupAdmin", (ModelAdmin,), admin_attrs)
    DjangoModelAdminClass = type("DjangoLookupAdmin", (DjangoModelAdmin,), admin_attrs)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(model, NinjaModelAdmin)
    ninja_admin = admin_site.get_model_admin(model)
    django_admin = DjangoModelAdminClass(model, DjangoAdminSite())

    return (
        ninja_admin.lookup_allowed(lookup, value, request),
        django_admin.lookup_allowed(lookup, value, request),
    )


@pytest.mark.parametrize(
    ("model", "lookup", "value", "list_filter", "expected"),
    [
        pytest.param(Product, "price__gte", "10", (), True, id="local-transform"),
        pytest.param(Product, "missing__exact", "x", (), True, id="missing-field-deferred"),
        pytest.param(Product, "category__id__exact", "1", (), True, id="remote-primary-key"),
        pytest.param(CategorySlugLink, "category__slug__exact", "cameras", (), True, id="remote-to-field"),
        pytest.param(Product, "category__slug__exact", "cameras", (), False, id="undeclared-remote-non-pk"),
        pytest.param(Product, "category__slug__exact", "cameras", ("category__slug",), True, id="declared-relation"),
        pytest.param(Product, "category__products__name", "Alpha", (), False, id="suspicious-multihop"),
    ],
)
def test_lookup_allowed_matches_django_admin_for_relation_edge_cases(model, lookup, value, list_filter, expected):
    ninja_allowed, django_allowed = _lookup_allowed_decisions(
        model,
        lookup,
        value,
        list_filter=list_filter,
    )

    assert ninja_allowed is expected
    assert ninja_allowed == django_allowed


@isolate_apps("tests.testapp")
def test_lookup_allowed_honors_limit_choices_to_relation_lookups(db):
    class LimitedCategory(models.Model):
        name = models.CharField(max_length=100)

        class Meta:
            app_label = "testapp"

    class LimitedProduct(models.Model):
        category = models.ForeignKey(LimitedCategory, on_delete=models.CASCADE)

        class Meta:
            app_label = "testapp"

    class LimitedImage(models.Model):
        product = models.ForeignKey(
            LimitedProduct,
            on_delete=models.CASCADE,
            limit_choices_to={"category__name": "Cameras"},
        )

        class Meta:
            app_label = "testapp"

    class LimitedProductAdmin(ModelAdmin):
        list_filter = ()

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(LimitedProduct, LimitedProductAdmin)
    model_admin = admin_site.get_model_admin(LimitedProduct)
    request = RequestFactory().get("/admin-api/testapp/limitedproduct")

    assert model_admin.lookup_allowed("category__name", "Cameras", request) is True
    assert model_admin.lookup_allowed("category__name", "Accessories", request) is False


def test_changelist_rejects_bad_lookup_page_and_ordering(admin_client, sample):
    bad_lookup = admin_client.get("/admin-api/testapp/product?category__name=Cameras")
    assert bad_lookup.status_code == 400

    bad_filter_value = admin_client.get("/admin-api/testapp/product?category__id__exact=not-an-id")
    assert bad_filter_value.status_code == 400
    assert bad_filter_value.json()["errors"] == [{"message": "Invalid lookup value.", "param": "category__id__exact"}]

    bad_direct_value = admin_client.get("/admin-api/testapp/product?price=not-a-decimal")
    assert bad_direct_value.status_code == 400
    assert bad_direct_value.json()["errors"] == [{"message": "Invalid lookup value.", "param": "price"}]

    bad_page = admin_client.get("/admin-api/testapp/product?page=0")
    assert bad_page.status_code == 422
    assert bad_page.json()["errors"] == [
        {"message": "String should match pattern '^(last|[1-9][0-9]*)$'", "param": "query.page"}
    ]

    bad_short_page = admin_client.get("/admin-api/testapp/product?p=0")
    assert bad_short_page.status_code == 422
    assert bad_short_page.json()["errors"] == [
        {"message": "String should match pattern '^(last|[1-9][0-9]*)$'", "param": "query.p"}
    ]

    bad_page_size = admin_client.get("/admin-api/testapp/product?pp=0")
    assert bad_page_size.status_code == 422
    assert bad_page_size.json()["errors"] == [
        {"message": "Input should be greater than or equal to 1", "param": "query.pp"}
    ]

    excessive_page_size = admin_client.get("/admin-api/testapp/product?pp=201")
    assert excessive_page_size.status_code == 422
    assert excessive_page_size.json()["errors"] == [
        {"message": "Input should be less than or equal to 200", "param": "query.pp"}
    ]

    bad_ordering = admin_client.get("/admin-api/testapp/product?o=999")
    assert bad_ordering.status_code == 400

    malformed_ordering = admin_client.get("/admin-api/testapp/product?o=1,,2")
    assert malformed_ordering.status_code == 422
    ordering_pattern = r"^-?(?:\d+|[A-Za-z_][A-Za-z0-9_]*)(?:[,.]-?(?:\d+|[A-Za-z_][A-Za-z0-9_]*))*$"
    assert malformed_ordering.json()["errors"] == [
        {
            "message": f"String should match pattern '{ordering_pattern}'",
            "param": "query.o",
        }
    ]

    bad_date_hierarchy = admin_client.get("/admin-api/testapp/product?created_at__month=2")
    assert bad_date_hierarchy.status_code == 400

    hidden_bad_date_hierarchy = admin_client.get(
        "/admin-api/testapp/product",
        {"created_at__year": ["not-a-year", "2024"]},
    )
    assert hidden_bad_date_hierarchy.status_code == 400
    assert hidden_bad_date_hierarchy.json()["errors"] == [{"message": "Invalid year.", "param": "created_at__year"}]

    hidden_bad_page = admin_client.get("/admin-api/testapp/product", {"p": ["0", "1"]})
    assert hidden_bad_page.status_code == 400
    assert hidden_bad_page.json()["errors"] == [{"message": "Invalid page.", "param": "p"}]

    hidden_bad_page_alias = admin_client.get("/admin-api/testapp/product", {"page": ["0", "1"]})
    assert hidden_bad_page_alias.status_code == 400
    assert hidden_bad_page_alias.json()["errors"] == [{"message": "Invalid page.", "param": "page"}]

    hidden_bad_page_size = admin_client.get("/admin-api/testapp/product", {"pp": ["201", "1"]})
    assert hidden_bad_page_size.status_code == 400
    assert hidden_bad_page_size.json()["errors"] == [{"message": "Page size must be at most 200.", "param": "pp"}]

    hidden_malformed_ordering = admin_client.get("/admin-api/testapp/product", {"o": ["1,,2", "1"]})
    assert hidden_malformed_ordering.status_code == 400
    assert hidden_malformed_ordering.json()["errors"] == [{"message": "Invalid ordering.", "param": "o"}]

    hidden_bad_show_all = admin_client.get("/admin-api/testapp/product", {"all": ["maybe", "1"]})
    assert hidden_bad_show_all.status_code == 400
    assert hidden_bad_show_all.json()["errors"] == [{"message": "Invalid boolean value.", "param": "all"}]

    hidden_bad_facets = admin_client.get("/admin-api/testapp/product", {"_facets": ["maybe", "1"]})
    assert hidden_bad_facets.status_code == 400
    assert hidden_bad_facets.json()["errors"] == [{"message": "Invalid boolean value.", "param": "_facets"}]


@override_settings(ROOT_URLCONF="tests.custom_urls")
def test_related_list_filters_use_remote_to_field_values(admin_client, monkeypatch):
    from tests.custom_urls import slug_autocomplete_site

    Category.objects.create(name="Cameras", slug="cameras")
    Category.objects.create(name="Accessories", slug="accessories")
    Category.objects.create(name="Unused", slug="unused")
    CategorySlugLink.objects.create(name="Camera link", category_id="cameras")
    CategorySlugLink.objects.create(name="Accessory link", category_id="accessories")
    link_admin = slug_autocomplete_site.get_model_admin(CategorySlugLink)

    monkeypatch.setattr(link_admin, "list_filter", ("category",))
    response = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink")

    assert response.status_code == 200
    category_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in category_filter["choices"]}
    assert choices_by_display["Cameras"]["query_string"] == "?category__slug__exact=cameras"
    assert choices_by_display["Accessories"]["query_string"] == "?category__slug__exact=accessories"
    assert choices_by_display["Unused"]["query_string"] == "?category__slug__exact=unused"

    filtered = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink?category__slug__exact=cameras")

    assert filtered.status_code == 200
    assert [row["cells"]["name"] for row in filtered.json()["rows"]] == ["Camera link"]
    filtered_category_filter = next(
        item for item in filtered.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    assert (
        next(choice for choice in filtered_category_filter["choices"] if choice["display"] == "Cameras")["selected"]
        is True
    )

    monkeypatch.setattr(link_admin, "list_filter", (("category", RelatedOnlyFieldListFilter),))
    related_only = admin_client.get("/slug-autocomplete-admin/testapp/categorysluglink")

    assert related_only.status_code == 200
    related_only_filter = next(
        item for item in related_only.json()["config"]["filters"] if item["parameter_name"] == "category__slug__exact"
    )
    related_only_choices = {choice["display"]: choice for choice in related_only_filter["choices"]}
    assert {"Cameras", "Accessories"}.issubset(related_only_choices)
    assert "Unused" not in related_only_choices
    assert related_only_choices["Cameras"]["query_string"] == "?category__slug__exact=cameras"


def test_choices_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    Product.objects.filter(pk=sample.pk).update(condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["Unspecified"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["New"]["query_string"] == "?condition__exact=new"

    unspecified = admin_client.get("/admin-api/testapp/product?condition__isnull=1")
    assert unspecified.status_code == 200
    unspecified_body = unspecified.json()
    assert unspecified_body["config"]["result_count"] == 1
    assert unspecified_body["rows"][0]["cells"]["name"] == "Beta"
    condition_filter = next(
        item for item in unspecified_body["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    selected_unspecified = next(choice for choice in condition_filter["choices"] if choice["display"] == "Unspecified")
    assert selected_unspecified["selected"] is True

    concrete = admin_client.get("/admin-api/testapp/product?condition__exact=new")
    assert concrete.status_code == 200
    assert concrete.json()["config"]["result_count"] == 1
    assert concrete.json()["rows"][0]["cells"]["name"] == "Alpha"


def test_all_values_list_filter_supports_null_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    Product.objects.filter(pk=sample.pk).update(condition="used")
    Product.objects.create(name="Tripod", category=sample.category, price="6.00", condition="new")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    condition_filter = next(item for item in response.json()["config"]["filters"] if item["title"] == "condition")
    choices_by_display = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices_by_display["-"]["query_string"] == "?condition__isnull=1"
    assert choices_by_display["-"]["query_string"] != choices_by_display["All"]["query_string"]

    null_response = admin_client.get(f"/admin-api/testapp/product{choices_by_display['-']['query_string']}")

    assert null_response.status_code == 200
    assert null_response.json()["config"]["result_count"] == 1
    condition_filter = next(item for item in null_response.json()["config"]["filters"] if item["title"] == "condition")
    null_choice = next(choice for choice in condition_filter["choices"] if choice["display"] == "-")
    assert null_choice["selected"] is True


def test_list_filters_reject_invalid_isnull_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    choices_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert choices_response.status_code == 400
    assert choices_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", ("category",))
    related_response = admin_client.get("/admin-api/testapp/product?category__isnull=maybe")
    assert related_response.status_code == 400
    assert related_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "category__isnull"}]

    monkeypatch.setattr(product_admin, "list_filter", (("condition", AllValuesFieldListFilter),))
    all_values_response = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert all_values_response.status_code == 400
    assert all_values_response.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]

    hidden_invalid = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe&condition__isnull=1")
    assert hidden_invalid.status_code == 400
    assert hidden_invalid.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]


def test_field_list_filters_or_repeated_values_and_validate_each(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(condition="new")
    Product.objects.filter(pk=beta.pk).update(condition="used")

    monkeypatch.setattr(product_admin, "list_filter", ("condition",))
    repeated_choices = admin_client.get("/admin-api/testapp/product?condition__exact=new&condition__exact=used")

    assert repeated_choices.status_code == 200
    assert repeated_choices.json()["config"]["result_count"] == 2
    assert {row["cells"]["name"] for row in repeated_choices.json()["rows"]} == {"Alpha", "Beta"}
    condition_filter = next(
        item for item in repeated_choices.json()["config"]["filters"] if item["parameter_name"] == "condition__exact"
    )
    choices = {choice["display"]: choice for choice in condition_filter["choices"]}
    assert choices["New"]["selected"] is True
    assert choices["Used"]["selected"] is True

    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=accessories, price="6.00")

    monkeypatch.setattr(product_admin, "list_filter", ("category",))
    repeated_related = admin_client.get(
        f"/admin-api/testapp/product?category__id__exact={sample.category_id}&category__id__exact={accessories.pk}"
    )

    assert repeated_related.status_code == 200
    assert repeated_related.json()["config"]["result_count"] == 3
    assert {row["cells"]["name"] for row in repeated_related.json()["rows"]} == {"Alpha", "Beta", "Tripod"}
    category_filter = next(
        item for item in repeated_related.json()["config"]["filters"] if item["parameter_name"] == "category__id__exact"
    )
    category_choices = {choice["display"]: choice for choice in category_filter["choices"]}
    assert category_choices["Cameras"]["selected"] is True
    assert category_choices["Accessories"]["selected"] is True

    hidden_invalid_related = admin_client.get(
        f"/admin-api/testapp/product?category__id__exact=not-an-id&category__id__exact={sample.category_id}"
    )
    assert hidden_invalid_related.status_code == 400
    assert hidden_invalid_related.json()["errors"] == [
        {"message": "Invalid lookup value.", "param": "category__id__exact"}
    ]


def test_changelist_direct_lookup_params_prepare_in_and_isnull_values(admin_client, sample):
    beta = Product.objects.get(name="Beta")
    Product.objects.filter(pk=sample.pk).update(condition="new")

    repeated_scalar = admin_client.get("/admin-api/testapp/product?price=12.50&price=3.00")
    assert repeated_scalar.status_code == 200
    assert repeated_scalar.json()["config"]["result_count"] == 2
    assert {row["cells"]["name"] for row in repeated_scalar.json()["rows"]} == {"Alpha", "Beta"}

    blank_scalar = admin_client.get("/admin-api/testapp/product?description=")
    assert blank_scalar.status_code == 200
    assert blank_scalar.json()["config"]["result_count"] == 1
    assert blank_scalar.json()["rows"][0]["cells"]["name"] == "Beta"

    in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk},{beta.pk}")

    assert in_lookup.status_code == 200
    assert in_lookup.json()["config"]["result_count"] == 2

    repeated_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk}")
    assert repeated_in_lookup.status_code == 200
    assert repeated_in_lookup.json()["config"]["result_count"] == 2

    mixed_in_lookup = admin_client.get(f"/admin-api/testapp/product?id__in={sample.pk}&id__in={beta.pk},999999")
    assert mixed_in_lookup.status_code == 200
    assert mixed_in_lookup.json()["config"]["result_count"] == 2

    non_null = admin_client.get("/admin-api/testapp/product?condition__isnull=0")
    assert non_null.status_code == 200
    assert non_null.json()["config"]["result_count"] == 1
    assert non_null.json()["rows"][0]["cells"]["name"] == "Alpha"

    empty_is_false = admin_client.get("/admin-api/testapp/product?condition__isnull=")
    assert empty_is_false.status_code == 200
    assert empty_is_false.json()["config"]["result_count"] == 1
    assert empty_is_false.json()["rows"][0]["cells"]["name"] == "Alpha"

    null = admin_client.get("/admin-api/testapp/product?condition__isnull=true")
    assert null.status_code == 200
    assert null.json()["config"]["result_count"] == 1
    assert null.json()["rows"][0]["cells"]["name"] == "Beta"

    hidden_invalid_scalar = admin_client.get("/admin-api/testapp/product?price=not-a-decimal&price=12.50")
    assert hidden_invalid_scalar.status_code == 400
    assert hidden_invalid_scalar.json()["errors"] == [{"message": "Invalid lookup value.", "param": "price"}]

    invalid_in = admin_client.get("/admin-api/testapp/product?id__in=not-a-number")
    assert invalid_in.status_code == 400
    assert invalid_in.json()["errors"] == [{"message": "Invalid lookup value.", "param": "id__in"}]

    invalid_isnull = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe")
    assert invalid_isnull.status_code == 400
    assert invalid_isnull.json()["errors"] == [{"message": "Invalid lookup value.", "param": "condition__isnull"}]

    hidden_invalid_isnull = admin_client.get("/admin-api/testapp/product?condition__isnull=maybe&condition__isnull=1")
    assert hidden_invalid_isnull.status_code == 400
    assert hidden_invalid_isnull.json()["errors"] == [
        {"message": "Invalid lookup value.", "param": "condition__isnull"}
    ]


def test_empty_field_list_filter_validates_values(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (("description", EmptyFieldListFilter),))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    description_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "description__isempty"
    )
    choices_by_display = {choice["display"]: choice for choice in description_filter["choices"]}
    assert choices_by_display["Empty"]["query_string"] == "?description__isempty=1"
    assert choices_by_display["Not empty"]["query_string"] == "?description__isempty=0"

    empty = admin_client.get("/admin-api/testapp/product?description__isempty=1")
    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"

    not_empty = admin_client.get("/admin-api/testapp/product?description__isempty=0")
    assert not_empty.status_code == 200
    assert not_empty.json()["config"]["result_count"] == 1
    assert not_empty.json()["rows"][0]["cells"]["name"] == "Alpha"

    repeated = admin_client.get("/admin-api/testapp/product?description__isempty=1&description__isempty=0")
    assert repeated.status_code == 200
    assert repeated.json()["config"]["result_count"] == 2
    description_filter = next(
        item for item in repeated.json()["config"]["filters"] if item["parameter_name"] == "description__isempty"
    )
    repeated_choices = {choice["display"]: choice for choice in description_filter["choices"]}
    assert repeated_choices["Empty"]["selected"] is True
    assert repeated_choices["Not empty"]["selected"] is True

    invalid = admin_client.get("/admin-api/testapp/product?description__isempty=maybe")
    assert invalid.status_code == 400
    assert invalid.json()["errors"] == [{"message": "Invalid lookup value.", "param": "description__isempty"}]

    hidden_invalid = admin_client.get("/admin-api/testapp/product?description__isempty=maybe&description__isempty=1")
    assert hidden_invalid.status_code == 400
    assert hidden_invalid.json()["errors"] == [{"message": "Invalid lookup value.", "param": "description__isempty"}]


def test_simple_list_filter_without_lookups_is_hidden(admin_client, sample, monkeypatch):
    class HiddenFilter(SimpleListFilter):
        title = "hidden"
        parameter_name = "hidden"

        def lookups(self, request, model_admin):
            return ()

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", (HiddenFilter,))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_related_field_list_filter_includes_many_to_many_empty_choice(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_filter", ("tags",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    tag_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact"
    )
    choices_by_display = {choice["display"]: choice for choice in tag_filter["choices"]}
    assert choices_by_display["None"]["query_string"] == "?tags__isnull=1"

    empty = admin_client.get("/admin-api/testapp/product?tags__isnull=1")

    assert empty.status_code == 200
    assert empty.json()["config"]["result_count"] == 1
    assert empty.json()["rows"][0]["cells"]["name"] == "Beta"
    tag_filter = next(item for item in empty.json()["config"]["filters"] if item["parameter_name"] == "tags__id__exact")
    selected_none = next(choice for choice in tag_filter["choices"] if choice["display"] == "None")
    assert selected_none["selected"] is True


def test_related_only_list_filter_honors_related_admin_ordering(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    category_admin = site.get_model_admin(Category)
    zooms = Category.objects.create(name="Zooms")
    Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=zooms, price="6.00", description="Stable")
    monkeypatch.setattr(product_admin, "list_filter", (("category", RelatedOnlyFieldListFilter),))
    monkeypatch.setattr(category_admin, "ordering", ("-name",))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    category_filter = next(
        item for item in response.json()["config"]["filters"] if item["parameter_name"] == "category__id__exact"
    )
    choices = [choice["display"] for choice in category_filter["choices"] if choice["display"] != "All"]
    assert choices == ["Zooms", "Cameras"]
