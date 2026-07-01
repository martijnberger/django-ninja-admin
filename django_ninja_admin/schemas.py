from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class AdminWriteSchema(Schema):
    model_config = ConfigDict(extra="allow")


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
    errors: list[ErrorItem]
    protected: list[str] | None = None
    perms_needed: list[str] | None = None
    model_count: dict[str, int] | None = None


class MessageResponse(Schema):
    detail: str


class PermissionMap(Schema):
    has_add_permission: bool = False
    has_change_permission: bool = False
    has_delete_permission: bool = False
    has_view_permission: bool = False


class ModelSummary(Schema):
    name: str
    object_name: str
    app_label: str
    model_name: str
    perms: PermissionMap


class AppSummary(Schema):
    name: str
    app_label: str
    has_module_perms: bool
    models: list[ModelSummary]


class SiteContext(Schema):
    site_title: str
    site_header: str
    site_url: str
    has_permission: bool
    available_apps: list[AppSummary]
    is_nav_sidebar_enabled: bool


class FieldDescription(Schema):
    name: str
    type: str
    attrs: dict[str, Any]


class FileFieldValue(Schema):
    name: str
    url: str | None = None


class ImageFieldValue(FileFieldValue):
    width: int | None = None
    height: int | None = None


class FormMediaDescription(Schema):
    css: dict[str, list[str]] = Field(default_factory=dict)
    js: list[str] = Field(default_factory=list)


class FormDescription(Schema):
    model: str
    readonly_fields: list[str]
    fields: list[FieldDescription]
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    fieldsets: list[Any]
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


class InlineDescription(Schema):
    model: str
    readonly_fields: list[str]
    fieldsets: list[Any]
    prepopulated: dict[str, Any]
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    permissions: PermissionMap
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


class Row(Schema):
    id: Any
    cells: dict[str, Any]
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
    first_page_query_string: str | None = None
    previous_page_query_string: str | None = None
    next_page_query_string: str | None = None
    last_page_query_string: str | None = None
    show_all: bool = False
    can_show_all: bool = False
    show_facets: bool = False
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
    ordering_field_columns: dict[str, str] = {}
    ordering: list[str] = []
    search_fields: list[str] = []
    search_help_text: str | None = None


class ListEditingRow(Schema):
    index: int
    pk: Any
    pk_name: str
    fields: list[FieldDescription]


class ChangelistResponse(Schema):
    columns: list[Column]
    rows: list[Row]
    config: ChangelistConfig
    action_form: list[FieldDescription] = []
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
    results: list[AutocompleteItem]
    pagination: AutocompletePagination


class ViewOnSiteResponse(Schema):
    url: str
