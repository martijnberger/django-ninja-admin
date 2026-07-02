# Django Ninja Admin v2 Reimplementation Plan

## Summary

- Build a new Ninja-native package from the empty workspace: distribution `django-ninja-admin`, import package `django_ninja_admin`.
- Target full feature parity with `daemon-bixia/django-api-admin` 1.3.0 before release, but do not preserve DRF imports or old wire shapes.
- Use `django-ninja` 1.6.2 and Pydantic v2; remove `djangorestframework` and `drf-spectacular`.
- Keep Django-admin concepts: site registry, model admins, filters, actions, changelists, inlines, history, autocomplete, view-on-site, checks, and admin log model.

## Public API And Contracts

- Export `site`, `NinjaAdminSite`, `ModelAdmin`, `InlineModelAdmin`, `TabularInline`, `StackedInline`, `action`, `display`, `register`, and admin filter classes from `django_ninja_admin`.
- Usage target:

```python
from django.urls import path
from django_ninja_admin import ModelAdmin, site

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


site.register(Product, ProductAdmin)

urlpatterns = [path("admin-api/", site.urls)]
```

- Replace DRF customization with Ninja/Django-native hooks: `form_class`, `output_schema`, `schema_field_overrides`, `get_form_class()`, `get_output_schema()`, `get_form_description()`, plus existing permission/save/queryset/action hooks.
- Serialization and deserialization should use Pydantic where feasible, while preserving Django `ModelForm`/formset validation where it gives admin-grade behavior.
- Default auth is `ninja.security.SessionAuthIsStaff`; `NinjaAdminSite(auth=...)` accepts any Ninja auth callable, sequence, or explicit `None`.
- Use REST-style routes: `GET /apps`, `GET /apps/{app_label}`, `GET /context`, `GET /permissions`, `GET /history`, `GET /autocomplete`, `GET /view-on-site/{content_type_id}/{object_id}`, and model routes under `/{app_label}/{model_name}` for list, detail, create, update, delete, actions, and bulk list-editable updates.
- Use HTTP status codes instead of a required top-level `status` field. Success and error bodies are typed Pydantic schemas; mutation requests use `{data: {...}, inlines?: {app.model: {add: [], change: [], delete: []}}}`.

## Implementation Changes

- Scaffold packaging with `django>=5.0,<6.1`, `django-ninja>=1.6.2,<2`, `pydantic>=2,<3`, Python `>=3.12`, pytest/ruff dev tooling, and MIT plus Django BSD attribution.
- Port reusable admin logic first: registry, decorators, checks, filters, changelist/query handling, quote utilities, deleted-object collection, action dispatch, inline operation validation, and custom `LogEntry` migration/table.
- Build a lazy `NinjaAdminSite` that constructs a `NinjaAPI` and per-model routers after registration/autodiscovery; registration invalidates router/OpenAPI schema caches.
- Generate Pydantic schemas per registered model/operation for OpenAPI and response serialization; use Django `ModelForm`/formset validation internally for admin-grade create/update/inline behavior.
- Implement all site and model endpoints with Ninja function views, transactions around mutations, existing `has_*_permission` checks, `to_field` validation, protected-delete handling, model action execution, list-editable bulk updates, autocomplete pagination, history filtering, and view-on-site URL resolution.
- Register Ninja exception handlers for auth, permission denied, not found, validation, protected delete, suspicious lookup/to-field errors, and unexpected errors, returning consistent typed error bodies.
- Use Ninja's built-in OpenAPI/docs support, stable operation IDs, model tags, dynamic schemas, and rich response maps instead of drf-spectacular hooks.

## Schema Strategy

Use Django Ninja's native Pydantic machinery as the default schema foundation,
then layer Django-admin-specific behavior only where admin semantics require it.

- Treat Ninja `ModelSchema` / `ninja.orm.create_schema()` semantics as the
  baseline for read/output schemas. Generated output schemas should use
  explicit safe field lists, never blanket `__all__`, and should keep admin
  exclusions such as password fields, readonly/computed fields, relation labels,
  file/image metadata, many-to-many IDs, and `_to_field`-aware relation values.
- Keep write/input schemas form-derived rather than model-derived. Admin writes
  are governed by `ModelForm`, custom form fields, widget cleaning, disabled
  fields, formsets, inline constraints, and changelist formsets, so generated
  Pydantic request schemas should parse, coerce, and document request payloads
  before Django forms remain the authoritative persistence validator.
- Use normal Pydantic/Ninja customization hooks for explicit contracts:
  `output_schema` when callers own the whole response shape,
  `schema_field_overrides` for computed/read fields, and
  `form_schema_field_overrides` for form/input fields whose type cannot be
  inferred precisely.
- Support Ninja's `register_field()` story for custom Django model fields where
  feasible, and document when projects should use `register_field()` versus
  admin-specific override hooks.
- Evaluate Ninja `fields_optional` / `PatchDict` patterns for partial updates,
  but only adopt them where they preserve admin form semantics, inline payloads,
  error locations, OpenAPI component names, and existing mutation hooks.
- Keep generated component names, schema examples, validation-error shapes, and
  OpenAPI references deterministic so frontend clients can diff contracts
  between releases.
- Document that DRF `serializer_class` migration is intentionally out of scope:
  projects should move to `form_class`, Pydantic/Ninja schemas, field override
  hooks, and action input/response schemas.

## Current Parity Status

The package is currently a functional Ninja-native foundation, not a full upstream-parity implementation.

Completed or mostly complete:

- Package scaffold, dependency policy, licenses, app config, default site, lazy API construction, and basic documentation.
- Public exports for `site`, `NinjaAdminSite`, `ModelAdmin`, inlines, decorators, registration, and package-owned admin filter classes.
- Registry coverage now includes option-based registration, duplicate/unregistered errors, abstract-model rejection, swapped-model skipping, and the public `@register` decorator.
- Core site/model routes for apps, context, permissions, history, autocomplete, view-on-site, changelist, detail, add/change/delete, actions, and bulk updates.
- Context metadata honors custom site title/header/url/sidebar settings and uses `NinjaAdminSite.has_permission()` for permission status.
- Permissions metadata includes site-level `has_permission`, registered-model
  permission maps, custom model permission hooks, and is covered for default
  staff-session and explicit `auth=None` sites.
- Default `SessionAuthIsStaff`, explicit `auth=None`, custom auth callable, and multiple Ninja auth callable support.
- Basic Pydantic request envelopes and typed response schemas.
- Dynamic Pydantic output schemas with FK labels, many-to-many IDs, and `schema_field_overrides`.
- `schema_field_overrides` now serialize computed `ModelAdmin` methods, matching the documented Ninja-native output customization pattern.
- Dynamic per-model Pydantic request schemas for create, replace, partial update, and list-editable bulk update payloads.
- Dynamic per-inline Pydantic operation schemas for add/change/delete payloads, exposed under the real `app.model` inline wire keys.
- Disabled Django form fields remain visible in form metadata but are not required by generated parent or inline Pydantic write schemas.
- Dynamic per-model action payload schemas with OpenAPI enums for registered/global action names.
- Custom actions can now declare Pydantic/Ninja input and response schemas through `@action(input_schema=..., response_schema=...)`; input schemas are validated before dispatch and exposed as discriminated per-action OpenAPI payload variants.
- Action system checks now validate `allowed_permissions` entries while preserving custom `has_<permission>_permission()` hooks.
- Global action changes now invalidate the lazy Ninja API/OpenAPI cache so action payload schemas stay current after initial API construction.
- Built-in site routes now advertise typed OpenAPI auth-error responses, while omitting auth-only responses for explicit `auth=None` sites.
- Model routes now advertise richer OpenAPI response maps for typed error bodies, including conditional `401` auth failures and normalized `422` request-validation responses.
- Pydantic/Ninja request validation errors are normalized into typed API error bodies.
- Django `ModelForm` and inline formset validation for create/update/inline mutations.
- Mounted-route tests now cover `save_form`, `save_model`, `save_related`, `response_add`, `response_change`, `delete_model`, `delete_queryset`, and `response_delete` hooks during add/change/delete mutations, plus `save_form` skipping for unchanged bulk rows.
- `response_add` and `response_change` hooks can return Ninja `Status` values for custom success status/body responses, and model mutation routes advertise common alternate success responses in OpenAPI.
- Inline mutations reject duplicate change/delete PKs and rows that attempt to change and delete the same inline object.
- Inline mutation tests now cover unknown inline objects and transaction rollback of parent saves when inline validation fails.
- Inline mutations now distinguish unknown inline IDs from configured-but-forbidden inline operations, returning permission errors for forbidden add/change/delete attempts.
- Inline mutations reject unknown or readonly row fields before formset save so ignored client input cannot silently pass.
- Inline mutations now aggregate server-side add/change/delete row errors before any parent or inline writes occur.
- Admin system checks now reject non-sequence `inlines` configurations before validating individual inline classes.
- Admin system checks now validate inline `extra`, `min_num`, and `max_num`
  option types and ranges before formset construction.
- Admin system checks now validate inline `can_delete` and `show_change_link`
  option types before inline metadata generation.
- Admin system checks now validate inline `fields`, `exclude`,
  `readonly_fields`, and `fieldsets` option shapes before form generation.
- Admin system checks now validate inline `fields`, `exclude`, and
  `readonly_fields` option items, including unknown fields and duplicates.
- Admin system checks now validate inline nested `fieldsets` entries,
  including malformed field declarations, unknown fields, and duplicates.
- Inline admins now support custom `formset` classes and validate that they inherit from Django's `BaseInlineFormSet`.
- Inline admin checks now reject `exclude` entries that remove the parent foreign key field from inline forms.
- Dynamic inline `get_extra()`, `get_min_num()`, and `get_max_num()` hook
  returns are validated before formset construction and produce typed API
  errors for bad values.
- Inline formset mutation rows now normalize Pydantic-cleaned values before
  Django form binding, including `MultiValueField` expansion for custom inline
  forms.
- Bulk list-editable updates use strict row schemas, reject duplicate PKs, and validate all rows before writing.
- Bulk list-editable updates now resolve target rows through the filtered
  changelist queryset so active filters/search constrain editable rows before
  any writes occur.
- Changelist responses now expose structured list-editing formset metadata with
  formset prefixes, management-form counts, row indexes, primary keys,
  primary-key field names, and prefixed editable field descriptions for
  frontend bulk formset rendering.
