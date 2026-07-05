from datetime import datetime
from typing import Any, Literal

from django.utils.functional import Promise
from ninja import Schema
from pydantic import ConfigDict, Field, RootModel, field_serializer, field_validator


class AdminSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class AdminWriteSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid")


class AdminInlineRowSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid")


class AdminInlineOperationsSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid")


class AdminInlinePayloadSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AdminInlineOperationResultsSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid")


class AdminBulkRowSchema(AdminSchema):
    model_config = ConfigDict(extra="forbid")


type DeletedObject = str | list[DeletedObject]
type ErrorMessage = str | list[str]


class ErrorItem(AdminSchema):
    message: ErrorMessage
    param: str = "non_field_errors"

    @field_validator("message", mode="before")
    @classmethod
    def coerce_lazy_message(cls, value):
        if isinstance(value, (list, tuple)):
            return [str(item) if isinstance(item, Promise) else item for item in value]
        if value is None:
            return ""
        if isinstance(value, Promise):
            return str(value)
        return value


class ErrorResponse(AdminSchema):
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
                    "deleted_objects": ["Nice camera"],
                    "protected": ["Protected review: Nice camera"],
                    "perms_needed": ["Can delete product review"],
                    "model_count": {"product reviews": 1},
                },
            ]
        }
    )

    errors: list[ErrorItem]
    deleted_objects: list[DeletedObject] | None = None
    protected: list[str] | None = None
    perms_needed: list[str] | None = None
    model_count: dict[str, int] | None = None


class CsrfTokenResponse(AdminSchema):
    csrf_token: str


class SessionLoginPayload(AdminSchema):
    username: str
    password: str


class SessionResponse(AdminSchema):
    is_authenticated: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    has_permission: bool
    csrf_token: str


class ActionResponse(AdminSchema):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"detail": "Action completed."},
                {"detail": "Successfully deleted selected objects.", "deleted": {"products": 1}},
            ]
        },
    )

    detail: str
    deleted: dict[str, int] | None = None

    @field_validator("detail", mode="before")
    @classmethod
    def coerce_lazy_detail(cls, value):
        if value is None:
            return value
        return str(value)


class PermissionMap(AdminSchema):
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


class ModelSummary(AdminSchema):
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


class AppSummary(AdminSchema):
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


class SiteContext(AdminSchema):
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


class PermissionsResponse(AdminSchema):
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
    "max_length": 80,
    "initial": "Tripod",
    "value": "Tripod",
    "choices": [["in_stock", "In Stock"], ["out_of_stock", "Out of Stock"]],
    "admin_widget": "autocomplete",
    "autocomplete": {
        "url": "/admin-api/autocomplete",
        "app_label": "shop",
        "model_name": "product",
        "field_name": "category",
        "related_model": "shop.category",
        "multiple": False,
    },
    "input_schema_override": {"schema": {"type": "boolean"}},
}


class FileFieldValue(AdminSchema):
    name: str
    url: str | None = None


class ImageFieldValue(FileFieldValue):
    width: int | None = None
    height: int | None = None


class SelectedOption(AdminSchema):
    id: str
    text: str


type FieldMetadataValue = dict[str, FieldMetadataValue] | list[FieldMetadataValue] | str | int | float | bool | None
type JsonSchemaValue = dict[str, JsonSchemaValue] | list[JsonSchemaValue] | str | int | float | bool | None
type JsonObject = dict[str, JsonSchemaValue]
type ObjectIdentifier = str | int | float
type ChoicePair = tuple[str | None, str]


class JsonObjectResponse(RootModel[JsonObject]):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "detail": "ok",
                    "metadata": {"count": 1},
                }
            ]
        }
    )


