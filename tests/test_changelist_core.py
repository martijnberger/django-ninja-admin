from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db import connection, models
from django.http import QueryDict
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from django_ninja_admin import ModelAdmin, NinjaAdminSite, display, site
from django_ninja_admin.changelist import ChangeList
from tests.testapp.models import Category, Product, Tag

RENDERED_FIELD_ATTR_KEYS = {
    "aria_describedby",
    "auto_id",
    "bound_subwidgets",
    "clear_checkbox_id",
    "clear_checkbox_name",
    "css_classes",
    "form_prefix",
    "hidden_initial_id",
    "hidden_initial_name",
    "hidden_initial_widget",
    "html_initial_id",
    "html_initial_name",
    "html_name",
    "id_for_label",
    "option_template_name",
    "rendered_attrs",
    "rendered_optgroups",
    "rendered_subwidgets",
    "show_hidden_initial",
    "template_name",
}


def assert_no_rendered_field_attrs(attrs):
    assert RENDERED_FIELD_ATTR_KEYS.isdisjoint(attrs)


def test_changelist_search_filter_and_detail(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["result_count"] == 1
    assert body["config"]["search_term"] == "Alpha"
    assert body["config"]["has_search"] is True
    assert body["config"]["clear_search_query_string"] == "?"
    assert body["rows"][0]["cells"]["name"] == "Alpha"

    filtered = admin_client.get("/admin-api/testapp/product?stock_status=out_of_stock")
    assert filtered.json()["config"]["result_count"] == 1

    exact_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert exact_filtered.status_code == 200
    assert exact_filtered.json()["rows"][0]["cells"]["name"] == "Beta"

    detail = admin_client.get(f"/admin-api/testapp/product/{sample.pk}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Alpha"
    assert detail.json()["category_label"] == "Cameras"
    assert detail.json()["manual"] == {
        "name": "manuals/alpha.pdf",
        "url": "/media/manuals/alpha.pdf",
    }
    assert set(detail.json()["tags"]) == set(sample.tags.values_list("pk", flat=True))


def test_changelist_filters_ordering_pagination_and_show_all(admin_client, sample):
    initial = admin_client.get("/admin-api/testapp/product")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert {item["parameter_name"] for item in initial_body["config"]["filters"]} == {
        "stock_status__exact",
        "price_band",
    }
    assert initial_body["config"]["has_filters"] is True
    assert initial_body["config"]["has_active_filters"] is False
    assert initial_body["config"]["clear_all_filters_query_string"] is None
    assert initial_body["config"]["facets_optional"] is True
    assert initial_body["config"]["add_facets_query_string"] == "?_facets=1"
    assert initial_body["config"]["remove_facets_query_string"] is None
    assert initial_body["config"]["ordering"] == ["name", "-pk"]
    initial_name_column = next(column for column in initial_body["columns"] if column["field"] == "name")
    assert initial_name_column["sorted"] is True
    assert initial_name_column["ascending"] is True
    assert initial_name_column["sort_priority"] == 1
    assert initial_name_column["ascending_query_string"] == "?o=1"
    assert initial_name_column["descending_query_string"] == "?o=-1"
    assert initial_name_column["remove_sorting_query_string"] is None

    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Tripod", category=accessories, price="6.00", description="Stable")

    related_filtered = admin_client.get(f"/admin-api/testapp/product?category__id__exact={sample.category_id}")
    assert related_filtered.status_code == 200
    assert related_filtered.json()["config"]["result_count"] == 2
    assert "category__id__exact" in {item["parameter_name"] for item in related_filtered.json()["config"]["filters"]}

    simple_filtered = admin_client.get("/admin-api/testapp/product?price_band=cheap")
    assert simple_filtered.status_code == 200
    assert [row["cells"]["name"] for row in simple_filtered.json()["rows"]] == ["Beta", "Tripod"]

    choice_filtered = admin_client.get("/admin-api/testapp/product?stock_status__exact=out_of_stock")
    assert choice_filtered.json()["config"]["has_active_filters"] is True
    assert choice_filtered.json()["config"]["clear_all_filters_query_string"] == "?"
    assert choice_filtered.json()["config"]["add_facets_query_string"] == "?stock_status__exact=out_of_stock&_facets=1"
    stock_filter = next(
        item for item in choice_filtered.json()["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    assert any(choice["selected"] and choice["display"] == "Out of Stock" for choice in stock_filter["choices"])
    assert any("stock_status__exact=in_stock" in choice["query_string"] for choice in stock_filter["choices"])

    price_ordered = admin_client.get("/admin-api/testapp/product?o=3")
    assert [row["cells"]["name"] for row in price_ordered.json()["rows"]] == ["Beta", "Tripod", "Alpha"]

    display_ordered = admin_client.get("/admin-api/testapp/product?o=-5")
    assert [row["cells"]["name"] for row in display_ordered.json()["rows"]] == ["Tripod", "Beta", "Alpha"]

    paginated = admin_client.get("/admin-api/testapp/product?pp=1&page=2")
    assert paginated.status_code == 200
    paginated_body = paginated.json()
    assert paginated_body["config"]["page"] == 2
    assert paginated_body["config"]["page_count"] == 3
    assert paginated_body["config"]["pagination"] == {
        "count": 3,
        "num_pages": 3,
        "page": 2,
        "per_page": 1,
        "has_next": True,
        "has_previous": True,
        "more": True,
    }
    assert paginated_body["config"]["has_next"] is True
    assert paginated_body["config"]["has_previous"] is True
    assert paginated_body["config"]["multi_page"] is True
    assert paginated_body["config"]["pagination_required"] is True
    assert paginated_body["config"]["page_range"] == [1, 2, 3]
    assert paginated_body["config"]["page_choices"] == [
        {"display": "1", "page": 1, "selected": False, "query_string": "?pp=1"},
        {"display": "2", "page": 2, "selected": True, "query_string": "?pp=1&p=2"},
        {"display": "3", "page": 3, "selected": False, "query_string": "?pp=1&p=3"},
    ]
    assert len(paginated_body["rows"]) == 1
    assert paginated_body["config"]["page_result_count"] == 1
    assert paginated_body["config"]["result_start_index"] == 2
    assert paginated_body["config"]["result_end_index"] == 2
    assert paginated_body["rows"][0]["index"] == 0
    assert paginated_body["rows"][0]["result_index"] == 2
    assert paginated_body["config"]["first_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["previous_page_query_string"] == "?pp=1"
    assert paginated_body["config"]["next_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["last_page_query_string"] == "?pp=1&p=3"
    assert paginated_body["config"]["show_all_query_string"] == "?pp=1&all=1"
    assert paginated_body["config"]["clear_show_all_query_string"] is None

    generated_query_strings = []
    for filter_description in paginated_body["config"]["filters"]:
        generated_query_strings.extend(choice["query_string"] for choice in filter_description["choices"])
    generated_query_strings.extend(
        column["ascending_query_string"] for column in paginated_body["columns"] if column["ascending_query_string"]
    )
    generated_query_strings.extend(
        choice["query_string"] for choice in paginated_body["config"]["date_hierarchy"]["choices"]
    )
    generated_query_strings.append(paginated_body["config"]["date_hierarchy"]["clear_query_string"])
    for query_string in generated_query_strings:
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params
        assert "p" not in params
    for query_string in (
        paginated_body["config"]["first_page_query_string"],
        paginated_body["config"]["previous_page_query_string"],
        paginated_body["config"]["next_page_query_string"],
        paginated_body["config"]["last_page_query_string"],
        paginated_body["config"]["show_all_query_string"],
        *(choice["query_string"] for choice in paginated_body["config"]["page_choices"] if choice["query_string"]),
    ):
        params = QueryDict(query_string.removeprefix("?"))
        assert "page" not in params

    prefixed_filter = admin_client.get("/admin-api/testapp/product?price__gte=1&pp=1&page=2&o=3")
    assert prefixed_filter.status_code == 200
    prefixed_body = prefixed_filter.json()
    prefixed_price_column = next(column for column in prefixed_body["columns"] if column["field"] == "price")
    assert prefixed_body["config"]["previous_page_query_string"] == "?price__gte=1&pp=1&o=3"
    assert prefixed_body["config"]["next_page_query_string"] == "?price__gte=1&pp=1&o=3&p=3"
    assert prefixed_body["config"]["show_all_query_string"] == "?price__gte=1&pp=1&o=3&all=1"
    assert prefixed_body["config"]["has_active_filters"] is True
    assert prefixed_body["config"]["clear_all_filters_query_string"] == "?pp=1&o=3"
    assert prefixed_body["config"]["search_term"] == ""
    assert prefixed_body["config"]["has_search"] is False
    assert prefixed_body["config"]["clear_search_query_string"] is None
    assert prefixed_price_column["descending_query_string"] == "?price__gte=1&pp=1&o=-3"
    assert prefixed_price_column["remove_sorting_query_string"] == "?price__gte=1&pp=1"
    prefixed_stock_filter = next(
        item for item in prefixed_body["config"]["filters"] if item["parameter_name"] == "stock_status__exact"
    )
    prefixed_stock_choice = next(
        choice for choice in prefixed_stock_filter["choices"] if choice["display"] == "In Stock"
    )
    assert prefixed_stock_choice["query_string"] == "?price__gte=1&pp=1&o=3&stock_status__exact=in_stock"

    searched_with_state = admin_client.get("/admin-api/testapp/product?price__gte=1&q=a&pp=1&page=2&o=3")
    assert searched_with_state.status_code == 200
    assert searched_with_state.json()["config"]["search_term"] == "a"
    assert searched_with_state.json()["config"]["has_search"] is True
    assert searched_with_state.json()["config"]["clear_search_query_string"] == "?price__gte=1&pp=1&o=3"

    last_page = admin_client.get("/admin-api/testapp/product?pp=1&page=last")
    assert last_page.status_code == 200
    assert last_page.json()["config"]["page"] == 3
    assert last_page.json()["rows"][0]["cells"]["name"] == "Tripod"

    show_all = admin_client.get("/admin-api/testapp/product?all=1")
    assert show_all.status_code == 200
    show_all_body = show_all.json()
    assert len(show_all_body["rows"]) == show_all_body["config"]["result_count"]
    assert show_all_body["config"]["full_count"] == 3
    assert show_all_body["config"]["page_result_count"] == 3
    assert show_all_body["config"]["result_start_index"] == 1
    assert show_all_body["config"]["result_end_index"] == 3
    assert show_all_body["config"]["show_all"] is True
    assert show_all_body["config"]["can_show_all"] is True
    assert show_all_body["config"]["pagination_required"] is False
    assert show_all_body["config"]["page_range"] == []
    assert show_all_body["config"]["page_choices"] == []
    assert show_all_body["config"]["first_page_query_string"] is None
    assert show_all_body["config"]["previous_page_query_string"] is None
    assert show_all_body["config"]["next_page_query_string"] is None
    assert show_all_body["config"]["last_page_query_string"] is None
    assert show_all_body["config"]["show_all_query_string"] is None
    assert show_all_body["config"]["clear_show_all_query_string"] == "?"
    assert show_all_body["config"]["list_display_links"] == ["name"]
    assert show_all_body["config"]["actions_on_top"] is True
    assert show_all_body["config"]["actions_on_bottom"] is False
    assert show_all_body["config"]["actions_selection_counter"] is True
    assert show_all_body["config"]["show_full_result_count"] is True
    assert show_all_body["config"]["show_admin_actions"] is True
    assert show_all_body["columns"][0]["display_link"] is True
    assert show_all_body["columns"][2]["sortable"] is True
    assert show_all_body["config"]["search_fields"] == ["name", "description", "category__name"]
    price_column = next(column for column in show_all_body["columns"] if column["field"] == "price")
    assert price_column["ascending_query_string"] == "?all=1&o=3"
    assert price_column["descending_query_string"] == "?all=1&o=-3"
    assert price_column["remove_sorting_query_string"] == "?all=1"
    columns_by_field = {column["field"]: column for column in show_all_body["columns"]}
    assert columns_by_field["has_description"]["boolean"] is True
    assert columns_by_field["tagline"]["empty_value_display"] == "No description"
    assert columns_by_field["is_expensive"]["header_name"] == "Expensive"
    assert columns_by_field["is_expensive"]["boolean"] is True
    assert columns_by_field["subtitle"]["header_name"] == "Subtitle"
    assert columns_by_field["subtitle"]["empty_value_display"] == "No subtitle"
    rows_by_name = {row["cells"]["name"]: row for row in show_all_body["rows"]}
    assert [row["index"] for row in show_all_body["rows"]] == [0, 1, 2]
    assert [row["result_index"] for row in show_all_body["rows"]] == [1, 2, 3]
    alpha_name_cell = rows_by_name["Alpha"]["cell_metadata"]["name"]
    assert alpha_name_cell == {
        "field": "name",
        "header_name": "Name",
        "value": "Alpha",
        "display_value": "Alpha",
        "empty": False,
        "boolean": False,
        "display_link": True,
        "link_url": f"/admin-api/testapp/product/{sample.pk}",
        "sortable": True,
        "ordering_field": "name",
        "editable": False,
        "empty_value_display": "-",
    }
    beta_tagline_cell = rows_by_name["Beta"]["cell_metadata"]["tagline"]
    assert beta_tagline_cell["value"] is None
    assert beta_tagline_cell["display_value"] == "No description"
    assert beta_tagline_cell["empty"] is True
    assert beta_tagline_cell["empty_value_display"] == "No description"
    beta_stock_cell = rows_by_name["Beta"]["cell_metadata"]["stock_status"]
    assert beta_stock_cell["editable"] is True
    assert beta_stock_cell["display_link"] is False
    assert beta_stock_cell["link_url"] is None
    assert rows_by_name["Alpha"]["cells"]["price"] == "12.50"
    assert rows_by_name["Alpha"]["cell_metadata"]["price"]["value"] == "12.50"
    assert rows_by_name["Alpha"]["cell_metadata"]["price"]["display_value"] == "12.50"

    show_all_by_presence = admin_client.get("/admin-api/testapp/product?all=0")
    assert show_all_by_presence.status_code == 200
    show_all_by_presence_body = show_all_by_presence.json()
    assert show_all_by_presence_body["config"]["show_all"] is True
    assert show_all_by_presence_body["config"]["pagination_required"] is False
    assert len(show_all_by_presence_body["rows"]) == show_all_by_presence_body["config"]["result_count"]

    alpha_row = rows_by_name["Alpha"]
    content_type = ContentType.objects.get_for_model(Product)
    assert alpha_row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert alpha_row["delete_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert alpha_row["view_on_site_url"] == f"/admin-api/view-on-site/{content_type.pk}/{sample.pk}"
    assert alpha_row["permissions"] == {
        "has_add_permission": True,
        "has_change_permission": True,
        "has_delete_permission": True,
        "has_view_permission": True,
    }
    assert rows_by_name["Alpha"]["cells"]["has_description"] is True
    assert rows_by_name["Alpha"]["cells"]["tagline"] == "Nice camera"
    assert rows_by_name["Alpha"]["cells"]["is_expensive"] is True
    assert rows_by_name["Alpha"]["cells"]["subtitle"] == "Nice camera"
    assert rows_by_name["Beta"]["cells"]["has_description"] is False
    assert rows_by_name["Beta"]["cells"]["tagline"] == "No description"
    assert rows_by_name["Beta"]["cells"]["is_expensive"] is False
    assert rows_by_name["Beta"]["cells"]["subtitle"] == "No subtitle"

    empty = admin_client.get("/admin-api/testapp/product?q=missing")
    assert empty.status_code == 200
    assert empty.json()["config"]["search_term"] == "missing"
    assert empty.json()["config"]["has_search"] is True
    assert empty.json()["config"]["clear_search_query_string"] == "?"
    assert empty.json()["config"]["result_count"] == 0
    assert empty.json()["config"]["page_result_count"] == 0
    assert empty.json()["config"]["result_start_index"] == 0
    assert empty.json()["config"]["result_end_index"] == 0


def test_changelist_supports_callable_list_display(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    @display(description="Stock badge", ordering="stock_status", boolean=True)
    def stock_badge(obj):
        return obj.stock_status == "in_stock"

    monkeypatch.setattr(product_admin, "list_display", ("name", stock_badge))
    monkeypatch.setattr(product_admin, "sortable_by", (stock_badge,))

    response = admin_client.get("/admin-api/testapp/product?o=-2")

    assert response.status_code == 200
    error_ids = {error.id for error in product_admin.check()}
    assert "django_ninja_admin.E002" not in error_ids
    assert "django_ninja_admin.E057" not in error_ids
    body = response.json()
    stock_column = next(column for column in body["columns"] if column["field"] == "stock_badge")
    assert stock_column["header_name"] == "Stock badge"
    assert stock_column["boolean"] is True
    assert stock_column["sortable"] is True
    assert stock_column["ordering_field"] == "stock_status"
    assert body["config"]["ordering_field_columns"] == {"stock_badge": 2}
    assert body["rows"][0]["cells"]["name"] == "Beta"
    assert body["rows"][0]["cells"]["stock_badge"] is False
    assert body["rows"][1]["cells"]["name"] == "Alpha"
    assert body["rows"][1]["cells"]["stock_badge"] is True


def test_changelist_supports_relation_path_list_display(admin_client, sample, monkeypatch):
    accessories = Category.objects.create(name="Accessories")
    Product.objects.create(name="Omega", category=accessories, price="1.00")
    product_admin = site.get_model_admin(Product)

    monkeypatch.setattr(product_admin, "list_display", ("name", "category__name"))

    response = admin_client.get("/admin-api/testapp/product?o=2")

    assert response.status_code == 200
    body = response.json()
    category_column = next(column for column in body["columns"] if column["field"] == "category__name")
    assert category_column["header_name"] == "Name"
    assert category_column["sortable"] is True
    assert category_column["ordering_field"] == "category__name"
    assert category_column["ordering_index"] == 2
    assert body["config"]["ordering"] == ["category__name", "-pk"]
    assert body["config"]["ordering_field_columns"] == {"name": 1, "category__name": 2}
    assert body["rows"][0]["cells"] == {"name": "Omega", "category__name": "Accessories"}
    assert body["rows"][1]["cells"]["category__name"] == "Cameras"


def test_changelist_preserves_explicit_blank_display_metadata(admin_client, sample, monkeypatch):
    @display(description="", empty_value="")
    def blank_summary(obj):
        return None

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "list_display", ("name", blank_summary))

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    blank_column = next(column for column in body["columns"] if column["field"] == "blank_summary")
    assert blank_column["header_name"] == ""
    assert blank_column["empty_value_display"] == ""
    assert [row["cells"]["blank_summary"] for row in body["rows"]] == ["", ""]
    assert all(
        row["cell_metadata"]["blank_summary"]["display_value"] == ""
        and row["cell_metadata"]["blank_summary"]["empty_value_display"] == ""
        for row in body["rows"]
    )


def test_changelist_ordering_adds_deterministic_pk_fallback(admin_client, sample, monkeypatch):
    duplicate = Product.objects.create(name="Alpha", category=sample.category, price="6.00")

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["name", "-pk"]
    alpha_ids = [row["id"] for row in body["rows"] if row["cells"]["name"] == "Alpha"]
    assert alpha_ids == [duplicate.pk, sample.pk]

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "ordering", ("id",))

    unique_ordering = admin_client.get("/admin-api/testapp/product")

    assert unique_ordering.status_code == 200
    assert unique_ordering.json()["config"]["ordering"] == ["id"]


def test_changelist_preserves_custom_queryset_ordering(db, sample):
    class QuerysetOrderedProductAdmin(ModelAdmin):
        list_display = ("name", "price")
        list_display_links = ("name",)

        def get_queryset(self, request):
            return super().get_queryset(request).order_by("-price")

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, QuerysetOrderedProductAdmin)
    model_admin = admin_site.get_model_admin(Product)
    user = get_user_model().objects.create_user("queryset-ordering-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, model_admin)

    assert changelist.ordering == ["-price", "-pk"]
    assert [obj.name for obj in changelist.result_list] == ["Alpha", "Gamma", "Beta"]
    price_sort = changelist.column_sort_query_strings("price")
    assert price_sort["sorted"] is True
    assert price_sort["ascending"] is False
    assert price_sort["sort_priority"] == 1
    assert price_sort["remove_sorting_query_string"] is None


def test_changelist_row_metadata_honors_object_permissions(staff_client, sample):
    response = staff_client("view_product").get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["index"] == 0
    assert row["result_index"] == 1
    assert row["detail_url"] == f"/admin-api/testapp/product/{sample.pk}"
    assert row["change_form_url"] == f"/admin-api/testapp/product/{sample.pk}/form"
    assert row["cell_metadata"]["name"]["link_url"] == row["detail_url"]
    assert row["delete_url"] is None
    assert row["permissions"] == {
        "has_add_permission": False,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_changelist_cell_link_url_honors_object_view_permission(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_view_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    def has_change_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    monkeypatch.setattr(product_admin, "has_view_permission", has_view_permission)
    monkeypatch.setattr(product_admin, "has_change_permission", has_change_permission)

    response = admin_client.get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["detail_url"] is None
    assert row["change_form_url"] is None
    assert row["cell_metadata"]["name"]["display_link"] is True
    assert row["cell_metadata"]["name"]["link_url"] is None


def test_change_form_metadata_honors_custom_object_permission_hooks(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)

    def has_change_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    def has_delete_permission(request, obj=None):
        return obj is None or obj.pk != sample.pk

    monkeypatch.setattr(product_admin, "has_change_permission", has_change_permission)
    monkeypatch.setattr(product_admin, "has_delete_permission", has_delete_permission)

    response = admin_client.get(f"/admin-api/testapp/product/{sample.pk}/form")

    assert response.status_code == 200
    assert response.json()["form"]["permissions"] == {
        "has_add_permission": True,
        "has_change_permission": False,
        "has_delete_permission": False,
        "has_view_permission": True,
    }


def test_changelist_action_ui_metadata_follows_model_admin(admin_client, staff_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "actions_on_top", False)
    monkeypatch.setattr(product_admin, "actions_on_bottom", True)
    monkeypatch.setattr(product_admin, "actions_selection_counter", False)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["actions_on_top"] is False
    assert config["actions_on_bottom"] is True
    assert config["actions_selection_counter"] is False
    choices_by_action = {choice["action"]: choice for choice in config["action_choices"]}
    assert choices_by_action["delete_selected"]["permissions"] == ["delete"]
    assert choices_by_action["mark_out_of_stock"]["permissions"] == ["change"]
    assert choices_by_action["report_names"]["permissions"] == ["view"]
    assert choices_by_action["set_stock_status"]["permissions"] == ["change"]
    assert {field["name"] for field in response.json()["action_form"]} == {"action", "selected_ids", "select_across"}

    view_only = staff_client("view_product").get("/admin-api/testapp/product")
    assert view_only.status_code == 200
    assert view_only.json()["config"]["action_choices"] == [
        {"action": "report_names", "description": "Report names", "permissions": ["view"]}
    ]
    action_field = next(field for field in view_only.json()["action_form"] if field["name"] == "action")
    assert action_field["attrs"]["choices"] == [["report_names", "Report names"]]


def test_changelist_exposes_list_editing_row_metadata(admin_client, sample):
    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    body = response.json()
    rows = body["list_editing_rows"]
    legacy_formset = body["list_editing_formset"]

    assert body["list_editing_formset_prefix"] == "form"
    assert body["list_editing_total_form_count"] == 2
    assert body["list_editing_initial_form_count"] == 2
    management_fields = {field["name"]: field for field in body["list_editing_management_form"]}
    assert_no_rendered_field_attrs(management_fields["TOTAL_FORMS"]["attrs"])
    assert management_fields["TOTAL_FORMS"]["attrs"]["value"] == 2
    assert_no_rendered_field_attrs(management_fields["INITIAL_FORMS"]["attrs"])
    assert management_fields["INITIAL_FORMS"]["attrs"]["value"] == 2
    assert management_fields["MIN_NUM_FORMS"]["attrs"]["value"] == 0
    assert management_fields["MAX_NUM_FORMS"]["attrs"]["value"] >= 2
    assert [row["index"] for row in rows] == [0, 1]
    assert [row["pk"] for row in rows] == [row["id"] for row in body["rows"]]
    assert {row["pk_name"] for row in rows} == {"id"}
    assert [row["form_prefix"] for row in rows] == ["form-0", "form-1"]
    assert [row["empty_permitted"] for row in rows] == [False, False]
    assert [[field["name"] for field in row["fields"]] for row in rows] == [["stock_status"], ["stock_status"]]
    assert legacy_formset == [row["fields"] for row in rows]
    assert rows[0]["fields"][0]["attrs"]["value"] == "in_stock"
    assert_no_rendered_field_attrs(rows[0]["fields"][0]["attrs"])
    assert rows[1]["fields"][0]["attrs"]["value"] == "out_of_stock"
    assert_no_rendered_field_attrs(rows[1]["fields"][0]["attrs"])
    assert rows[0]["fields"][0]["attrs"]["choices"] == [
        ["in_stock", "In Stock"],
        ["out_of_stock", "Out of Stock"],
    ]


def test_changelist_can_skip_full_result_count(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "show_full_result_count", False)

    response = admin_client.get("/admin-api/testapp/product?q=Alpha")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["result_count"] == 1
    assert config["full_count"] is None
    assert config["show_full_result_count"] is False
    assert config["show_admin_actions"] is True


def test_changelist_search_distincts_duplicate_many_to_many_matches(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    match_one = Tag.objects.create(name="Search Match One")
    match_two = Tag.objects.create(name="Search Match Two")
    sample.tags.add(match_one, match_two)
    monkeypatch.setattr(product_admin, "search_fields", ("tags__name",))

    response = admin_client.get("/admin-api/testapp/product?q=Search")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert [row["cells"]["name"] for row in response.json()["rows"]] == ["Alpha"]


def test_changelist_prefix_search_distincts_duplicate_many_to_many_matches(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    match_one = Tag.objects.create(name="Search Prefix One")
    match_two = Tag.objects.create(name="Search Prefix Two")
    sample.tags.add(match_one, match_two)
    monkeypatch.setattr(product_admin, "search_fields", ("^tags__name",))

    response = admin_client.get("/admin-api/testapp/product?q=Search")

    assert response.status_code == 200
    assert response.json()["config"]["result_count"] == 1
    assert [row["cells"]["name"] for row in response.json()["rows"]] == ["Alpha"]


def test_changelist_multi_column_ordering_metadata(admin_client, sample):
    Product.objects.create(name="Gamma", category=sample.category, price="3.00")

    response = admin_client.get("/admin-api/testapp/product?o=3,-1")

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["ordering"] == ["price", "-name", "-pk"]
    assert [row["cells"]["name"] for row in body["rows"]][:2] == ["Gamma", "Beta"]

    columns_by_field = {column["field"]: column for column in body["columns"]}
    price_column = columns_by_field["price"]
    name_column = columns_by_field["name"]
    stock_column = columns_by_field["stock_status"]
    assert price_column["sorted"] is True
    assert price_column["ascending"] is True
    assert price_column["sort_priority"] == 1
    assert price_column["ascending_query_string"] == "?o=3,-1"
    assert price_column["descending_query_string"] == "?o=-3,-1"
    assert price_column["remove_sorting_query_string"] == "?o=-1"
    assert name_column["sorted"] is True
    assert name_column["ascending"] is False
    assert name_column["sort_priority"] == 2
    assert name_column["ascending_query_string"] == "?o=1,3"
    assert name_column["descending_query_string"] == "?o=-1,3"
    assert name_column["remove_sorting_query_string"] == "?o=3"
    assert stock_column["sorted"] is False
    assert stock_column["sort_priority"] is None


def test_changelist_search_supports_lookup_suffixes(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(
        name="Alphabet",
        category=sample.category,
        price="14.00",
        description="Starts the same",
    )
    Product.objects.create(
        name="Beta Alpha",
        category=sample.category,
        price="5.00",
        description="Contains the word later",
    )

    monkeypatch.setattr(product_admin, "search_fields", ("^name",))
    startswith = admin_client.get("/admin-api/testapp/product?q=Alpha")
    assert startswith.status_code == 200
    assert [row["cells"]["name"] for row in startswith.json()["rows"]] == ["Alpha", "Alphabet"]

    monkeypatch.setattr(product_admin, "search_fields", ("=name",))
    iexact = admin_client.get("/admin-api/testapp/product?q=alpha")
    assert iexact.status_code == 200
    assert [row["cells"]["name"] for row in iexact.json()["rows"]] == ["Alpha"]

    monkeypatch.setattr(product_admin, "search_fields", ("category__id__exact",))
    category_exact = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id}")
    assert category_exact.status_code == 200
    assert category_exact.json()["config"]["result_count"] == 4

    padded_category = admin_client.get(f"/admin-api/testapp/product?q={sample.category_id:03d}")
    assert padded_category.status_code == 200
    assert padded_category.json()["config"]["result_count"] == 0


def test_changelist_auto_selects_related_list_display_fields(db):
    user = get_user_model().objects.create_user("query-admin", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user

    changelist = ChangeList(request, site.get_model_admin(Product))

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related


def test_changelist_auto_selects_related_display_ordering_paths(db, sample):
    @display(description="Category label", ordering="category__name")
    def category_label(obj):
        return obj.category.name

    class RelatedOrderingProductAdmin(ModelAdmin):
        list_display = ("name", category_label)
        ordering = ("name",)

    Category.objects.create(name="Accessories")
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelatedOrderingProductAdmin)
    user = get_user_model().objects.create_user("query-admin-callable", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [category_label(obj) for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_auto_selects_relation_path_list_display_fields(db, sample):
    class RelationPathProductAdmin(ModelAdmin):
        list_display = ("name", "category__name")
        sortable_by = ("name",)
        ordering = ("name",)

    Product.objects.create(name="Gamma", category=sample.category, price="8.00")

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, RelationPathProductAdmin)
    user = get_user_model().objects.create_user("query-admin-relation-path", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.auto_select_related_fields() == ["category"]
    assert "category" in changelist.queryset.query.select_related
    with CaptureQueriesContext(connection) as queries:
        rendered = [obj.category.name for obj in changelist.result_list]

    assert rendered == ["Cameras", "Cameras", "Cameras"]
    assert len(queries) == 0


def test_changelist_applies_list_prefetch_related_for_callable_display(db, sample):
    @display(description="Tag names")
    def tag_names(obj):
        return ", ".join(sorted(tag.name for tag in obj.tags.all()))

    class PrefetchProductAdmin(ModelAdmin):
        list_display = ("name", tag_names)
        list_prefetch_related = ("tags",)
        ordering = ("name",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, PrefetchProductAdmin)
    user = get_user_model().objects.create_user("query-admin-prefetch", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert changelist.list_prefetch_related == ("tags",)
    assert changelist.queryset._prefetch_related_lookups == ("tags",)
    with CaptureQueriesContext(connection) as queries:
        rendered = [tag_names(obj) for obj in changelist.result_list]

    assert rendered == ["Compact, Featured", ""]
    assert len(queries) == 0


def test_changelist_applies_prefetch_objects_for_callable_display(db, sample):
    @display(description="Prefetched tag names")
    def prefetched_tag_names(obj):
        return ", ".join(tag.name for tag in obj.prefetched_tags)

    class PrefetchObjectProductAdmin(ModelAdmin):
        list_display = ("name", prefetched_tag_names)
        list_prefetch_related = (
            models.Prefetch("tags", queryset=Tag.objects.order_by("name"), to_attr="prefetched_tags"),
        )
        ordering = ("name",)

    admin_site = NinjaAdminSite(include_auth=False)
    admin_site.register(Product, PrefetchObjectProductAdmin)
    user = get_user_model().objects.create_user("query-admin-prefetch-object", password="pw", is_staff=True)
    user.user_permissions.set(Permission.objects.all())
    request = RequestFactory().get("/admin-api/testapp/product")
    request.user = user
    model_admin = admin_site.get_model_admin(Product)

    changelist = ChangeList(request, model_admin)

    assert isinstance(changelist.list_prefetch_related[0], models.Prefetch)
    assert isinstance(changelist.queryset._prefetch_related_lookups[0], models.Prefetch)
    with CaptureQueriesContext(connection) as queries:
        rendered = [prefetched_tag_names(obj) for obj in changelist.result_list]

    assert rendered == ["Compact, Featured", ""]
    assert len(queries) == 0


def test_changelist_route_uses_model_admin_hook(admin_client, sample, monkeypatch):
    class CustomChangeList(ChangeList):
        def filter_descriptions(self):
            return []

    product_admin = site.get_model_admin(Product)
    monkeypatch.setattr(product_admin, "get_changelist", lambda request, **kwargs: CustomChangeList)

    response = admin_client.get("/admin-api/testapp/product")

    assert response.status_code == 200
    assert response.json()["config"]["filters"] == []


def test_changelist_route_uses_model_admin_paginator_hook(admin_client, sample, monkeypatch):
    product_admin = site.get_model_admin(Product)
    Product.objects.create(name="Gamma", category=sample.category, price="8.00")
    calls = {}

    def get_paginator(request, queryset, per_page, orphans=0, allow_empty_first_page=True):
        calls["path"] = request.path
        calls["model"] = queryset.model
        calls["is_queryset"] = isinstance(queryset, models.QuerySet)
        calls["per_page"] = per_page
        calls["orphans"] = orphans
        calls["allow_empty_first_page"] = allow_empty_first_page
        return Paginator(
            queryset,
            per_page,
            orphans=orphans,
            allow_empty_first_page=allow_empty_first_page,
        )

    monkeypatch.setattr(product_admin, "get_paginator", get_paginator)

    response = admin_client.get("/admin-api/testapp/product?pp=1")

    assert response.status_code == 200
    assert response.json()["config"]["page_count"] == 3
    assert calls == {
        "path": "/admin-api/testapp/product",
        "model": Product,
        "is_queryset": True,
        "per_page": 1,
        "orphans": 0,
        "allow_empty_first_page": True,
    }