- List-editable row metadata and bulk updates now honor changelist `_to_field`
  row identity so editable rows can use validated alternate object fields.
- Bulk list-editable updates now skip save hooks and empty change-log entries for unchanged rows, and changed rows also skip log creation when `construct_change_message()` returns no messages.
- Bulk list-editable updates now aggregate server-side row errors before writing.
- Direct delete and default `delete_selected` return structured protected-object and permission-needed details.
- Collected-object delete permission checks now honor object-level delete hooks, including the default `delete_selected` action.
- Direct delete now returns structured permission-needed details when object-level delete hooks deny the target row.
- Default `delete_selected` now has mounted coverage for `select_across` over a
  filtered queryset when an object-level delete hook denies one of the expanded
  rows, preserving all-or-nothing behavior.
- Model detail/form/update/delete routes now support allowed `_to_field`
  lookups and reject bad `_to_field` references with typed validation errors.
- Changelist routes now support allowed `_to_field` lookups by validating the
  requested field and emitting row IDs/object links that use the alternate
  object field.
- History listing now filters by caller-visible models and object-level view/change permissions before pagination and supports app/model/object/action filters plus client-controlled page/page-size pagination, typed bad-param handling, structured model identity, and object detail/form links on each viewable row.
- Autocomplete now returns typed not-found responses for invalid pages, exposes richer pagination metadata, and has coverage for many-to-many source fields and source-field `limit_choices_to` filtering.
- View-on-site route coverage now includes callable hooks that return absolute or protocol-relative external URLs.
- View-on-site now returns absolute URLs from the configured Site domain and falls back to the request host when that Site row is missing.
- Change messages include field labels and inline add/change/delete entries for history/log consumers.
- Inline deletion change messages now preserve deleted object display text instead of falling back to primary keys.
- Actions cover custom return values, empty-selection validation, and `select_across` behavior over filtered changelists.
- Changelist action metadata now includes declared permission names and hides
  actions whose permission hooks deny the current user.
- Admin system checks now reject non-sequence `actions` configurations before validating registered action names and permission hooks.
- Changelist responses expose action UI placement and selection-counter metadata for frontend action controls.
- Changelist responses expose filter state and clear-all-filters query-string
  metadata for frontend reset controls.
- Changelist responses expose facet optionality plus add/remove facet
  query-string metadata for frontend count toggles.
- Changelist responses expose active search state and clear-search query-string
  metadata for frontend search controls.
- Changelist responses now honor `show_full_result_count` and expose `show_admin_actions` metadata.
- Changelist responses now expose admin-style pagination state with `multi_page`, `pagination_required`, and an elided `page_range`.
- Changelist pagination now honors `ModelAdmin.get_paginator()` overrides in
  addition to custom `paginator` classes.
- Changelist ordering metadata now reflects default `ModelAdmin.ordering` and
  marks default-sorted columns when no explicit `?o=` parameter is present.
- Changelist responses now support callable `list_display` entries with stable response keys, labels, display metadata, admin checks, and `admin_order_field` sorting.
- Form descriptions include richer widget, validator, relation, numeric-bound, decimal-precision, choice, disabled, readonly, model `blank`/`null`, uniqueness/index, default, and upload metadata.
- Form descriptions now expose structured `SelectDateWidget` metadata for
  split date-select rendering, including order, generated field names, choices,
  empty choices, and selected values.
- Form descriptions now expose stable model-field identity metadata, including
  field class, internal type, attname, and database column when available.
- Form descriptions now expose aggregated custom form/widget media assets for
  frontend clients.
- Inline form descriptions now expose formset media assets and use
  `formfield_for_dbfield()` customizations from inline admins.
- Inline admins now honor custom `form_class` definitions for formset metadata,
  Pydantic inline payload schemas, and ModelForm validation.
- Add-form descriptions now honor `get_changeform_initial_data()` and
  querystring-derived initial values, including selected relation labels.
- Pydantic request schemas now use native JSON, UUID, and generic IP address
  types for matching Django form fields.
- Pydantic request schemas now use native duration types, and form descriptions
  expose temporal input formats.
- Pydantic request schemas now use structured date/time tuple payloads for
  Django `SplitDateTimeField`, with mutation normalization into Django
  `MultiWidget` form data.
- Pydantic request schemas now recursively derive fixed tuple payloads for
  generic Django `MultiValueField` subfields, including subfield constraints,
  and normalize them into Django `MultiWidget` form data.
- Pydantic request schemas now cover `FilePathField` fixed filesystem choices,
  and form descriptions expose path, match, recursion, and allow-files/folders
  metadata for frontend renderers.
- Pydantic request schemas now validate `ComboField` values through Django's
  stacked subfield cleaners while exposing representable string constraints,
  and form descriptions expose structured combo subfield metadata.
- Form descriptions now expose grouped choice metadata while preserving
  flattened choice values for simple clients.
- Form descriptions now expose typed choice `coerce` metadata and JSON-safe
  coerced choice values so frontend clients can align rendered options with
  generated Pydantic schemas.
- Pydantic request schemas now validate numeric `step_size` constraints and
  expose OpenAPI `multipleOf` hints when they are not offset, while form
  descriptions include step size and offset metadata.
- Pydantic request schemas now run Django date/time/datetime cleaners before
  type validation so custom temporal `input_formats` are accepted by request
  payloads.
- Pydantic request schemas now preserve enum/member validation for typed
  choice fields whose `coerce` hooks produce float, decimal, or UUID values.
- Mutation handling now preserves Pydantic-cleaned Python values when binding
  payloads to Django forms, with targeted normalization for string-oriented
  URL, IP address, and UUID form fields plus mounted-route coverage for those
  scalar form-field bindings.
- Pydantic request schemas now infer typed list entries for multiple-choice
  fields from declared choice values.
- Pydantic request schemas now constrain concrete Django choice values with
  enum-style `Literal` schemas where possible, including grouped choices.
- Pydantic request schemas now infer Django typed choice fields from concrete
  `coerce` hooks such as `int`.
- Pydantic request schemas now validate typed choice fields against declared
  values after coercion while preserving OpenAPI enum metadata.
- Pydantic request schemas now advertise enum values for plain Django choice
  fields whose raw choices are non-JSON scalar values such as `Decimal` or
  `UUID`, using the stringified values Django forms accept.
- Pydantic request schemas now validate Django email form fields using Django's
  email validator.
- Pydantic request schemas now use native URL validation for Django URL form
  fields.
- Pydantic request schemas now parse Django `NullBooleanField` tri-state
  values, including `"unknown"` as `None`, and form descriptions expose
  nullable-boolean metadata.
- Pydantic parent mutation schemas now reject unknown `data` fields before
  Django forms run, matching the stricter inline and bulk row contracts.
- Pydantic request schemas now apply Django-style `CharField.strip` handling
  before generated string constraints such as regex patterns.
- Pydantic parent, inline, and bulk row request schemas now support
  `form_schema_field_overrides` for explicit per-field input/OpenAPI types
  and form-description metadata, including component and route-level examples
  that validate against their generated schemas, while preserving Django form
  validation as the persistence authority.
- Pydantic request schemas now carry Django form string length, field/validator
  regex pattern, numeric bound, and decimal precision constraints into
  generated validation/OpenAPI schemas.
- Pydantic request schemas now carry explicit form-field string length
  validators into generated validation/OpenAPI schemas, including custom
  `CharField` and `ComboField` inputs.
- Pydantic request schemas now carry explicit form-field numeric validators
  into generated validation/OpenAPI schemas, including custom integer, float,
  and decimal fields; custom `FloatField` inputs now advertise OpenAPI `number`
  schemas.
- Form descriptions now expose widget template, option-template, checked-state,
  add-id-index, fieldset, format, microsecond-support, and `MultiWidget`
  subwidget metadata plus Django `BoundField` HTML names, generated IDs, label
  target IDs, `aria-describedby` values, `BoundWidget` option/subwidget names,
  values, labels, selected states, IDs, and attrs, rendered widget attrs,
  rendered grouped-choice optgroups, rendered compound-widget child input
  names/IDs/values, `ClearableFileInput` clear-checkbox names/IDs/labels,
  inline formset prefixes, management-form fields,
  empty-form template rows, per-row form metadata, and
  `show_hidden_initial` hidden initial widget/ID metadata for richer frontend
  rendering.
- Raw-id form field descriptions now include structured lookup request metadata.
- Filter-horizontal and filter-vertical form field descriptions now include
  structured selector metadata.
- Form descriptions now expose JSON-safe field error messages, localization
  flags, `empty_value`, and structured radio/prepopulated field metadata.
- Form descriptions now expose structured validator metadata, including limit
  values and regex patterns, alongside existing validator names.
- Form descriptions now expose effective string and numeric bounds derived from
  explicit form-field validators, including custom `CharField`, `ComboField`,
  integer, float, and decimal inputs.
- Form descriptions now support callable `readonly_fields`, exposing stable
  string names, labels, values, and display metadata including boolean,
  empty-value, and ordering-field hints while accepting them in admin checks.
- Explicit `fields` and `fieldsets` layouts now treat callable readonly fields
  by their stable display names when validating checks and generating
  `ModelForm` classes.
- Bulk list-editable updates now use a dedicated `get_changelist_form_class()`
  hook for generated row schemas, changelist row metadata, and server-side row
  validation.
- Permission hardening for actions, autocomplete, view-on-site, and object-level bulk updates; autocomplete now uses the remote model admin's paginator/search-field hooks and filters returned choices through object-level remote view permissions.
- Autocomplete now resolves related option IDs from the source relation's
  actual target field, including `ForeignKey(to_field=...)` relations to unique
  non-primary-key fields.
- Ninja-native `ChangeList` foundation for validated lookup params, shared action/changelist querysets, search, ordering, pagination, show-all behavior, `list_select_related`, `date_hierarchy`, and facet counts.
- Date hierarchy metadata now exposes field type and active timezone for
  `DateTimeField` buckets, and changelist bucketing explicitly uses the active
  timezone.
