from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class AdminWriteSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class AdminInlineRowSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class AdminInlineOperationsSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class AdminInlinePayloadSchema(Schema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AdminBulkRowSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class ErrorItem(Schema):
    message: Any
    param: str = "non_field_errors"


class ErrorResponse(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "errors": [{"param": "name", "message": ["This field is required."]}],
                },
                {
                    "errors": [{"param": "non_field_errors", "message": "Permission denied."}],
                },
                {
                    "errors": [{"param": "delete", "message": "Cannot delete selected objects."}],
                    "protected": ["Protected review: Nice camera"],
                    "perms_needed": ["Can delete product review"],
                    "model_count": {"product reviews": 1},
                },
            ]
        }
    )

    errors: list[ErrorItem]
    protected: list[str] | None = None
    perms_needed: list[str] | None = None
    model_count: dict[str, int] | None = None


class MessageResponse(Schema):
    model_config = ConfigDict(json_schema_extra={"examples": [{"detail": "Object deleted."}]})

    detail: str


class PermissionMap(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "has_add_permission": True,
                    "has_change_permission": True,
                    "has_delete_permission": False,
                    "has_view_permission": True,
                }
            ]
        }
    )

    has_add_permission: bool = False
    has_change_permission: bool = False
    has_delete_permission: bool = False
    has_view_permission: bool = False


class ModelSummary(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Products",
                    "object_name": "Product",
                    "app_label": "shop",
                    "model_name": "product",
                    "perms": {
                        "has_add_permission": True,
                        "has_change_permission": True,
                        "has_delete_permission": False,
                        "has_view_permission": True,
                    },
                }
            ]
        }
    )

    name: str
    object_name: str
    app_label: str
    model_name: str
    perms: PermissionMap


class AppSummary(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Shop",
                    "app_label": "shop",
                    "has_module_perms": True,
                    "models": [
                        {
                            "name": "Products",
                            "object_name": "Product",
                            "app_label": "shop",
                            "model_name": "product",
                            "perms": {
                                "has_add_permission": True,
                                "has_change_permission": True,
                                "has_delete_permission": False,
                                "has_view_permission": True,
                            },
                        }
                    ],
                }
            ]
        }
    )

    name: str
    app_label: str
    has_module_perms: bool
    models: list[ModelSummary]


class SiteContext(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "site_title": "Django Ninja Admin",
                    "site_header": "Django Ninja Administration",
                    "site_url": "/",
                    "has_permission": True,
                    "available_apps": [
                        {
                            "name": "Shop",
                            "app_label": "shop",
                            "has_module_perms": True,
                            "models": [
                                {
                                    "name": "Products",
                                    "object_name": "Product",
                                    "app_label": "shop",
                                    "model_name": "product",
                                    "perms": {
                                        "has_add_permission": True,
                                        "has_change_permission": True,
                                        "has_delete_permission": False,
                                        "has_view_permission": True,
                                    },
                                }
                            ],
                        }
                    ],
                    "is_nav_sidebar_enabled": True,
                }
            ]
        }
    )

    site_title: str
    site_header: str
    site_url: str
    has_permission: bool
    available_apps: list[AppSummary]
    is_nav_sidebar_enabled: bool


class PermissionsResponse(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "is_authenticated": True,
                    "is_active": True,
                    "is_staff": True,
                    "is_superuser": False,
                    "has_permission": True,
                    "models": [
                        {
                            "name": "Products",
                            "object_name": "Product",
                            "app_label": "shop",
                            "model_name": "product",
                            "perms": {
                                "has_add_permission": True,
                                "has_change_permission": True,
                                "has_delete_permission": False,
                                "has_view_permission": True,
                            },
                        }
                    ],
                }
            ]
        }
    )

    is_authenticated: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    has_permission: bool
    models: list[ModelSummary] = Field(default_factory=list)


FIELD_DESCRIPTION_ATTRS_EXAMPLE = {
    "required": True,
    "label": "Name",
    "help_text": "Public display name.",
    "widget": "TextInput",
    "ordering_field": "name",
    "html_name": "name",
    "auto_id": "id_name",
    "id_for_label": "id_name",
    "aria_describedby": "id_name_helptext",
    "rendered_attrs": {
        "id": "id_name",
        "required": True,
        "aria-describedby": "id_name_helptext",
    },
    "rendered_subwidgets": [
        {
            "index": 0,
            "name": "release_window_0",
            "auto_id": "id_release_window_0",
            "id_for_label": "id_release_window_0",
            "attrs": {"id": "id_release_window_0"},
            "type": "text",
        }
    ],
}


class FieldDescription(Schema):
    name: str
    type: str
    attrs: dict[str, Any] = Field(
        description="Django form/admin metadata for frontend renderers.",
        json_schema_extra={"examples": [FIELD_DESCRIPTION_ATTRS_EXAMPLE]},
    )


