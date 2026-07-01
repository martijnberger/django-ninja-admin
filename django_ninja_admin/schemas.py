from typing import Any

from ninja import Schema


class ErrorItem(Schema):
    message: Any
    param: str = "non_field_errors"


class ErrorResponse(Schema):
    errors: list[ErrorItem]


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


class FormDescription(Schema):
    model: str
    readonly_fields: list[str]
    fields: list[FieldDescription]
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


class Row(Schema):
    id: Any
    cells: dict[str, Any]


class ActionChoice(Schema):
    action: str
    description: str


class FilterChoice(Schema):
    selected: bool
    query_string: str
    display: str


class FilterDescription(Schema):
    title: str
    choices: list[FilterChoice]


class ChangelistConfig(Schema):
    full_count: int
    result_count: int
    page_count: int
    page: int
    per_page: int
    action_choices: list[ActionChoice]
    filters: list[FilterDescription]
    list_display_fields: list[str]
    ordering_field_columns: dict[str, str] = {}


class ChangelistResponse(Schema):
    columns: list[Column]
    rows: list[Row]
    config: ChangelistConfig
    action_form: list[FieldDescription] = []
    list_editing_formset: list[list[FieldDescription]] = []


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


class HistoryItem(Schema):
    id: Any
    action_time: str
    user_id: Any
    content_type_id: Any = None
    object_id: str | None = None
    object_repr: str
    action_flag: int
    change_message: Any


class HistoryResponse(Schema):
    pagination: Pagination
    results: list[HistoryItem]


class AutocompleteItem(Schema):
    id: str
    text: str


class AutocompletePagination(Schema):
    more: bool


class AutocompleteResponse(Schema):
    results: list[AutocompleteItem]
    pagination: AutocompletePagination


class ViewOnSiteResponse(Schema):
    url: str