- Changelist search now applies distinct results for duplicate-prone many-to-many search paths.
- Changelist search now covers Django-style prefix and lookup-suffix behavior, including non-text `__exact` searches that cast field values to text.
- Package-owned list filter classes for simple, field, choices, related, related-only, boolean, date, all-values, and empty-value filters, with Pydantic-safe filter metadata.
- Date list filters now use Django-admin-style bounded ranges and clear stale grouped date params when switching choices.
- Choices list filters now support explicit `NULL` choices with `__isnull` query behavior.
- All-values list filters now support explicit `NULL` choices with `__isnull` query behavior.
- List filters now reject malformed `__isnull` boolean values with typed lookup errors.
- Related list filters now hide when they have only one non-empty choice, still apply hidden-filter query params, and expose their real lookup keys, matching Django admin's output threshold.
- Related list filters now expose many-to-many empty-relation choices and related-only filters preserve related-admin ordering while limiting choices to used relations.
- Related and related-only list filters now use the remote relation target
  field value in choices and query strings, including
  `ForeignKey(to_field=...)` relations.
- Empty-value list filters now validate `__isempty` values and return typed lookup errors for invalid input.
- Direct changelist lookup params now normalize comma-separated and repeated
  `__in` values plus strict `__isnull` booleans before applying remaining ORM
  filters.
- Simple list filters now hide when `lookups()` returns no choices, matching Django admin.
- Changelist facet handling now has mounted-route coverage for `ShowFacets.NEVER`, `ALLOW`, and `ALWAYS`.
- Field-based `list_filter` tuple entries now validate as two-item `(field, FieldListFilter)` declarations at check and runtime boundaries.
- Invalid changelist lookup values now return typed API errors for both declared filters and direct field lookups.
- `lookup_allowed()` now allows local field lookup suffixes and Django-style `limit_choices_to` reverse-FK lookup parameters while continuing to reject unapproved relational lookups.
- Expanded changelist metadata for display links, sortable columns, multi-column sort state/query strings, selected ordering, search fields, pagination state, facets, and date hierarchy choices.
- Generated changelist query strings now reset stale page parameters for
  filter, ordering, and date hierarchy links while preserving explicit page-size
  state.
- Changelist rows now expose detail, change-form, delete, view-on-site, and object-permission metadata for frontend action rendering.
- Changelist columns now support single-valued relation paths in `list_display`,
  including row values and ordering metadata.
- Date hierarchy metadata now includes clear/back navigation query strings and validates impossible year/month/day combinations.
- Date hierarchy checks and changelist metadata/filtering now support relation paths such as `product__created_at`.
- Date hierarchy navigation now starts at the lowest useful initial level when
  all filtered results share a year or month, matching Django admin's
  drill-down behavior.
- Initial N+1 hardening through automatic `select_related()` for direct relation fields in `list_display`.
- Changelist N+1 hardening now infers `select_related()` paths from single-valued
  relation paths in `list_display`, independent of sortability.
- Changelist N+1 hardening now also infers `select_related()` paths from display callables/methods whose `admin_order_field` traverses FK or one-to-one relations.
- Changelist N+1 hardening now supports explicit `list_prefetch_related` /
  `get_list_prefetch_related()` relation prefetches, including string and
  `Prefetch` entries, for callable display columns that intentionally touch
  many-valued relations.
- Phase 0 parity matrix at `docs/parity-matrix.md`.
- Initial admin system checks for display, form layout, filters, search/order fields, relation widgets, radio fields, widget-option conflicts, date hierarchy, actions, and inlines.
- Relation widget checks now reject reverse relations in `autocomplete_fields` and `raw_id_fields`, preventing frontend metadata for unsupported admin widget targets.
- Autocomplete checks now require related models to be registered with
  `search_fields`, catching endpoint misconfiguration before runtime.
- `prepopulated_fields` system checks now validate dict shape, target field suitability, source-field list shape, and source-field existence.
- `readonly_fields` system checks now reject duplicate string or callable
  entries before they can duplicate form metadata.
- `sortable_by` system checks now validate sequence shape, item types, and membership in `list_display` before changelist sorting runs.
- Admin system checks now reject `ordering` configurations that combine random ordering (`"?"`) with other fields.
- Admin system checks now allow Django ORM ordering expressions and validate `F("field")` references when possible.
- Admin system checks now validate `list_per_page` and `list_max_show_all` types
  and ranges before changelist pagination runs.
- Admin system checks now validate custom `paginator` classes before changelist pagination runs.
- Admin system checks now validate `save_as`, `save_on_top`, and `view_on_site` option types before form/config metadata generation.
- Admin system checks now validate `save_as_continue`, action placement/counter flags, and `show_full_result_count` option types before form/changelist metadata generation.
- `ShowFacets` is exported from the package root and admin system checks now reject malformed `show_facets` values before changelist facet metadata generation.
- Admin system checks now validate `search_help_text` before changelist metadata serialization.
- Admin system checks now validate `empty_value_display` before changelist and
  readonly metadata serialization.
- Admin system checks now reject empty `list_display` configurations before changelist runtime.
- Custom `form_class` system checks now validate `ModelForm` inheritance and catch forms whose declared `Meta.model` does not match the registered admin model.
- `formfield_overrides` system checks now validate field-class keys, mapping-shaped overrides, and string formfield keyword names.
- `schema_field_overrides` system checks now validate mapping shape, string
  field names, and one/two-item tuple override declarations before dynamic
  output schema generation.
- Admin system checks now reject direct many-to-many and reverse relation fields in `list_display`, preventing raw related managers from leaking into changelist cells.
- Admin system checks now reject `list_editable` fields removed from generated forms by `fields`, `fieldsets`, or `exclude`, preventing silent bulk-update no-ops.
- Admin system checks now reject manual-through many-to-many fields in explicit `fields` and `fieldsets` form layouts.
- Admin system checks now reject first-column `list_editable` fields unless an explicit `list_display_links` target is configured.
- Admin system checks now reject duplicate entries in `list_display_links` and
  `exclude`, plus non-string/non-callable `list_display_links` entries.
- Admin system checks now validate `list_select_related` types and relation paths before changelist runtime.
- Admin system checks now reject `filter_horizontal`/`filter_vertical` on many-to-many fields with custom through models.
- `get_changelist()` and `get_changelist_instance()` hooks for changelist customization.
- Initial site/model custom view support through `admin_view()`, `get_urls()`, and `route()` helpers, including OpenAPI registration, typed custom-route error response maps, raw bound method wrapping, route tags/descriptions, hidden routes, explicit route-level `auth=None`, route-level auth sequence overrides, decorator-style route registration, and stable unique operation IDs for generated and explicit multi-method custom routes.
- Custom admin view tests now cover named Ninja response schemas together with route-level auth overrides.
- Display decorator metadata for descriptions, ordering, booleans, and per-field empty values is reflected in changelist columns/results.
- Changelist display metadata now also recognizes labels, boolean flags, and empty-value text attached to model property getters.
- File field read serialization now uses typed Pydantic metadata (`name`, `url`) and form descriptions expose multipart/current-file hints.
- Image field read serialization now uses typed Pydantic metadata (`name`, `url`, `width`, `height`) and form descriptions expose image/upload hints plus configured width/height field names.
- Existing file fields can be cleared in JSON mutations by sending explicit `null`, using Django's form clear semantics and recording change messages.
- File fields can now be written through multipart create/update routes whose JSON form parts are validated by the generated Pydantic mutation schemas before Django `ModelForm` file handling runs.
- Image fields now have mounted multipart validation coverage for invalid files
  and valid PNG uploads, including persisted dimensions and typed response/form
  metadata.
- Generated Pydantic write schemas now expose file and image fields as
  string-or-null JSON values instead of untyped payload slots, with runtime
  request-validation coverage for malformed JSON values and image clear
  mutations.
- Multipart file parts now satisfy required file fields during Pydantic request
  validation so clients do not need to duplicate uploaded filenames inside the
  JSON `data` part.
- Form descriptions now expose file-extension validator metadata for upload
  controls, with multipart rejection coverage for disallowed extensions.
- Multipart create-route OpenAPI schemas now mark required file parts as
  required alongside the JSON `data` part.
- Many-to-many fields now have Pydantic write schemas, typed output schemas,
  JSON-safe change-form values, form relation metadata, output serialization,
  and create/update persistence coverage.
- Model choice fields now have typed output schemas with enum values where
  possible, including nullable choice fields.
- Model primary keys now have non-null typed output schemas for persisted admin
  response bodies.
- Decimal model fields now preserve `max_digits` and `decimal_places`
  constraints in generated output schemas.
- Bounded numeric model fields now preserve min/max validator constraints in
  generated output schemas, including nullable positive integer fields.
- Multiple numeric model-field validators now collapse to the strictest
  generated output-schema bounds, including relation target schemas.
- Email and URL model fields now preserve OpenAPI `format` metadata in
  generated output schemas, including nullable URL fields.
- Generic IP address model fields now use native Pydantic IP address types in
  generated output and relation-target schemas.
- JSON model/form fields now use explicit JSON-compatible Pydantic schemas for
  generated request and response components.
- Binary model fields now serialize as deterministic base64 strings in JSON
  responses and advertise base64 content metadata in generated output schemas,
  including nullable binary fields.
- Model-field regex validators, including `SlugField` patterns, now propagate
  to generated output schemas and relation target schemas.
- Model-field string length validators now propagate to generated output
  schemas and relation target schemas, including stricter `MaxLengthValidator`
  limits and explicit `MinLengthValidator` limits.
- Zero-offset model `StepValueValidator` constraints now propagate to generated
  output schemas and relation target schemas as OpenAPI `multipleOf` metadata.
- Blank-but-non-null model fields now have non-null typed output schemas for
  persisted admin response bodies.
- Relation write schemas and OpenAPI examples now infer input types from the
  related primary key or explicit `to_field_name` target.
- Relation output schemas now infer serialized foreign-key `attname` types from
  the related target field, including non-PK `to_field` relations.
- Relation target-field constraints such as string `max_length` now propagate to
  foreign-key write schemas and many-to-many output/write item schemas.
- Admin-owned model-field type inference now honors Ninja `register_field()`
  mappings for custom field internal types, including custom primary keys,
  relation output IDs, and form-derived relation inputs.
- Generated output examples now use many-to-many target-field values and
  Ninja-registered custom field types so examples validate against their own
  component schemas.
- Generated output examples now include valid values for common explicit
  `schema_field_overrides` types such as UUID, temporal, URL, IP address, and
  constrained annotated/container Pydantic types.