class ChoiceOption(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    raw_value: FieldMetadataValue = None
    label: str
    coerced_value: FieldMetadataValue = None


class ChoiceGroup(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    options: list[ChoiceOption]


class SourceFieldIdentity(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    app_label: str | None = None
    model_name: str | None = None
    field_name: str


def _to_field_query_json_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    if "to_field" in properties:
        properties["_to_field"] = properties.pop("to_field")
    schema["required"] = ["_to_field" if item == "to_field" else item for item in schema.get("required", [])]


class ToFieldQuery(AdminSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, json_schema_extra=_to_field_query_json_schema)

    to_field: str = Field(alias="_to_field", serialization_alias="_to_field")


class RelationWidgetMetadata(SourceFieldIdentity):
    related_model: str | None = None
    related_app_label: str | None = None
    related_model_name: str | None = None
    related_object_name: str | None = None
    related_verbose_name: str | None = None
    related_verbose_name_plural: str | None = None
    to_field_name: str | None = None
    to_field_class: str | None = None
    to_field_internal_type: str | None = None
    to_field_attname: str | None = None
    multiple: bool | None = None
    url: str | None = None
    query: SourceFieldIdentity | ToFieldQuery | None = None


class FilteredSelectMetadata(SourceFieldIdentity):
    direction: Literal["horizontal", "vertical"]
    is_stacked: bool
    verbose_name: str | None = None
    selected_count: int | None = None
    available_count: int | None = None
    related_model: str | None = None
    related_app_label: str | None = None
    related_model_name: str | None = None
    related_object_name: str | None = None
    related_verbose_name: str | None = None
    related_verbose_name_plural: str | None = None
    to_field_name: str | None = None
    to_field_class: str | None = None
    to_field_internal_type: str | None = None
    to_field_attname: str | None = None
    url: str | None = None
    query: ToFieldQuery | None = None


class RadioMetadata(SourceFieldIdentity):
    orientation: Literal[1, 2]


class PrepopulatedSourceMetadata(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    label: str | None = None
    internal_type: str | None = None


class PrepopulatedMetadata(SourceFieldIdentity):
    sources: list[PrepopulatedSourceMetadata]


def _class_field_json_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    if "class_" in properties:
        properties["class"] = properties.pop("class_")
    schema["required"] = ["class" if item == "class_" else item for item in schema.get("required", [])]


class ValidatorDetail(AdminSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, json_schema_extra=_class_field_json_schema)

    class_: str = Field(alias="class", serialization_alias="class")
    code: FieldMetadataValue = None
    message: FieldMetadataValue = None
    limit_value: FieldMetadataValue = None
    pattern: str | None = None


class WidgetMetadata(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    widget: str
    widget_attrs: dict[str, FieldMetadataValue] | None = None
    is_hidden: bool
    is_localized: bool
    multiple: bool
    use_fieldset: bool | None = None
    input_type: str | None = None
    format: str | None = None
    needs_multipart_form: bool | None = None
    add_id_index: bool | None = None
    checked_attribute: dict[str, FieldMetadataValue] | str | bool | None = None
    supports_microseconds: bool | None = None


class SubwidgetMetadata(WidgetMetadata):
    name_suffix: str


class IndexedInputFormats(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    index: int
    input_formats: list[str]


class SelectDateChoice(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    value: FieldMetadataValue = None
    label: str


class SelectDateEmptyChoices(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    year: SelectDateChoice
    month: SelectDateChoice
    day: SelectDateChoice


class SelectDateSelected(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    year: FieldMetadataValue = None
    month: FieldMetadataValue = None
    day: FieldMetadataValue = None


class SelectDateMetadata(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    order: list[Literal["year", "month", "day"]]
    years: list[FieldMetadataValue]
    months: list[SelectDateChoice]
    days: list[int]
    empty_choices: SelectDateEmptyChoices
    selected: SelectDateSelected | None = None


def _schema_field_json_schema(schema: dict[str, Any]) -> None:
    properties = schema.get("properties", {})
    if "schema_" in properties:
        properties["schema"] = properties.pop("schema_")
    schema["required"] = ["schema" if item == "schema_" else item for item in schema.get("required", [])]


class InputSchemaOverrideMetadata(AdminSchema):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, json_schema_extra=_schema_field_json_schema)

    schema_: JsonSchemaValue = Field(alias="schema", serialization_alias="schema")


class FieldAttributes(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    required: bool | None = None
    label: str | None = None
    help_text: str | None = None
    read_only: bool | None = None
    disabled: bool | None = None
    localize: bool | None = None
    validators: list[str] | None = None
    validator_details: list[ValidatorDetail] | None = None
    error_messages: dict[str, FieldMetadataValue] | None = None
    boolean: bool | None = None
    empty_value_display: str | None = None
    ordering_field: str | None = None

    widget: str | None = None
    widget_attrs: dict[str, FieldMetadataValue] | None = None
    is_hidden: bool | None = None
    is_localized: bool | None = None
    multiple: bool | None = None
    use_fieldset: bool | None = None
    input_type: str | None = None
    format: str | None = None
    needs_multipart_form: bool | None = None
    add_id_index: bool | None = None
    checked_attribute: dict[str, FieldMetadataValue] | str | bool | None = None
    supports_microseconds: bool | None = None
    admin_widget: str | None = None
    radio_orientation: Literal[1, 2] | None = None

    model_field_name: str | None = None
    model_field_class: str | None = None
    internal_type: str | None = None
    blank: bool | None = None
    null: bool | None = None
    editable: bool | None = None
    primary_key: bool | None = None
    unique: bool | None = None
    db_index: bool | None = None
    attname: str | None = None
    column: str | None = None
    default: FieldMetadataValue = None
    upload_to: str | None = None
    image: bool | None = None
    width_field: str | None = None
    height_field: str | None = None
    limit_choices_to: dict[str, FieldMetadataValue] | list[FieldMetadataValue] | None = None

    subwidgets: list[SubwidgetMetadata] | None = None
    select_date: SelectDateMetadata | None = None
    input_formats: list[str | IndexedInputFormats] | None = None
    choices: list[ChoicePair] | None = None
    choice_options: list[ChoiceOption] | None = None
    choice_coerce: str | None = None
    choice_groups: list[ChoiceGroup] | None = None
    combo_fields: list["ComboFieldMetadata"] | None = None

    initial: FieldMetadataValue = None
    value: FieldMetadataValue = None
    max_length: int | None = None
    min_length: int | None = None
    strip: bool | None = None
    empty_value: FieldMetadataValue = None
    min_value: FieldMetadataValue = None
    max_value: FieldMetadataValue = None
    step_size: FieldMetadataValue = None
    step_offset: FieldMetadataValue = None
    max_digits: int | None = None
    decimal_places: int | None = None
    null_boolean: bool | None = None

    path: str | None = None
    recursive: bool | None = None
    allow_files: bool | None = None
    allow_folders: bool | None = None
    match: str | None = None
    allow_empty_file: bool | None = None
    allowed_extensions: list[str] | None = None
    accepted_extensions: list[str] | None = None
    accepted_content_types: list[str] | None = None
    current_file: FileFieldValue | ImageFieldValue | None = None
    clearable_file_input: bool | None = None
    initial_text: str | None = None
    input_text: str | None = None
    clear_checkbox_label: str | None = None

    related_model: str | None = None
    related_app_label: str | None = None
    related_model_name: str | None = None
    related_object_name: str | None = None
    related_verbose_name: str | None = None
    related_verbose_name_plural: str | None = None
    to_field_name: str | None = None
    to_field_class: str | None = None
    to_field_internal_type: str | None = None
    to_field_attname: str | None = None
    empty_label: str | None = None
    selected_options: list[SelectedOption] | None = None
    autocomplete: RelationWidgetMetadata | None = None
    raw_id: RelationWidgetMetadata | None = None
    filtered_select: FilteredSelectMetadata | None = None
    radio: RadioMetadata | None = None
    prepopulated_from: list[str] | None = None
    prepopulated: PrepopulatedMetadata | None = None
    input_schema_override: InputSchemaOverrideMetadata | None = None


class ComboFieldMetadata(AdminSchema):
    model_config = ConfigDict(extra="forbid")

    index: int
    type: str
    attrs: FieldAttributes


FieldAttributes.model_rebuild(_types_namespace={"ComboFieldMetadata": ComboFieldMetadata})


class FieldDescription(AdminSchema):
    name: str
    type: str
    attrs: FieldAttributes = Field(
        description="Semantic form/admin metadata for frontend renderers.",
        json_schema_extra={"examples": [FIELD_DESCRIPTION_ATTRS_EXAMPLE]},
    )

    @field_serializer("attrs")
    def serialize_attrs(self, attrs: FieldAttributes):
        return attrs.model_dump(mode="json", exclude_unset=True, by_alias=True)


class ActionChoiceFieldAttributes(AdminSchema):
    required: Literal[True] = True
    choices: list[ChoicePair]


class ActionSelectedIdsFieldAttributes(AdminSchema):
    required: Literal[False] = False


class ActionSelectAcrossFieldAttributes(AdminSchema):
    required: Literal[False] = False


class ActionChoiceFieldDescription(FieldDescription):
    name: Literal["action"]
    type: Literal["ChoiceField"]
    attrs: ActionChoiceFieldAttributes


class ActionSelectedIdsFieldDescription(FieldDescription):
    name: Literal["selected_ids"]
    type: Literal["MultipleChoiceField"]
    attrs: ActionSelectedIdsFieldAttributes


class ActionSelectAcrossFieldDescription(FieldDescription):
    name: Literal["select_across"]
    type: Literal["BooleanField"]
    attrs: ActionSelectAcrossFieldAttributes


type ActionFormField = (
    ActionChoiceFieldDescription | ActionSelectedIdsFieldDescription | ActionSelectAcrossFieldDescription
)


class ManagementFormFieldAttributes(AdminSchema):
    required: bool
    label: str
    help_text: str = ""
    read_only: Literal[False] = False
    disabled: Literal[False] = False
    localize: Literal[False] = False
    validators: list[str] = Field(default_factory=list)
    error_messages: dict[str, FieldMetadataValue] = Field(default_factory=dict)
    widget: Literal["HiddenInput"] = "HiddenInput"
    widget_attrs: dict[str, FieldMetadataValue] = Field(default_factory=dict)
    is_hidden: Literal[True] = True
    is_localized: Literal[False] = False
    multiple: Literal[False] = False
    input_type: Literal["hidden"] = "hidden"
    needs_multipart_form: Literal[False] = False
    value: int = Field(ge=0)


class RequiredManagementFormFieldAttributes(ManagementFormFieldAttributes):
    required: Literal[True] = True


class OptionalManagementFormFieldAttributes(ManagementFormFieldAttributes):
    required: Literal[False] = False


class TotalFormsFieldDescription(FieldDescription):
    name: Literal["TOTAL_FORMS"]
    type: Literal["IntegerField"]
    attrs: RequiredManagementFormFieldAttributes


class InitialFormsFieldDescription(FieldDescription):
    name: Literal["INITIAL_FORMS"]
    type: Literal["IntegerField"]
    attrs: RequiredManagementFormFieldAttributes


class MinNumFormsFieldDescription(FieldDescription):
    name: Literal["MIN_NUM_FORMS"]
    type: Literal["IntegerField"]
    attrs: OptionalManagementFormFieldAttributes


class MaxNumFormsFieldDescription(FieldDescription):
    name: Literal["MAX_NUM_FORMS"]
    type: Literal["IntegerField"]
    attrs: OptionalManagementFormFieldAttributes


type ManagementFormField = (
    TotalFormsFieldDescription
    | InitialFormsFieldDescription
    | MinNumFormsFieldDescription
    | MaxNumFormsFieldDescription
)


class FormMediaDescription(AdminSchema):
    css: dict[str, list[str]] = Field(default_factory=dict)
    js: list[str] = Field(default_factory=list)


class FieldsetRow(AdminSchema):
    fields: list[str]


class FieldsetDescription(AdminSchema):
    name: str | None = None
    classes: list[str] = Field(default_factory=list)
    description: str | None = None
    fields: list[str] = Field(default_factory=list)
    rows: list[FieldsetRow] = Field(default_factory=list)


type PrepopulatedFieldMap = dict[str, list[str]]
type RadioFieldMap = dict[str, Literal[1, 2]]


class FormDescription(AdminSchema):
    model: str
    readonly_fields: list[str]
    fields: list[FieldDescription]
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    fieldset_layout: list[FieldsetDescription] = Field(default_factory=list)
    prepopulated: PrepopulatedFieldMap
    permissions: PermissionMap
    save_as: bool = False
    save_as_continue: bool = True
    save_on_top: bool = False
    filter_horizontal: list[str] = Field(default_factory=list)
    filter_vertical: list[str] = Field(default_factory=list)
    raw_id_fields: list[str] = Field(default_factory=list)
    radio_fields: RadioFieldMap = Field(default_factory=dict)
    view_on_site: bool = True
    autocomplete_fields: list[str] = Field(default_factory=list)


class InlineFormsetRowMetadata(AdminSchema):
    index: int = Field(ge=0)
    prefix: str
    is_initial: bool
    empty_permitted: bool
    object_id: str | None = None


class InlineDescription(AdminSchema):
    model: str
    readonly_fields: list[str]
    fieldset_layout: list[FieldsetDescription] = Field(default_factory=list)
    prepopulated: PrepopulatedFieldMap
    media: FormMediaDescription = Field(default_factory=FormMediaDescription)
    permissions: PermissionMap
    formset_prefix: str | None = None
    management_form: list[ManagementFormField] = Field(default_factory=list)
    total_form_count: int | None = Field(default=None, ge=0)
    initial_form_count: int | None = Field(default=None, ge=0)
    empty_form_prefix: str | None = None
    empty_form: list[FieldDescription] = Field(default_factory=list)
    formset_row_metadata: list[InlineFormsetRowMetadata] = Field(default_factory=list)
    extra: int = Field(default=3, ge=0)
    min_num: int | None = Field(default=None, ge=0)
    max_num: int | None = Field(default=None, ge=0)
    verbose_name: str
    verbose_name_plural: str
    can_delete: bool = True
    show_change_link: bool = False
    admin_style: str
    formset: list[list[FieldDescription]]


class FormResponse(AdminSchema):
    form: FormDescription
    inlines: list[InlineDescription] = Field(default_factory=list)


class Column(AdminSchema):
    field: str
    header_name: str
    display_link: bool = False
    boolean: bool = False
    empty_value_display: str | None = None
    sortable: bool = False
    sorted: bool = False
    ascending: bool = False
    sort_priority: int | None = None
    ordering_field: str | None = None
    ordering_index: int | None = None
    ascending_query_string: str | None = None
    descending_query_string: str | None = None
    remove_sorting_query_string: str | None = None


class CellMetadata(AdminSchema):
    field: str
    header_name: str
    value: FieldMetadataValue = None
    display_value: FieldMetadataValue = None
    empty: bool = False
    boolean: bool = False
    display_link: bool = False
    link_url: str | None = None
    sortable: bool = False
    ordering_field: str | None = None
    editable: bool = False
    empty_value_display: str | None = None


class Row(AdminSchema):
    id: ObjectIdentifier
    index: int = Field(default=0, ge=0)
    result_index: int = Field(default=0, ge=0)
    cells: dict[str, FieldMetadataValue]
    cell_metadata: dict[str, CellMetadata] = Field(default_factory=dict)
    detail_url: str | None = None
    change_form_url: str | None = None
    delete_url: str | None = None
    view_on_site_url: str | None = None
    permissions: PermissionMap | None = None


class ActionChoice(AdminSchema):
    action: str
    description: str
    permissions: list[str] = Field(default_factory=list)


class FilterChoice(AdminSchema):
    selected: bool
    query_string: str
    display: str
    count: int | None = Field(default=None, ge=0)


class FilterDescription(AdminSchema):
    title: str
    parameter_name: str = ""
    choices: list[FilterChoice]


type DateHierarchyLevel = Literal["year", "month", "day"]
type DateHierarchyParamName = Literal["year", "month", "day"]


class DateHierarchyParams(RootModel[dict[DateHierarchyParamName, int]]):
    pass


class DateHierarchyChoice(AdminSchema):
    selected: bool
    query_string: str
    display: str
    level: DateHierarchyLevel
    value: int = Field(ge=1)
    count: int | None = Field(default=None, ge=0)


class DateHierarchyDescription(AdminSchema):
    field: str
    title: str
    field_type: str
    timezone: str | None = None
    level: DateHierarchyLevel
    params: DateHierarchyParams
    clear_query_string: str
    back_query_string: str | None = None
    choices: list[DateHierarchyChoice]


class PageChoice(AdminSchema):
    display: str
    page: int | None = Field(default=None, ge=1)
    selected: bool = False
    query_string: str | None = None


class Pagination(AdminSchema):
    count: int = Field(ge=0)
    num_pages: int = Field(ge=0)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1)
    has_next: bool = False
    has_previous: bool = False
    more: bool = False


class ChangelistConfig(AdminSchema):
    full_count: int | None = Field(ge=0)
    result_count: int = Field(ge=0)
    page_result_count: int = Field(default=0, ge=0)
    result_start_index: int = Field(default=0, ge=0)
    result_end_index: int = Field(default=0, ge=0)
    page_count: int = Field(ge=0)
    page: int = Field(ge=1)
    per_page: int = Field(ge=1)
    pagination: Pagination
    has_next: bool = False
    has_previous: bool = False
    multi_page: bool = False
    pagination_required: bool = False
    page_range: list[int | str] = Field(default_factory=list)
    page_choices: list[PageChoice] = Field(default_factory=list)
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
    list_display_links: list[str] = Field(default_factory=list)
    to_field: str | None = None
    object_id_field: str
    ordering_field_columns: dict[str, int] = Field(default_factory=dict)
    ordering: list[str] = Field(default_factory=list)
    search_term: str = ""
    has_search: bool = False
    clear_search_query_string: str | None = None
    search_fields: list[str] = Field(default_factory=list)
    search_help_text: str | None = None


class ListEditingRow(AdminSchema):
    index: int = Field(ge=0)
    pk: ObjectIdentifier
    pk_name: str
    form_prefix: str | None = None
    empty_permitted: bool = False
    fields: list[FieldDescription]


class ChangelistResponse(AdminSchema):
    columns: list[Column]
    rows: list[Row]
    config: ChangelistConfig
    action_form: list[ActionFormField] = Field(default_factory=list)
    list_editing_formset_prefix: str | None = None
    list_editing_management_form: list[ManagementFormField] = Field(default_factory=list)
    list_editing_total_form_count: int | None = Field(default=None, ge=0)
    list_editing_initial_form_count: int | None = Field(default=None, ge=0)
    list_editing_formset: list[list[FieldDescription]] = Field(default_factory=list)
    list_editing_rows: list[ListEditingRow] = Field(default_factory=list)


class HistoryItem(AdminSchema):
    id: ObjectIdentifier
    action_time: datetime
    user_id: ObjectIdentifier
    content_type_id: ObjectIdentifier | None = None
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
    change_message: FieldMetadataValue
    change_message_text: str


class HistoryResponse(AdminSchema):
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
                        "more": False,
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


class AutocompleteItem(AdminSchema):
    id: str
    text: str


class AutocompleteResponse(AdminSchema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "results": [{"id": "1", "text": "Cameras"}],
                    "pagination": {
                        "count": 1,
                        "num_pages": 1,
                        "page": 1,
                        "per_page": 20,
                        "has_next": False,
                        "has_previous": False,
                        "more": False,
                    },
                }
            ]
        }
    )

    results: list[AutocompleteItem]
    pagination: Pagination


class ViewOnSiteResponse(AdminSchema):
    model_config = ConfigDict(json_schema_extra={"examples": [{"url": "https://example.com/products/1/"}]})

    url: str
