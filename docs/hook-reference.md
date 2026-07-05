# Hook Reference

`django-ninja-admin` keeps Django-admin-style extension points where they map
cleanly to an HTTP API. Prefer these hooks over DRF serializer concepts.

## Registration

- `site.register(Model, AdminClass)`
- `site.unregister(Model)`
- `@register(Model)`
- `NinjaAdminSite(auth=...)`

The default `site` is lazy and builds routers after registration and
autodiscovery.

## Model Admin Contract Hooks

- `form_class`
- `get_form_class(request, obj=None, change=False)`
- `form_schema_field_overrides`
- `get_form_schema_field_overrides(request, obj=None, change=False)`
- `output_schema`
- `get_output_schema(request=None)`
- `schema_field_overrides`
- `get_schema_field_overrides(request=None)`
- `output_exclude`
- `get_output_exclude(request=None)`
- `get_form_description(request, obj=None, **kwargs)`

Pydantic request schemas are derived from form fields where possible, while
Django `ModelForm` validation remains authoritative for persistence.

## Changelist And Bulk Editing Hooks

- `get_changelist_form_class(request)`
- `changelist_formset`
- `get_changelist_formset(request, **kwargs)`
- `get_changelist_form_fields_description(request, obj=None, *, form=None)`

List-editable changelist metadata, bulk update request schemas/examples, and
runtime bulk validation use the configured changelist formset. Override
`get_changelist_formset()` when a custom `BaseModelFormSet` should control
prefixes, cross-row validation, or other list-editable formset behavior.

## Query And Permission Hooks

- `get_queryset(request)`
- `get_search_results(request, queryset, search_term)`
- `get_list_display(request)`
- `get_list_filter(request)`
- `get_list_select_related(request)`
- `get_list_prefetch_related(request)`
- `has_module_permission(request)`
- `has_view_permission(request, obj=None)`
- `has_add_permission(request)`
- `has_change_permission(request, obj=None)`
- `has_delete_permission(request, obj=None)`

Object-level hooks are used for detail, mutation, delete, actions, inline,
history, autocomplete, and changelist row metadata where the route has an
object to check.

## Save, Delete, And Response Hooks

- `save_form(request, form, change)`
- `save_model(request, obj, form, change)`
- `save_related(request, form, inline_results, change)`
- `delete_model(request, obj)`
- `delete_queryset(request, queryset)`
- `response_add(request, obj, form, inline_results)`
- `response_change(request, obj, form, inline_results)`
- `response_delete(request, obj_display, obj_id)`

Custom response hooks that return non-default `Status(...)` bodies should
declare `response_add_schema`, `response_change_schema`, or
`response_delete_schema` so OpenAPI remains typed.

Response hook return values are part of the generated-client contract:

- Custom action `input_schema`/`response_schema` models and response-hook
  schemas must emit closed object contracts. Set
  `model_config = ConfigDict(extra="forbid")` on Ninja/Pydantic schema classes
  unless the schema is intentionally a typed map.
- The base `response_add()` and `response_change()` implementations return the
  standard mutation shape generated from the saved object and inline results.
- Plain `response_add()` or `response_change()` dictionaries are wrapped in
  the conventional success status (`201` for add, `200` for change). These
  statuses are advertised with the standard mutation schema, so custom
  add/change bodies should return `Status(200, body)` or `Status(202, body)`
  and declare `response_add_schema` or `response_change_schema`.
- Add/change/delete hooks may return `Status(204, None)` when the mutation
  should commit without a response body. A `204` hook response with a body is
  rejected before the surrounding transaction commits.
- `response_delete()` may return `None` for the default `204` response, a plain
  dictionary for a typed `200` response, or `Status(...)` for an explicit
  status/body pair. Delete hooks that return a body must declare
  `response_delete_schema`.
- Hooks returning custom bodies should declare a schema class, or a
  status-to-schema mapping when different statuses return different shapes.
  A schema class is advertised on `200` and `202` for add/change/delete hooks;
  a mapping is used exactly as provided.
- Hook bodies should be JSON-compatible Pydantic/Ninja response data. They
  should not return Django `HttpResponse` objects, rendered templates, or
  model instances directly.
- Add/change/delete hook bodies are validated against the advertised response
  schema before the surrounding mutation transaction commits. If validation
  fails, the database write is rolled back and the client receives the shared
  typed error response.

## Actions, Inlines, And Routes

- `@action(...)` supports permissions, Pydantic input schemas, and custom
  response schemas.
- Action response bodies are validated against the advertised success or error
  schema inside the action transaction. Invalid bodies roll back action writes;
  `Status(204, None)` is allowed for no-content action responses.
- `InlineModelAdmin`, `TabularInline`, and `StackedInline` use Django formsets
  for validation and typed Pydantic envelopes for add/change/delete rows.
- `route()` and `get_urls()` add sync or async custom site or model routes with
  Ninja-native response, auth, throttle, tags, descriptions, and operation ids.
  Custom route response schemas must emit closed object contracts or typed
  maps; use `model_config = ConfigDict(extra="forbid")` on concrete
  Ninja/Pydantic response models.

Use `admin_view()` around custom views that should enforce admin permissions in
addition to route-level auth.