- Form field descriptions now expose per-field admin widget intent for autocomplete, raw-id, radio, filter-horizontal/filter-vertical, and prepopulated fields.
- Relation form field descriptions now include structured related-model identity,
  selected option labels, target-field type metadata, and mount-aware
  endpoint/query metadata for autocomplete and raw-id frontend clients.
- Filter-horizontal and filter-vertical metadata now includes stacking state,
  source verbose names, related-model identity, and target-field type metadata
  for dual-select renderers.
- Relation form field descriptions now include selected option labels for existing foreign-key and many-to-many values.
- Relation form field descriptions now expose model `limit_choices_to` constraints,
  including callable constraints and structured `Q` objects.
- Readonly form descriptions now expose display labels, values, boolean flags, and empty-value fallbacks for admin methods and model properties.
- Parent and inline form descriptions now expose normalized fieldset layout
  metadata with section names, classes, descriptions, flattened fields, and row
  groupings alongside raw Django fieldsets.
- Custom `form_class` and generated-form `formfield_*` customization hooks are covered through mounted Ninja routes for write-schema generation, custom widget attributes, Django form validation, and mutation persistence.
- History responses now include Django-style human-readable change-message text for parent and inline add/change/delete operations, plus model identity and object-link metadata for frontend routing/rendering.
- Semantic OpenAPI contract tests now cover core site/model route operation IDs,
  tags, security, request body schemas, generated JSON mutation examples,
  success response schemas, changelist/inline formset response metadata
  components including normalized fieldset layout schemas, typed error response
  maps, and concrete `ErrorResponse` examples for validation, permission, and
  protected-delete bodies.
- `FieldDescription.attrs` OpenAPI metadata now includes a concrete example
  showing bound-field, rendered-widget, and rendered-subwidget keys.
- Multipart OpenAPI schemas now mark JSON-encoded `data` and `inlines` form
  parts with `contentMediaType: application/json`.
- API and authentication docs now cover Ninja-native customization hooks such as `form_class`, `output_schema`, and `schema_field_overrides`, plus default/custom/disabled auth patterns.
- Local release gates now use `just` for lint, tests, package smoke, and aggregate checks.
- Package smoke tooling builds the wheel, installs it into an isolated target, verifies public API imports, and checks dependency metadata for absent DRF/drf-spectacular dependencies.
- Sample-project smoke tooling installs the built wheel into a temporary Django project, registers a model, mounts `site.urls`, opens docs/OpenAPI, and exercises the registered model app list/changelist.
- Full sample-project tooling installs the built wheel into a richer temporary
  Django project and exercises autocomplete, filters/search, list-editable bulk
  updates, inlines, actions, multipart file upload, history, custom routes, and
  view-on-site URLs.
- Release hardening docs now include a changelog and explicit alpha/beta/stable checklist.
- GitHub Actions now runs the `just` gates across Django 5.0, 5.1, 5.2, and an experimental 6.0 lane on Python 3.12+.
- CI now has a PostgreSQL lane using env-driven test database settings and `just postgres-test`.
- An initial copyright/license audit records MIT package licensing, Django BSD attribution, upstream parity references, and no-DRF dependency checks.
- Initial behavioral tests and no DRF/drf-spectacular runtime dependency.

Known non-parity areas:

- Changelist behavior now supports `_to_field` validation/row identity, custom paginator hooks, default ordering metadata including visible custom queryset `order_by()` columns, deterministic primary-key fallback ordering, last-page pagination, row/result indexes, per-row cell display metadata, page-result/range metadata, page-choice metadata, list-editable formset prefixes/management metadata, presence-style show-all handling, pagination/show-all query strings, search/filter-state clear metadata, direct repeated/comma-separated `__in` and `__isnull` lookup value preparation, facet toggle links, bounded date hierarchy filtering including maximum-year bounds, lowest-useful initial date hierarchy levels, explicit relation prefetches for callable display columns, and preservation of unrelated lookup params when resetting stale page/order links, but is still not fully equivalent to upstream `ChangeList`; remaining query-string edge cases, deeper result rendering semantics, deeper list-editable formset edge cases, additional date hierarchy edge cases, and broader N+1 hardening still need work.
- Filter handling now covers common Django admin filter families, bounded date filter ranges, and initial facets, but it still needs semantic comparison against Django/upstream edge cases and richer facet/count behavior.
- System checks now cover common invalid configurations, many-to-many `list_display` mistakes, `list_display_links` item-type conflicts, `list_editable` item-type/form-layout conflicts, duplicate `list_editable`/`readonly_fields`, callable readonly field layout names, `list_select_related` and `list_prefetch_related` mistakes, `date_hierarchy` type/path/field mistakes, pagination and inline option type/range/shape/item mistakes, autocomplete target registration/searchability, text option types, schema override shapes, and relation/widget option conflicts, but they do not yet match Django's complete check coverage or IDs.
- Action metadata and payload schemas now advertise action names, permission requirements, discriminated per-action input payload variants, and optional custom response schema unions.
- Field metadata now covers common widget, custom widget attrs, widget template/option/checked-state hints, Django bound-field HTML names/IDs/ARIA descriptions, rendered widget attrs, bound option/subwidget metadata, rendered grouped-choice optgroups, rendered compound-widget child inputs, normalized fieldset layouts, hidden-initial widgets/IDs, inline formset prefixes/management forms/empty forms/row metadata, nullable booleans, disabled form fields, relation, flat/grouped choice, typed raw choice values, structured validator details, error-message, `empty_value`, localization, string stripping, numeric, decimal, readonly display values, model `blank`/`null`/default/index/unique/editable attributes, initial file/image attributes including storage backends without public URLs, typed file/image JSON write schemas, clearable file widget metadata, explicit per-field input schema overrides, file-extension upload constraints, basic file/image clearing, multipart file uploads, mounted image validation/dimension persistence, generated-form `formfield_*` customizations, dynamic inline extra form descriptions, basic many-to-many values/widgets, and admin widget intent for raw-id/radio/prepopulated/autocomplete/filter-horizontal/filter-vertical fields including dual-select stacking, related-model metadata, and mount-aware autocomplete/raw-id endpoint hints, but deeper storage edge cases, custom model fields, and specialized widget behavior still need deeper parity.
- Save/delete and response hooks, including custom `Status` responses from add/change/delete hooks, inline formsets, typed operation schemas, dynamic inline count hook validation, inline multivalue normalization, protected-delete details, model/object-level history permission filtering, autocomplete pagination/paginator/search-field hooks and object-level result filtering, `_to_field` changelist/detail/update/delete lookup support, object-level permission checks for custom actions, inline permission checks, readonly/unknown inline field rejection, unknown parent mutation field rejection, richer inline delete messages, dedicated changelist form hooks for list-editable rows, unchanged and empty-log bulk-row handling, row-indexed inline/bulk errors including permission denials, and stricter bulk validation are now used, but upstream-style error semantics and edge-case coverage are not exhaustive.
- OpenAPI generation works and now has semantic contract coverage for core site/model routes, generated JSON mutation examples, generated per-model component examples, built-in site-route success examples, multipart JSON form parts and required file parts, changelist/inline formset response metadata components, normalized fieldset layout schemas, `FieldDescription.attrs` examples, typed `ErrorResponse` examples and component snapshots, generated/explicit custom-route operation IDs including multi-method uniqueness, custom-route typed error maps, custom action input/response schemas, alternate action success response maps for custom `Status` returns, and global action cache invalidation, but broader model-route snapshots are still needed before release.
- Admin extensibility is still young: custom view routing, direct/decorator route registration, stable generated route operation IDs, route metadata/auth overrides, named response-schema coverage, site/route-level multi-auth coverage, and display metadata exist, but deeper override-hook parity still needs work.
- Release hardening has local/CI `just` gates, wheel import smoke, a clean sample-project smoke, initial PostgreSQL CI coverage, and an initial copyright audit; remaining work is to confirm CI results and repeat the audit before release candidates.
- Upstream fixture parity and contract comparisons have not been ported beyond the initial parity matrix and targeted local registry/route contracts.

## Implementation Phases

### Phase 0: Parity Baseline And Fixture Port

Goal: make upstream parity measurable before adding more behavior.

- Build a parity matrix from `django-api-admin` 1.3.0 modules and `tests/mock_app/tests.py`, grouped by site routes, model routes, changelist, filters, forms, actions, inlines, deletion, logs, OpenAPI, and checks.
- Port the upstream mock app into local tests using Django Ninja Admin names and v2 JSON envelopes.
- Mark each upstream behavior as `implemented`, `intentionally changed`, `not applicable`, or `missing`.
- Add regression tests for every already-implemented behavior so later phases do not drift.
- Add CI commands for `ruff`, `pytest`, package build, import smoke, and no-DRF/no-drf-spectacular import checks.

Acceptance:

- A `docs/parity-matrix.md` or equivalent test manifest exists.
- Existing local behavior is mapped to upstream behaviors.
- Test count is broad enough that a changelist/filter/action regression cannot pass unnoticed.

### Phase 1: Changelist And Filter Parity

Goal: replace the simplified changelist/filter path with Django-admin-grade behavior.

- Port a Ninja-native `ChangeList` equivalent with validated lookup params, `lookup_allowed()`, `to_field`, ordering, search, pagination, show-all behavior, result counts, `list_select_related`, `sortable_by`, and `date_hierarchy`.
- Implement or adapt admin filter classes instead of only re-exporting Django's classes: `SimpleListFilter`, `FieldListFilter`, `RelatedFieldListFilter`, `RelatedOnlyFieldListFilter`, `BooleanFieldListFilter`, `ChoicesFieldListFilter`, `DateFieldListFilter`, `AllValuesFieldListFilter`, and `EmptyFieldListFilter`.
- Preserve query-string behavior for filter choices and ordering links.
- Add facet support for `ShowFacets.NEVER`, `ALLOW`, and `ALWAYS`.
- Ensure invalid lookups, suspicious lookup params, bad pages, and invalid ordering return typed errors.
- Expand changelist response schemas for result metadata, display links, editable fields, filters, facets, ordering columns, and action UI metadata.

Acceptance:

- Upstream changelist/filter/search/order/pagination tests have Ninja equivalents.
- Common Django admin list filters produce equivalent choices and query behavior.
- Large changelists do not issue avoidable N+1 queries for common FK/list-display cases.