class FileFieldValue(Schema):
    name: str
    url: str | None = None


class ImageFieldValue(FileFieldValue):
    width: int | None = None
    height: int | None = None


class FormMediaDescription(Schema):
    css: dict[str, list[str]] = Field(default_factory=dict)
    js: list[str] = Field(default_factory=list)


class FieldsetRow(Schema):
    fields: list[str]


class FieldsetDescription(Schema):
    name: str | None = None
    classes: list[str] = Field(default_factory=list)
    description: str | None = None
    fields: list[str] = Field(default_factory=list)
    rows: list[FieldsetRow] = Field(default_factory=list)


class FormDescription(Schema):
    model: str
    readonly_fields: list[str]
    fields: list[FieldDescription]
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    fieldsets: list[Any]
    fieldset_layout: list[FieldsetDescription] = Field(default_factory=list)
    prepopulated: dict[str, Any]
    permissions: PermissionMap
    save_as: bool = False
    save_as_continue: bool = True
    save_on_top: bool = False
    filter_horizontal: list[str] = []
    filter_vertical: list[str] = []
    raw_id_fields: list[str] = []
    radio_fields: dict[str, Any] = {}
    view_on_site: bool = True
    autocomplete_fields: list[str] = []


class InlineFormsetRowMetadata(Schema):
    index: int
    prefix: str
    is_initial: bool
    empty_permitted: bool
    object_id: str | None = None


class InlineDescription(Schema):
    model: str
    readonly_fields: list[str]
    fieldsets: list[Any]
    fieldset_layout: list[FieldsetDescription] = Field(default_factory=list)
    prepopulated: dict[str, Any]
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    permissions: PermissionMap
    formset_prefix: str | None = None
    management_form: list[FieldDescription] = Field(default_factory=list)
    total_form_count: int | None = None
    initial_form_count: int | None = None
    empty_form_prefix: str | None = None
    empty_form: list[FieldDescription] = Field(default_factory=list)
    formset_row_metadata: list[InlineFormsetRowMetadata] = Field(default_factory=list)
    extra: int = 3
    min_num: int | None = None
    max_num: int | None = None
    verbose_name: str
    verbose_name_plural: str
    can_delete: bool = True
    show_change_link: bool = False
    admin_style: str
    formset: list[list[FieldDescription]]


class FormResponse(Schema):
    form: FormDescription
    inlines: list[InlineDescription] = []


class Column(Schema):
    field: str
    headerName: str
    display_link: bool = False
    boolean: bool = False
    empty_value_display: str | None = None
    sortable: bool = False
    sorted: bool = False
    ascending: bool = False
    sort_priority: int | None = None
    ordering_field: str | None = None
    ordering_index: str | None = None
    ascending_query_string: str | None = None
    descending_query_string: str | None = None
    remove_sorting_query_string: str | None = None


class CellMetadata(Schema):
    field: str
    headerName: str
    value: Any = None
    display_value: Any = None
    empty: bool = False
    boolean: bool = False
    display_link: bool = False
    sortable: bool = False
    ordering_field: str | None = None
    editable: bool = False
    empty_value_display: str | None = None


class Row(Schema):
    id: Any
    index: int = 0
    result_index: int = 0
    cells: dict[str, Any]
    cell_metadata: dict[str, CellMetadata] = Field(default_factory=dict)
    detail_url: str | None = None
    change_form_url: str | None = None
    delete_url: str | None = None
    view_on_site_url: str | None = None
    permissions: PermissionMap | None = None


class ActionChoice(Schema):
    action: str
    description: str
    permissions: list[str] = []


class FilterChoice(Schema):
    selected: bool
    query_string: str
    display: str
    count: int | None = None


class FilterDescription(Schema):
    title: str
    parameter_name: str = ""
    choices: list[FilterChoice]


class DateHierarchyChoice(Schema):
    selected: bool
    query_string: str
    display: str
    level: str
    value: int
    count: int | None = None


class DateHierarchyDescription(Schema):
    field: str
    title: str
    field_type: str
    timezone: str | None = None
    level: str
    params: dict[str, int]
    clear_query_string: str
    back_query_string: str | None = None
    choices: list[DateHierarchyChoice]


class PageChoice(Schema):
    display: str
    page: int | None = None
    selected: bool = False
    query_string: str | None = None


