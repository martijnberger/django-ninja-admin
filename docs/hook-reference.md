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

## Actions, Inlines, And Routes

- `@action(...)` supports permissions, Pydantic input schemas, and custom
  response schemas.
- `InlineModelAdmin`, `TabularInline`, and `StackedInline` use Django formsets
  for validation and typed Pydantic envelopes for add/change/delete rows.
- `route()` and `get_urls()` add sync or async custom site or model routes with
  Ninja-native response, auth, throttle, tags, descriptions, and operation ids.

Use `admin_view()` around custom views that should enforce admin permissions in
addition to route-level auth.