### Phase 2: Pydantic Request/Response Schema Generation

Goal: make serialization/deserialization Pydantic-first where feasible, without losing Django form semantics.

- Make Ninja `ModelSchema` / `create_schema()` the explicit read-schema
  baseline, using admin-safe explicit field lists plus `custom_fields` for
  admin-specific output such as relation labels, many-to-many IDs, file/image
  metadata, typed choices, computed fields, and non-null persisted IDs.
- Generate form-derived Pydantic request schemas for create, replace, partial
  update, bulk list-editable update, action payloads, and inline operations.
- Keep Django `ModelForm`/formset validation as the authoritative persistence
  validator, but use Pydantic to parse, coerce, validate obvious type errors,
  and document request bodies before forms run.
- Support field-type overrides for model fields, form fields, computed display
  fields, file/image URL fields, custom admin fields, and custom Django model
  fields registered through Ninja `register_field()` where feasible.
- Distinguish read schemas from write schemas, including readonly fields,
  excluded fields, password fields, m2m fields, FK labels, custom output fields,
  disabled form fields, partial-update optionality, and inline operation
  variants.
- Make OpenAPI components stable and deterministic across registrations.
- Add schema cache invalidation when admins are registered/unregistered or output hooks change.
- Add contract tests that compare generated schema semantics, not only route
  behavior, for representative models, custom forms, custom actions, inlines,
  custom field overrides, and file/image routes.

Acceptance:

- OpenAPI shows concrete per-model request and response components instead of
  only `dict[str, Any]`.
- Pydantic validation errors return consistent typed error bodies.
- File/image/custom fields and custom model/form field overrides have explicit
  schema tests.

### Phase 3: Mutation, Inline, And Delete Semantics

Goal: match Django admin and upstream mutation behavior under real-world edge cases.

- Complete add/change/delete parity for `save_form`, `save_model`, `save_related`, `delete_model`, `delete_queryset`, and response hooks.
- Expand inline operation support for partial changes, unknown objects, duplicate PKs, deleted changed rows, min/max, readonly fields, parent permission constraints, nested validation errors, and transaction rollback.
- Improve list-editable bulk updates to follow changelist formset semantics, including per-row errors and unchanged rows.
- Finish protected-delete semantics for direct delete and `delete_selected`, including returned protected object descriptions and permission-needed details.
- Improve change-message construction to include field labels and inline additions/changes/deletions.
- Align direct update logging with Django admin by skipping empty change-log entries while preserving save hooks.
- Add tests for bad `_to_field`, protected delete, invalid actions, `select_across`, empty selections, and custom action return values.

Acceptance:

- Mutation routes are atomic across parent and inline work.
- Log entries and change messages match Django-admin semantics where the v2 API has equivalent concepts.
- Direct delete and default bulk delete are covered by protected object and permission tests.

### Phase 4: Admin API Surface, Checks, And Extensibility

Goal: support mature Django-admin customizations, not just basic model CRUD.

- Port/administer real checks for `list_display`, `list_display_links`, `list_editable`, `fieldsets`, `fields`, `exclude`, readonly fields, inlines, autocomplete fields, raw-id fields, filters, search fields, ordering, actions, and custom forms.
- Implement site/model custom view support: `admin_view`, site `get_urls()`, model admin `get_urls()`, and safe route registration into the Ninja API.
- Support per-view/per-route tags, operation IDs, permissions, auth overrides, and response schemas for custom admin views.
- Expand decorators to cover Django admin display semantics such as boolean display, ordering, empty values, descriptions, and admin action permissions.
- Add `get_changelist()`, `get_changelist_instance()`, and related hooks where useful for compatibility with Django-admin mental models.

Acceptance:

- Invalid admin configurations fail through Django checks rather than runtime surprises.
- A project can add custom site/model admin endpoints without bypassing auth, permission checks, or OpenAPI generation.

### Phase 5: Field, Form, And Media Parity

Goal: make forms rich enough for a frontend to render a serious admin UI.

- Expand form-field descriptions for widgets, choices, validators, help text, initial values, required/blank/null, disabled/readonly, max/min, decimal precision, upload constraints, and relation metadata.
- Add file and image field handling for reads, writes, clear/delete behavior, existing file URLs, storage errors, and multipart request support where Ninja supports it.
- Support many-to-many, raw ID, radio fields, filter-horizontal/filter-vertical, prepopulated fields, autocomplete fields, and readonly/display values in form descriptions.
- Add support for custom `form_class`, custom field widgets, and continue
  broadening per-field schema overrides in forms and OpenAPI.
- Ensure form descriptions use dynamic inline hooks such as `get_extra()`, `get_min_num()`, and `get_max_num()`.

Acceptance:

- A frontend can render add/change forms for common Django model field types without hardcoded per-model knowledge.
- File/image field tests pass for create, update, clear, and response serialization.

### Phase 6: OpenAPI, Docs, And Contract Stability

Goal: make generated docs a release-quality contract.

- Stabilize operation IDs, tags, response maps, error schemas, pagination schemas, inline schemas, and model component names.
- Document every built-in route with examples for success and error responses.
- Add snapshot or semantic OpenAPI tests that tolerate ordering differences but catch contract regressions.
- Document that DRF `serializer_class` hooks are unsupported and provide Ninja-native customization hooks: `form_class`, `output_schema`, and `schema_field_overrides`.
- Document authentication choices: default staff-session auth, custom Ninja auth, multiple auth callables, and explicit unauthenticated APIs with `auth=None`.

Acceptance:

- `/admin-api/docs` is useful for client generation.
- OpenAPI changes are intentional and reviewed through tests.

### Phase 7: Release Hardening

Goal: reach the beta/stable release bar: full measured parity or explicit v2
contract differences for every remaining gap.

- Run the full local test suite across Django 5.0, 5.1, 5.2, and supported Django 6.0.x when practical.
- Test against SQLite and PostgreSQL.
- Add package build checks and install smoke tests in a clean sample Django project.
- Audit copyright notices for Django-derived and upstream-derived code.
- Add `CHANGELOG.md`, release checklist, version policy, and explicit alpha/beta/stable criteria.
- Confirm no DRF or drf-spectacular imports at runtime or in dependency metadata.

Acceptance:

- A clean Django project can install the package, register realistic models, mount `site.urls`, open docs, and complete the parity matrix.
- All parity gaps are either implemented or explicitly documented as v2 intentional differences.

## Testing, Validation, And Verification Plan

Testing should be treated as a product surface, not a final polish step. The
goal is to make parity measurable, keep generated OpenAPI trustworthy, and
catch admin edge cases before client projects discover them.

### Test Principles

- Prefer semantic parity assertions over byte-for-byte JSON comparisons. v2 is
  intentionally Ninja/Pydantic-native, but equivalent admin behavior should be
  provable through permissions, querysets, validation results, side effects,
  log entries, and rendered metadata.
- Treat each feature as incomplete until implementation, schema behavior,
  route behavior, documentation, and matrix evidence agree. A feature that
  works locally but lacks contract coverage should remain `partial`.
- Every behavior marked `implemented` in `docs/parity-matrix.md` needs evidence:
  at least one test, smoke gate, documented intentional contract difference, or
  source-level reason why the behavior is not applicable.
- Every wire-shape change should include a request/response schema assertion,
  an OpenAPI assertion, or both. Schema drift should be visible in review.
- Tests should preserve the architecture: Pydantic parses, coerces, validates
  obvious request contract errors, and documents OpenAPI; Django
  `ModelForm`/formsets remain the authoritative admin persistence validators.
- New features should usually land with one behavior test, one negative/error
  test, and one schema or metadata assertion when the public API surface
  changes.
- When a feature depends on generated schemas, test the schema directly and
  through a mounted route. Direct schema tests catch inference mistakes quickly;
  mounted-route tests prove Ninja parsing, auth, exception handlers, and
  response serialization still work together.
- Treat generated examples as contract fixtures. Every request or response
  example added to Pydantic models or OpenAPI should be validated against the
  schema that advertises it.
- Tests should be allowed to be a little redundant where the public contract is
  generated. A direct schema assertion, an OpenAPI assertion, and a route test
  may all cover the same field because they protect different failure modes.
- Prefer fewer broad "happy path" tests and more targeted edge tests for admin
  semantics: object-level permission denial, malformed lookup input,
  unsupported `_to_field`, stale inline IDs, duplicate bulk rows, multipart
  parse failures, protected deletes, and rollback after late validation.
- Bias toward proving the same contract from multiple angles when the behavior
  is generated or lazy: direct helper tests for inference, mounted-route tests
  for integration, OpenAPI tests for clients, and installed-wheel smoke tests
  for packaging.
- Test the negative space deliberately. A strong v2 contract should prove that
  unknown fields, over-posted inline aliases, forbidden actions, invalid
  relation targets, stale objects, and denied permissions fail before partial
  state leaks into the database.
- Keep verification executable. Whenever the plan says "review", prefer a
  named `just` recipe, pytest marker, script, generated artifact, or checklist
  item that can be re-run by another maintainer.

### Verification Lanes

Use several complementary verification lanes instead of treating the full test
suite as the only source of confidence.

- Implementation lane: focused unit, schema, route, and mutation tests added in
  the same slice as the code change. This lane should be fast enough to run
  repeatedly while developing.
- Contract lane: OpenAPI component/route assertions, semantic OpenAPI diffs,
  generated examples, generated-client smoke, stable operation IDs, and typed
  error-shape checks.
- Parity lane: `docs/parity-matrix.md`, upstream-equivalent fixture scenarios,
  behavior comparisons, and explicit notes for intentional v2 differences.
- Installation lane: wheel build, isolated install, dependency metadata checks,
  migrations, app loading, public imports, `/admin-api/docs`, and
  `/admin-api/openapi.json`.
- Environment lane: SQLite by default, PostgreSQL for ORM-sensitive behavior,
  and supported Django/Python matrix coverage before beta/stable claims.
- Exploratory lane: manual sample-project walkthroughs and API-client trials
  that discover gaps, followed by automated regression tests before any parity
  status is upgraded.
- Performance lane: query-count and large-result guardrails for changelist,
  filters, facets, autocomplete, history, inline form descriptions, and bulk
  actions.

### Evidence Levels

Not every feature needs the same proof immediately, but each status should mean
something concrete.