class ChangelistConfig(Schema):
    full_count: int | None
    result_count: int
    page_result_count: int = 0
    result_start_index: int = 0
    result_end_index: int = 0
    page_count: int
    page: int
    per_page: int
    has_next: bool = False
    has_previous: bool = False
    multi_page: bool = False
    pagination_required: bool = False
    page_range: list[int | str] = []
    page_choices: list[PageChoice] = []
    first_page_query_string: str | None = None
    previous_page_query_string: str | None = None
    next_page_query_string: str | None = None
    last_page_query_string: str | None = None
    show_all_query_string: str | None = None
    clear_show_all_query_string: str | None = None
    show_all: bool = False
    can_show_all: bool = False
    show_facets: bool = False
    facets_optional: bool = False
    add_facets_query_string: str | None = None
    remove_facets_query_string: str | None = None
    has_filters: bool = False
    has_active_filters: bool = False
    clear_all_filters_query_string: str | None = None
    actions_on_top: bool = True
    actions_on_bottom: bool = False
    actions_selection_counter: bool = True
    show_full_result_count: bool = True
    show_admin_actions: bool = True
    action_choices: list[ActionChoice]
    filters: list[FilterDescription]
    date_hierarchy: DateHierarchyDescription | None = None
    list_display_fields: list[str]
    list_display_links: list[str] = []
    to_field: str | None = None
    object_id_field: str
    ordering_field_columns: dict[str, str] = {}
    ordering: list[str] = []
    search_term: str = ""
    has_search: bool = False
    clear_search_query_string: str | None = None
    search_fields: list[str] = []
    search_help_text: str | None = None


class ListEditingRow(Schema):
    index: int
    pk: Any
    pk_name: str
    form_prefix: str | None = None
    empty_permitted: bool = False
    fields: list[FieldDescription]


class ChangelistResponse(Schema):
    columns: list[Column]
    rows: list[Row]
    config: ChangelistConfig
    action_form: list[FieldDescription] = []
    list_editing_formset_prefix: str | None = None
    list_editing_management_form: list[FieldDescription] = Field(default_factory=list)
    list_editing_total_form_count: int | None = None
    list_editing_initial_form_count: int | None = None
    list_editing_formset: list[list[FieldDescription]] = []
    list_editing_rows: list[ListEditingRow] = []


class MutationPayload(Schema):
    data: dict[str, Any] = {}
    inlines: dict[str, Any] | None = None


class ActionPayload(Schema):
    action: str
    selected_ids: list[Any] = []
    select_across: bool = False


class BulkPayload(Schema):
    data: list[dict[str, Any]]


class MutationResponse(Schema):
    data: dict[str, Any]
    inlines: dict[str, Any] | None = None


class Pagination(Schema):
    num_pages: int
    count: int
    has_next: bool
    has_previous: bool
    page: int = 1
    per_page: int = 20


class HistoryItem(Schema):
    id: Any
    action_time: str
    user_id: Any
    content_type_id: Any = None
    model: str | None = None
    app_label: str | None = None
    model_name: str | None = None
    model_verbose_name: str | None = None
    model_verbose_name_plural: str | None = None
    object_id: str | None = None
    object_repr: str
    detail_url: str | None = None
    change_form_url: str | None = None
    action_flag: int
    change_message: Any
    change_message_text: str


class HistoryResponse(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pagination": {
                        "num_pages": 1,
                        "count": 1,
                        "has_next": False,
                        "has_previous": False,
                        "page": 1,
                        "per_page": 20,
                    },
                    "results": [
                        {
                            "id": 1,
                            "action_time": "2026-07-02T12:00:00+00:00",
                            "user_id": 1,
                            "content_type_id": 12,
                            "model": "shop.product",
                            "app_label": "shop",
                            "model_name": "product",
                            "model_verbose_name": "product",
                            "model_verbose_name_plural": "products",
                            "object_id": "1",
                            "object_repr": "Tripod",
                            "detail_url": "/admin-api/shop/product/1",
                            "change_form_url": "/admin-api/shop/product/1/form",
                            "action_flag": 2,
                            "change_message": [{"changed": {"fields": ["Name"]}}],
                            "change_message_text": "Changed Name.",
                        }
                    ],
                }
            ]
        }
    )

    pagination: Pagination
    results: list[HistoryItem]


class AutocompleteItem(Schema):
    id: str
    text: str


class AutocompletePagination(Schema):
    more: bool
    count: int = 0
    num_pages: int = 0
    page: int = 1
    per_page: int = 20
    has_next: bool = False
    has_previous: bool = False


class AutocompleteResponse(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "results": [{"id": "1", "text": "Cameras"}],
                    "pagination": {
                        "more": False,
                        "count": 1,
                        "num_pages": 1,
                        "page": 1,
                        "per_page": 20,
                        "has_next": False,
                        "has_previous": False,
                    },
                }
            ]
        }
    )

    results: list[AutocompleteItem]
    pagination: AutocompletePagination


class ViewOnSiteResponse(Schema):
    model_config = ConfigDict(json_schema_extra={"examples": [{"url": "https://example.com/products/1/"}]})

    url: str