- Prototype evidence: direct helper or schema tests prove the local behavior,
  but mounted-route, OpenAPI, package, or parity evidence is still missing.
  These rows remain `partial`.
- Route evidence: mounted Ninja tests cover auth, parsing, serialization,
  transactions, and exception handling for the behavior. This is the minimum
  bar for most user-facing endpoint claims.
- Contract evidence: OpenAPI/schema assertions prove the advertised contract
  matches the runtime behavior. This is required before client-visible schema
  changes are considered release-ready.
- Parity evidence: upstream-equivalent fixture behavior is covered or an
  intentional v2 difference is documented. This is required before claiming
  full parity for a row.
- Release evidence: the feature survives package smoke, sample-project smoke,
  and the relevant CI/database gates from an installed artifact. This is
  required before beta/stable release claims.

### Coverage Sources

- Port upstream behavioral coverage: registration, app list/index/context,
  permission denial, view-on-site, autocomplete, detail, actions, default delete
  action, select-across, invalid actions, delete/protected delete/bad
  `_to_field`, add/change forms, add/change mutations, pagination, changelist,
  schema generation, and inline add/change/delete/error cases.
- Keep a local parity fixture app with models that exercise the hard cases:
  custom primary keys, `ForeignKey(to_field=...)`, many-to-many fields,
  manual-through many-to-many fields, choices, nullable/blank fields, decimals,
  email/URL/IP/UUID/duration fields, JSON fields, files/images, custom forms,
  custom widgets, inlines, protected relations, object-level permissions, and
  custom actions.
- Add focused fixture variants for schema generation: custom Django model fields
  registered with Ninja `register_field()`, explicit `output_schema`,
  `schema_field_overrides`, `form_schema_field_overrides`, disabled form
  fields, readonly/computed fields, file/image fields, and nullable relation
  targets.
- Run contract-style semantic comparisons against upstream fixtures where
  practical: same registered model behavior, permissions, filtering/search/order
  results, inline constraints, log entries, and change messages, without
  requiring identical JSON envelopes.
- Maintain small reusable factories for auth users, object-level permission
  hooks, inline parent/child records, protected relation graphs, large
  changelists, uploaded files/images, and custom forms/widgets so new tests do
  not become brittle one-off setups.
- Track each upstream behavior in `docs/parity-matrix.md` as `implemented`,
  `partial`, `missing`, or `changed`, with evidence pointing to tests, docs, or
  code.

### Definition Of Done For A Feature Slice

Each implementation slice should leave behind enough evidence that a future
refactor can understand and preserve the contract.

- Behavior is covered through mounted Ninja routes, not only direct helper
  tests, whenever auth, parsing, serialization, transactions, or exception
  handlers are involved.
- Pydantic request schemas are tested directly for at least one valid payload
  and one invalid payload when a slice changes input shape, coercion,
  optionality, constraints, aliases, or examples.
- Output schemas are tested directly when a slice changes serialization,
  computed fields, relation values, file/image values, custom fields, or
  `output_schema` / `schema_field_overrides` behavior.
- OpenAPI is asserted when a slice changes route presence, operation IDs, tags,
  request bodies, response status maps, examples, auth/error maps, component
  names, multipart bodies, or custom route/action schemas.
- Database side effects are asserted for mutations: parent rows, inline rows,
  many-to-many relations, uploaded files, log entries, change messages, and
  rollback after late failures.
- Permission-sensitive behavior includes both allowed and denied users, and
  object-level hooks when the corresponding Django admin hook exists.
- `docs/parity-matrix.md` is updated with precise evidence before claiming an
  implemented row; broad "covered by tests" notes should be replaced by test
  names, smoke gates, or documented v2 differences.
- `CHANGELOG.md` is updated for user-visible contract changes, new validation
  behavior, new OpenAPI shape, new admin hook support, or narrowed parity gaps.
- The release checklist is updated when the slice adds a new gate, fixture app,
  sample-project scenario, supported environment, or manual verification step.

### Pydantic And ModelSchema Verification Track

Django Ninja's documented `ModelSchema` / `create_schema()` behavior should be
treated as the reference point for generated read schemas, with admin-specific
extensions tested explicitly where we diverge.

- Read schema tests should confirm explicit safe field lists, never accidental
  `__all__`, deterministic component names, stable examples, nullable fields,
  constrained strings/numbers/decimals, email/URL/IP formats, JSON fields,
  registered custom field mappings, relation target IDs, many-to-many IDs,
  file/image metadata, and computed/admin display fields.
- Read serialization tests should validate both Pydantic `model_validate()` /
  `model_dump()` behavior and mounted-route JSON output so Ninja response
  serialization and admin helper serialization cannot drift apart.
- Partial update tests should verify unset fields are not treated as `None`.
  If Ninja `fields_optional` or `PatchDict` patterns are adopted later, they
  must preserve admin form semantics, hook order, inline aliases, and existing
  error locations before replacing current generated partial schemas.
- Write schema tests should prove form-derived Pydantic models reject unknown
  fields, coerce expected scalar/container values, preserve cleaned Python
  values for Django forms, expose realistic examples, and keep disabled or
  readonly fields out of writable requirements.
- Custom field tests should cover both Ninja `register_field()` mappings for
  Django model fields and admin `schema_field_overrides` /
  `form_schema_field_overrides` for cases where the admin contract is more
  specific than the model-field mapping.
- OpenAPI tests should verify that the schema a client sees matches the schema
  used by route parsing, including multipart JSON parts, inline operation
  aliases, bulk-row dictionaries, action payload discriminators, custom route
  response maps, and typed error bodies.
- Generated examples should be self-validating: every example advertised in a
  Pydantic schema or OpenAPI route should be passed through the corresponding
  schema in tests or smoke tooling.

### Near-Term Testing Investments

- Add a semantic OpenAPI diff helper that normalizes generated documents,
  compares route maps/components/request bodies/response maps/examples, and
  prints expected-versus-unexpected changes. Store reviewed diffs or short
  expected-change notes for intermediate releases.
- Add stable schema snapshot tests for representative models instead of trying
  to snapshot every dynamic component. Cover one simple model, one relation
  intensive model, one inline-heavy model, one file/image model, one custom
  field model, and one custom-action model.
- Add a small generated-client smoke test before beta. It can use a lightweight
  OpenAPI consumer or generated Python/TypeScript client, but it should prove
  that list/detail/create/update/delete/action/inline payloads are usable from
  the published schema.
- Add a Django Ninja alignment suite for read schemas based on documented
  `ModelSchema`/`create_schema()` behavior: explicit safe field lists, no
  accidental `__all__`, optional PATCH-style fields where applicable, custom
  field mappings from `register_field()`, nullable fields, relation target
  types, and override fields.
- Add a write-schema contract suite for form-derived Pydantic schemas:
  required/optional fields, `fields`/`exclude`, disabled and readonly fields,
  `form_schema_field_overrides`, typed choices, relation target fields,
  multipart JSON parts, inline aliases, list-editable rows, and custom action
  inputs.
- Add mutation invariant tests that deliberately fail late in a request and
  assert no parent, inline, bulk, file/image, log-entry, or change-message side
  effects survive the rollback.
- Add an upstream-fixture comparison command that runs selected v1/Django-admin
  semantic scenarios against local fixtures and records whether the v2 response
  is equivalent, intentionally changed, or still missing.
- Add a parity-evidence checker that scans `docs/parity-matrix.md` for vague
  evidence notes, missing test/gate references, stale `partial` rows with no
  remaining-work text, and `implemented` rows whose cited test names no longer
  exist.
- Add a release-candidate gate that runs the broad verification set in one
  command: lint, unit/route tests, package smoke, sample-project smoke,
  generated-client smoke, parity report, OpenAPI diff input validation, and
  PostgreSQL tests when database credentials are available.
- Add mutation fuzz/property-style tests for envelope structure, inline aliases,
  duplicate row IDs, action names, malformed `_to_field`, unexpected fields,
  and invalid relation identifiers. Keep these focused on contract stability
  rather than broad random ORM state.
- Add pytest markers or naming conventions for `schema`, `openapi`, `route`,
  `postgres`, `smoke`, `performance`, and `parity` tests so focused gates can
  be run without losing the full `just check` gate.
- Add query-count/performance guardrails for the highest-risk admin views
  before claiming beta readiness: changelist relation columns, filters/facets,
  autocomplete, history, and inline form descriptions.
- Expand CI reporting so failed gates point to the affected parity-matrix row
  or release criterion where practical.

### Evidence And Traceability

- Treat `docs/parity-matrix.md` as the parity evidence ledger. Each
  `implemented` row should name the behavior covered, the fixture or scenario
  that proves it, and the local test file or smoke gate that would fail if the
  behavior regressed.
- Keep `partial` rows explicit about both sides of the boundary: what is
  already proven and what remains unproven. Avoid broad claims such as
  "mostly compatible" unless the matrix lists the missing cases.
- Add a short evidence note to `CHANGELOG.md` for every user-visible contract
  improvement, especially schema, validation, permission, mutation, and
  metadata changes. Release notes should be traceable back to tests or a smoke
  gate.
- When an upstream behavior is intentionally different in v2, capture the
  reason, the new contract, and the verification coverage. Intentional
  differences should not look like untested gaps.
- Keep a lightweight release-candidate checklist that links to the final
  parity matrix review, OpenAPI diff review, CI matrix run, PostgreSQL run,
  sample-project smoke, package smoke, and copyright/license audit.
- Do not move a parity row from `partial` to `implemented` in the same change
  that only adds code. The change should also add the evidence trail: focused
  test name, OpenAPI/schema assertion when relevant, and any intentional v2
  contract note.
- Keep a small "known unverified behavior" list for features that work in
  manual exploration but lack enough automated coverage. This is separate from
  implementation gaps and should be burned down before beta.
- When a regression test is added for a bug, link it back to the affected
  endpoint, schema, or matrix row so future refactors preserve the reason the
  test exists.
- Keep reviewed OpenAPI artifacts, parity reports, and release-candidate smoke
  logs long enough to compare at least the previous intermediate release and
  the next candidate. The project should be able to answer "what contract
  changed?" without reconstructing history from memory.

### Test Tiers

- Unit tests: small reusable pieces such as quote/unquote helpers, lookup
  validation, filter value preparation, schema type inference, form-field
  constraint extraction, deleted-object collection, action dispatch, inline
  operation validation, and error normalization.
- Schema tests: generated Pydantic models should be tested directly with
  `model_validate()` and `model_json_schema()` for valid coercions, invalid
  payloads, exact error locations, examples, optionality, constraints, enum
  literals, formats, and nullability.
- Route tests: every built-in endpoint should be exercised through mounted
  Ninja URLs so auth, request parsing, request state, response serialization,
  transactions, and exception handlers are tested together.
- Metadata tests: changelist metadata, form descriptions, inline formset
  metadata, field/widget attrs, relation hints, readonly values, action
  metadata, pagination state, facets, and generated query strings should have
  direct assertions because frontend clients will rely on them.
- Mutation tests: create, update, partial update, delete, default actions,
  custom actions, inline operations, multipart writes, and list-editable bulk
  updates should assert both response bodies and database/log side effects.
- Smoke tests: package install, public imports, no DRF/drf-spectacular
  dependencies, sample-project setup, docs availability, OpenAPI availability,
  and a minimal registered-model workflow should stay in the local and CI gates.
- Contract-consumer tests: generated examples, OpenAPI documents, and any
  generated or hand-written client fixtures should be exercised as consumers
  would use them, not only inspected as static JSON.
- Compatibility matrix tests: run representative behavioral and contract tests
  across supported Django 5.0+ versions and Python 3.12+ so compatibility
  claims are backed by execution, not dependency ranges alone.
- Fixture-comparison tests: run selected Django-admin or upstream-equivalent
  scenarios against the same local fixture data and compare semantic outcomes:
  visible objects, allowed actions, filtered counts, validation errors, log
  entries, delete protections, and change messages.
- Release-candidate tests: exercise the package as an installed artifact,
  preferably from the same wheel that would be uploaded, and verify that source
  tree assumptions do not hide packaging, migration, static asset, or settings
  issues.

### Required Gates By Change Type

- Schema-generation changes should include direct Pydantic schema assertions,
  OpenAPI component assertions, mounted-route validation for at least one valid
  and one invalid payload, and sample examples that validate against the
  generated schema.
- Changelist/filter changes should include fixture data that proves result
  ordering, counts, pagination, query-string metadata, invalid-lookup handling,
  and at least one query-count or prefetch/select-related assertion when the
  change touches relation rendering.
- Mutation changes should include success, validation failure, permission
  failure, transaction rollback, log/change-message, and hook-order assertions
  when applicable.
- Inline changes should include add/change/delete combinations, duplicate or
  unknown row identities, permission-denied rows, dynamic formset hook behavior,
  nested error locations, and parent rollback assertions.
- Permission/auth changes should run through mounted Ninja URLs and cover
  default staff sessions, anonymous users, non-staff users, object-level hooks,
  custom auth callables, auth sequences, route-level overrides, and explicit
  `auth=None` behavior where relevant.
- File/image/media changes should include JSON mutation behavior, multipart
  behavior, clear/delete semantics, storage URL edge cases, invalid upload
  rejection, persisted metadata, and OpenAPI multipart request-body assertions.
- Documentation-only changes should at least be reviewed against the current
  parity matrix and changelog. If the documentation changes a public contract,
  add or update a contract test in the same slice.
- Release-prep changes should run the broadest practical gate available in the
  environment. A release may proceed from a narrower local gate only when the
  missing wider gate is recorded with a reason and followed by CI or a later
  verification pass.
- Version/dependency changes should run package smoke, sample-project smoke,
  no-DRF/no-drf-spectacular dependency checks, and at least one installed-wheel
  OpenAPI/docs request.
- Matrix-only changes should be reviewed against code and tests; if a row moves
  toward `implemented`, the same change should add or cite concrete evidence.

### Validation Layers

- Pydantic request validation should reject malformed parent `data`, inline
  operation rows, bulk rows, custom action payloads, multipart JSON parts,
  unknown fields, invalid relation IDs, invalid enum values, malformed
  date/time values, file/image clear values, and bad override types before
  Django forms persist anything.
- Generated output schemas should be checked against Ninja
  `ModelSchema`/`create_schema` expectations where feasible: explicit safe
  field lists, no accidental `__all__`, registered custom field types,
  relation target types, string/numeric/decimal constraints, email/URL formats,
  typed choices, nullable fields, file/image metadata, and computed overrides.
- Form-validation tests should prove that Pydantic parsing does not replace
  admin-grade `ModelForm` and formset validation: forms remain authoritative
  for persistence, cross-field validation, uniqueness, disabled fields,
  readonly rejection, custom clean methods, model validation, and file/image
  validation.
- Inline validation should cover add/change/delete permission failures, unknown
  IDs, duplicate IDs, change-and-delete conflicts, readonly fields, unknown
  fields, min/max/extra constraints, custom inline formsets, dynamic inline
  hooks, and parent rollback when inline validation fails.
- Mutation tests should assert atomicity: parent saves, inline saves, bulk row
  changes, log entries, and file/image writes should roll back together when
  later validation fails.
- Permission tests should cover site-level auth, model-level permissions,
  object-level permissions, action permissions, inline add/change/delete
  permissions, autocomplete remote-model permissions, history visibility,
  custom-route auth overrides, multi-auth, and explicit `auth=None` APIs.
- Error tests should assert status codes, stable error `code` values, field or
  row locations, protected-object details, permission-needed details, and
  validation messages where clients need deterministic behavior.
- Cross-layer validation should prove that Pydantic, Django forms, model
  validation, database constraints, and exception handlers report compatible
  error locations. Clients should not need to special-case the same invalid
  field differently depending on which layer rejected it.
- Validation tests should include both JSON and multipart entry points when a
  feature supports files/images or JSON form parts, because Ninja parsing and
  Django form binding exercise different failure modes.
- Validation should include "too much input" cases: unknown parent fields,
  unknown inline aliases, unknown inline row fields, unknown bulk PKs,
  duplicate IDs, unexpected action payload keys, and unexpected query params
  where the admin contract promises strictness.

### Validation Scenario Matrix

Build and maintain a small matrix of validation scenarios so new features are
checked consistently across layers.

- Parent writes: create, replace, partial update, custom `form_class`,
  disabled fields, readonly fields, unknown fields, uniqueness, model
  validation, save hooks, response hooks, and rollback after late failures.
- Inline writes: add/change/delete in one payload, duplicate IDs, stale IDs,
  unknown inline aliases, unknown row fields, readonly fields, dynamic
  `get_extra()` / `get_min_num()` / `get_max_num()` hooks, custom formsets,
  permission denial, and parent rollback.
- Bulk list-editable writes: filtered queryset constraints, `_to_field` row
  identity, unchanged rows, duplicate row IDs, unknown row IDs, strict row
  schemas, hook order, log-entry creation, and rollback after aggregate
  validation errors.
- Actions: missing selections, invalid action names, hidden actions, custom
  action permissions, object-level permissions, `select_across`, filtered
  querysets, custom Pydantic action input, custom action responses, default
  delete action, protected deletes, and all-or-nothing side effects.
- Reads: detail serialization, changelist serialization, relation labels,
  many-to-many IDs, computed fields, `display()` metadata, file/image metadata,
  custom `output_schema`, and object-level view/change filtering.
- Queries: search, ordering, filters, facets, date hierarchy, pagination,
  preserved query strings, invalid lookup names, invalid lookup values,
  unsupported `_to_field`, and suspicious lookup rejection.
- Site routes: apps, app detail, context, permissions, history,
  autocomplete, view-on-site, custom routes, auth overrides, explicit
  `auth=None`, and multi-auth.
- Error paths: 400 request contract errors, 401 auth failures, 403 permission
  failures, 404 missing objects, 409 protected deletes/conflicts, 422
  Pydantic validation errors, and normalized unexpected errors.
- Multipart paths: file upload, image upload, required file fields, malformed
  JSON form parts, clearable file/image values, storage URL failures, image
  dimension persistence, and OpenAPI multipart request bodies.

### OpenAPI And Contract Verification

- Add semantic OpenAPI tests for every built-in route group: site routes,
  changelist/detail/form routes, create/update/delete routes, multipart routes,
  bulk routes, action routes, history, autocomplete, and custom admin routes.
- Snapshot or semantically diff generated OpenAPI components for representative
  models so component names, required fields, examples, status maps, auth-error
  maps, validation-error maps, and multipart request bodies cannot drift
  silently.
- Verify read schemas follow Ninja `ModelSchema`/`create_schema` semantics where
  possible, while preserving admin-specific custom fields such as FK labels,
  many-to-many IDs, file/image metadata, typed choice enums, relation target
  types, field constraints, registered custom fields, and computed fields.
- Verify write schemas are form-derived: required/optional fields, disabled
  fields, partial update optionality, constraints, choice literals, typed
  relation IDs, file/image clearing, inline aliases, bulk rows, and action input
  schemas should all appear in OpenAPI.
- Keep generated examples realistic enough for client generation and smoke
  tests: examples should validate against their own schemas.
- Add OpenAPI diff review before beta/stable release candidates, with expected
  changes called out in release notes and unexpected changes treated as release
  blockers.
- Keep stable operation IDs, tags, response maps, schema component names, and
  error components under test so generated clients can upgrade predictably.
- Before beta, generate at least one client from the OpenAPI document or run an
  equivalent schema-consumer smoke test. The goal is to catch contracts that are
  technically valid OpenAPI but awkward or unusable for real clients.
- Maintain a small expected-change log for OpenAPI diffs between intermediate
  releases. A removed field, renamed component, changed required field, changed
  status map, or changed error shape should be treated as a release decision,
  not incidental churn.
- Verify OpenAPI from an installed wheel, not only the source tree, before
  beta/stable candidates. Generated contracts should survive normal package
  installation, app loading, migrations, and URL mounting.
- Keep a minimal client-consumer fixture that discovers operation IDs from the
  OpenAPI document instead of hard-coding route URLs. This catches accidental
  operation-ID churn and proves advertised examples are useful to consumers.

### Verification Artifacts

Keep lightweight artifacts for important verification passes so releases can be
audited without re-discovering context.

- Store or attach normalized OpenAPI documents for release candidates and
  intermediate releases that intentionally change the public contract.
- Store semantic OpenAPI diff summaries with expected changes annotated by
  route/component/status code/example.
- Store parity reports for release candidates, including counts by status,
  rows lacking evidence, and the list of remaining `partial` rows.
- Store package-smoke and sample-project smoke logs for release candidates,
  especially the wheel path, installed version, Django version, Python version,
  and exercised routes.
- Store PostgreSQL/database gate summaries when they are run, including the
  database backend, Django version, and any skipped environment-sensitive tests.
- Keep manual walkthrough notes short and structured: scenario, expected
  behavior, observed behavior, follow-up test added or gap recorded.
- For any intentional v2 contract difference, keep the before/after behavior,
  rationale, and test coverage in the parity matrix or release notes.

### Gate Profiles

Use named gate profiles so local development stays fast while release evidence
keeps getting stronger.

- Fast slice gate: focused pytest target for the changed behavior, focused
  schema/OpenAPI assertion when applicable, and `just parity-report` when a
  matrix row changes.
- Default local gate: `just check`, covering lint, the full SQLite pytest
  suite, package smoke, and sample-project smoke.
- Contract gate: `just openapi-diff` with reviewed artifacts plus
  `just generated-client-smoke` for installed-project OpenAPI consumption.
- Database gate: `just postgres-test`, especially for ORM lookups, date/time
  bucketing, JSON fields, constraints, protected deletes, transactions,
  ordering, and facets/counts.
- Release-candidate gate: default local gate, contract gate, database gate,
  parity report review, copyright/license audit, changelog review, and
  installed-wheel sample-project verification from the candidate artifact.
- Exploratory gate: manual sample-project walkthrough plus notes converted
  into tests before a parity claim is upgraded.

### Maturity Gates

Use release maturity labels to make the verification bar explicit.

- Alpha/intermediate releases may ship with `partial` parity rows, but must run
  `just check`, `just parity-report`, package smoke, and sample-project smoke
  locally or in CI. Release notes should state that parity remains incomplete.
- Late-alpha releases should add `just sample-project-full`,
  `just generated-client-smoke`, and a reviewed OpenAPI diff for any public
  contract changes since the previous release.
- Beta candidates require no `missing` parity rows, no `implemented` rows
  lacking evidence, reviewed remaining `partial` rows, generated-client smoke,
  expanded sample-project verification, and PostgreSQL coverage for
  ORM-sensitive features.
- Stable candidates require every parity row to be `implemented` or
  intentionally `changed`, with evidence; reviewed OpenAPI diffs; passing CI
  matrix for supported Django/Python versions; installed-wheel sample-project
  verification; PostgreSQL verification; and no known DRF/drf-spectacular
  import/dependency regression.
- Emergency patch releases may run a narrower gate only when the fix is
  clearly scoped and the skipped gates are recorded in the release notes with a
  follow-up verification task.

### CI And Automation Plan

- Keep the default pull-request gate close to `just check` so contributors get
  fast feedback: lint, full SQLite tests, package smoke, and sample-project
  smoke.
- Add a contract job that runs semantic OpenAPI diff validation against the
  previous reviewed artifact when contract fixtures are present.
- Add an installed-wheel job that builds once, installs that wheel into clean
  sample projects, and runs docs/OpenAPI/sample workflows from the artifact.
- Add a PostgreSQL job for ORM-sensitive tests and run it on release branches,
  nightly, and before beta/stable candidates.
- Add a generated-client job before beta so a schema consumer exercises route
  discovery, operation IDs, request bodies, response maps, and examples.
- Add a parity-report job that fails only on objective release-blocking
  conditions for the current maturity level: missing evidence for
  `implemented` rows, unexpected `missing` rows for beta, or unresolved
  non-intentional gaps for stable.
- Add artifact upload for OpenAPI JSON, OpenAPI diff summaries, parity reports,
  package-smoke logs, sample-project logs, and PostgreSQL summaries on release
  candidate runs.

### Database, Version, And Environment Matrix

- Run the normal local gate with SQLite through `just check`.
- Run PostgreSQL coverage through `just postgres-test`, especially for lookup
  behavior, ordering, facets/counts, transactions, constraints, protected
  deletes, JSON fields, case sensitivity, and date/time handling.
- Exercise supported Django versions in CI: Django 5.0, 5.1, 5.2, and supported
  Django 6.0.x when practical, on Python 3.12+.
- Keep the package smoke test building a wheel, installing into an isolated
  target, importing the public API, and checking dependency metadata for absent
  DRF/drf-spectacular dependencies.
- Keep the sample-project smoke test installing the built wheel into a clean
  Django project, adding `django_ninja_admin` to `INSTALLED_APPS`, registering a
  model, mounting `site.urls`, opening `/admin-api/docs`, and exercising core
  authenticated routes.
- Add an expanded sample project before beta that includes realistic relations,
  inlines, custom actions, file/image fields, list filters, search, ordering,
  custom auth, and a custom admin route.

### Performance And Regression Checks

- Add query-count tests for changelist pages with FK columns, relation-path
  columns, callable display columns, many-to-many display columns, filters,
  facets, autocomplete, history rows, and form relation labels.
- Add large-result tests for pagination, show-all behavior, select-across
  actions, bulk updates, history pagination, date hierarchy, facets, and
  autocomplete page boundaries.
- Add regression tests for cache invalidation after model registration,
  unregistration, global action changes, custom output schema changes, custom
  auth changes, custom routes, and schema override changes.
- Add malformed-input tests for suspicious lookups, invalid ordering, invalid
  pages, invalid `_to_field`, malformed inline payload aliases, duplicate bulk
  PKs, invalid multipart JSON, unexpected parent fields, invalid action names,
  and unsupported file/image JSON values.
- Add migration/log-model checks that verify the package-owned `LogEntry` table
  can be migrated into a clean project and keeps expected indexes/relations.
- Track test gaps separately from implementation gaps. Some features may be
  functionally present but not release-ready until they have PostgreSQL,
  query-count, OpenAPI, or sample-project coverage.

### Test Data And Fixture Strategy

- Keep fixture models small but deliberately weird. Prefer models that combine
  realistic admin complexity: custom primary keys, `to_field` relations,
  nullable and blank fields, choices with non-string values, file/image fields,
  JSON fields, many-to-many fields, protected relations, and custom managers.
- Keep separate fixtures for read serialization and write validation. Read
  fixtures should stress output shape and labels; write fixtures should stress
  Pydantic coercion, Django form cleaning, inline formset behavior, and
  transaction rollback.
- Build reusable fixture builders for relation graphs, protected delete graphs,
  inline parent/child sets, list-filter data, large changelists, file/image
  uploads, auth users, and custom admin classes. New tests should compose these
  instead of creating ad hoc models or database state whenever possible.
- Include negative fixtures for malformed payloads, stale object IDs,
  permission-denied objects, invalid lookup strings, bad `_to_field` values,
  invalid multipart JSON, unsupported file clear values, and broken custom
  field mappings.
- Keep a sample project that mirrors real installation usage. It should be more
  than a smoke app before beta: use migrations, mounted URLs, session auth,
  registered admins, inlines, files/images, actions, filters, search, custom
  auth, and a custom admin route.

### Verification Tooling Backlog

- Keep `just openapi-diff` available for semantic OpenAPI contract reviews
  between release candidates.
- Keep `just sample-project-full` for the expanded sample project and reserve
  `just sample-project-smoke` for the fast release gate.
- Keep `just generated-client-smoke` available for the OpenAPI consumer check.
- Keep `just parity-report` available to summarize parity-matrix statuses,
  evidence notes, missing rows, partial rows, and rows with placeholder
  evidence.
- Add `just postgres-test` to the default release-candidate checklist even when
  it remains outside the fastest local `just check` loop.
- Add a package-install matrix job that builds the wheel once and installs that
  artifact into clean Django projects, rather than testing only from the source
  tree.
- Add an OpenAPI artifact upload in CI for release candidates so reviewers can
  inspect the exact contract that would ship.

### Manual And Exploratory Verification

- Keep a small manual verification script or checklist for opening the sample
  project docs, inspecting OpenAPI, creating an object, editing it, uploading a
  file/image, running an action, using autocomplete, deleting an object, and
  viewing history.
- Before beta, exercise the API from at least one generated or hand-written
  client to confirm the OpenAPI contract is practical for consumers.
- Review frontend-rendering metadata manually for representative add/change
  forms, inline formsets, changelists, filters, facets, pagination controls,
  raw-id/autocomplete widgets, file/image widgets, and readonly/computed fields.
- Periodically compare representative responses with Django admin UI behavior
  using the same fixture data, especially around changelist links, filter
  choices, date hierarchy navigation, delete protection, and log messages.
- Use manual verification to discover missing assertions, then convert those
  findings into automated tests before marking the behavior complete. Manual
  checks are useful evidence for exploration, but not enough for stable parity
  claims.

### Release Verification

- Every implementation slice should run focused tests for the touched behavior
  plus at least one OpenAPI/schema contract test when the wire shape changes.
- Before each intermediate release, run `just check`, review
  `docs/parity-matrix.md` for stale evidence, and record notable behavior and
  coverage additions in `CHANGELOG.md`.
- Before beta/stable release candidates, additionally run PostgreSQL tests,
  review CI matrix results, rerun the copyright/license audit, inspect the
  parity matrix for stale or vague evidence, run package and sample-project
  smoke tests from the built artifact, and generate or review OpenAPI contract
  diffs.
- No beta/stable release should ship with an `implemented` parity claim that
  lacks evidence, an unreviewed OpenAPI diff, a failing smoke test, a known DRF
  dependency/import regression, or an undocumented intentional v2 difference.
- Acceptance: a clean Django project can install the package, add
  `django_ninja_admin` to `INSTALLED_APPS`, register realistic models, mount
  `site.urls`, open `/admin-api/docs`, and exercise every parity feature
  successfully or see the remaining behavior documented as an intentional v2
  difference.

## Assumptions

- This is a v2 package, not a drop-in replacement for existing DRF clients.
- Alpha releases may continue while parity is being built, but beta/stable
  release candidates require full measured parity or explicit v2 contract
  differences for every remaining gap.
- DRF `serializer_class` customizations are intentionally unsupported; use `form_class`, `output_schema`, and/or `schema_field_overrides`.
- The implementation may reuse/port Django-derived logic with BSD notices and upstream MIT-attributed logic where appropriate.
