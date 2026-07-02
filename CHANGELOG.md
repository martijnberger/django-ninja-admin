# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

- Added inline formset prefix, management-form, empty-form, and per-row
  prefixed bound-field metadata to form descriptions.
- Added list-editable changelist formset prefix, management-form counts, and
  per-row prefixed bound-field metadata for bulk-edit renderers.
- Added semantic OpenAPI coverage for changelist and inline formset response
  metadata components.

## 0.1.18 - 2026-07-02

- Exposed Django `BoundField` HTML names, generated IDs, label target IDs, and
  hidden-initial IDs in form descriptions for frontend renderers.

## 0.1.17 - 2026-07-02

- Added inline admin checks for malformed nested `fieldsets` entries and
  duplicate or unknown fieldset fields.
- Added inline admin checks for malformed `fields`, `exclude`, and
  `readonly_fields` option items, including unknown fields and duplicates.
- Added inline admin checks for malformed `fields`, `exclude`,
  `readonly_fields`, and `fieldsets` option shapes.
- Hardened inline admin checks to reject non-boolean `can_delete` and
  `show_change_link` option values.
- Validated dynamic inline `get_extra()`, `get_min_num()`, and `get_max_num()`
  hook returns before formset construction, returning typed API errors for bad
  values.
- Hardened inline count-option checks to reject boolean, negative, and
  impossible min/max values before formset construction.
- Hardened admin pagination checks to reject boolean, zero, and negative
  pagination option values before changelist runtime.
- Exposed Django widget option-template, checked-attribute, add-id-index, and
  microsecond-support metadata in form descriptions.
- Exposed Django form field `empty_value` metadata in form descriptions.
- Added Pydantic request-schema and form-description support for Django
  `NullBooleanField` tri-state values.
- Exposed Django `show_hidden_initial` metadata in form field descriptions,
  including generated hidden initial names and hidden widget details.
- Added generated OpenAPI request examples for JSON create, update, bulk
  list-editable, and action routes.
- Added `form_schema_field_overrides` for parent, inline, and list-editable
  Pydantic request schemas and form descriptions, plus system checks for
  malformed declarations.
- Applied Django-style `CharField.strip` handling in generated Pydantic request
  schemas before constraints run and exposed `strip` in form descriptions.
- Forbid unknown parent `data` fields in generated create/update Pydantic
  request schemas instead of letting Django forms ignore them.
- Added admin system checks for malformed `schema_field_overrides` hook
  configurations.
- Normalized direct changelist lookup params for comma-separated `__in` values
  and repeated `__in` query params plus strict `__isnull` booleans before
  applying ORM filters.
- Added an admin system check for invalid `empty_value_display` option values.
- Added a `get_changelist_form_class()` hook and routed bulk list-editable
  row schemas, metadata, and validation through it.
- Allowed explicit `fields`/`fieldsets` layouts to reference callable readonly
  fields by their stable display names.
- Tightened generated Pydantic write schemas for file and image fields from
  untyped JSON values to string-or-null values and added JSON clear coverage
  for image fields.
- Let multipart file parts satisfy required file fields during Pydantic payload
  validation, avoiding duplicate filename requirements in JSON form parts.
- Exposed file-extension validator metadata in form descriptions for upload
  controls and covered extension rejection on multipart uploads.
- Marked required file parts as required in multipart create-route OpenAPI
  schemas.
- Marked multipart `data` and `inlines` OpenAPI string parts with
  `contentMediaType: application/json`.
- Added mounted-route `ImageField` upload coverage that rejects non-images and
  persists valid images with typed width/height metadata.
- Kept file field serialization and form metadata usable when a storage backend
  does not provide public URLs.
- Capped changelist date-hierarchy bounds at the maximum representable year so
  `9999` year/month/day filters return typed responses instead of overflowing.
- Added row-indexed `403` error details for object-level permission denials
  during bulk list-editable updates.
- Added `202` OpenAPI response coverage for custom delete response hooks.
- Made inline form descriptions include the actual number of extra blank rows
  resolved by dynamic inline formset hooks.
- Added structured form choice options with typed `raw_value` metadata while
  preserving the existing display-oriented `choices` pairs.
- Made custom model actions honor object-level permission hooks before
  dispatching selected changelist rows.
- Marked changelist columns as default-sorted when a custom
  `ModelAdmin.get_queryset()` `order_by()` clause maps to visible list-display
  columns.

## 0.1.16 - 2026-07-02

- Added deterministic default OpenAPI operation IDs for custom site/model
  admin routes that do not provide an explicit `operation_id`, including
  multi-method custom routes.
- Made explicit `operation_id` values unique for multi-method custom admin
  routes by adding deterministic HTTP-method suffixes.
- Added standard typed error response maps to custom site/model admin routes
  while preserving explicit response-map entries.
- Made `/context` permission metadata honor `NinjaAdminSite.has_permission()`
  overrides and added custom site metadata coverage.
- Added typed OpenAPI auth-error response maps for built-in apps, context,
  and permissions site routes.
- Added `has_permission` to `/permissions` responses and made built-in site
  route auth-error response maps honor `auth=None` sites.
- Added conditional `401` OpenAPI error response maps for protected built-in
  site and model admin routes.
- Added changelist page-result and row-range metadata for paginated,
  show-all, and empty result sets.
- Added changelist first/previous/next/last page query-string metadata that
  preserves active filters, search, page size, and ordering.
- Added structured changelist page choices with selected state and query
  strings for page-range rendering.
- Added page-local and filtered-result row indexes to changelist rows.
- Added changelist show-all and clear-show-all query-string metadata.
- Made changelist date hierarchy start at the lowest useful initial level when
  all filtered results share a year or month.
- Added an admin system check for non-string, non-callable
  `list_display_links` entries.
- Added changelist filter-state metadata and clear-all-filters query strings.
- Added changelist facet toggle metadata and add/remove facet query strings.
- Added changelist active search metadata and clear-search query strings.
- Added changelist `_to_field` validation plus alternate row IDs and object
  links when an allowed object field is requested.
- Added a Django-admin-style `ModelAdmin.get_paginator()` hook and made
  changelists use it.
- Added changelist metadata for default `ModelAdmin.ordering` and marked
  default-sorted columns in response metadata.
- Made list-editable row metadata and bulk updates honor changelist `_to_field`
  row identity.
- Made changelist show-all mode follow Django admin's presence-based `all`
  query parameter behavior.
- Added Django-admin-style deterministic primary-key fallback ordering for
  changelists whose active ordering does not include a non-null unique field
  or unique constraint.
- Switched changelist date hierarchy filtering to Django-admin-style bounded
  `gte`/`lt` ranges while preserving the public year/month/day query params.
- Added an admin system check that rejects non-string `date_hierarchy`
  configurations before field-path resolution.
- Aligned bulk list-editable updates with direct change routes by skipping
  empty change-log entries when `construct_change_message()` returns no
  messages.
- Made autocomplete pagination use the remote model admin's
  `get_paginator()` hook.
- Preserved string `order_by()` clauses from custom `ModelAdmin.get_queryset()`
  implementations in changelist ordering before applying deterministic
  primary-key fallback ordering.
- Made autocomplete use the remote admin's `get_search_fields()` hook when
  checking whether search is configured.

## 0.1.15 - 2026-07-02

- Allowed `response_add` and `response_change` hooks to return Ninja `Status`
  values for custom success statuses and bodies.
- Added OpenAPI response-map coverage for common custom mutation success
  statuses.
- Added admin system checks for duplicate and non-string `list_editable`
  entries.
- Kept disabled Django form fields visible in form metadata while making them
  optional in generated parent and inline Pydantic write schemas.

## 0.1.14 - 2026-07-02

- Added structured list-editing row metadata to changelist responses, including
  row index, primary-key field, row primary key, and editable field
  descriptions.
- Limited bulk list-editable updates to the filtered changelist queryset so
  rows outside active filters/search are rejected before any writes occur.
- Added active-timezone metadata and explicit timezone-aware bucketing for
  `DateTimeField` changelist date hierarchies.
- Normalized Pydantic-cleaned inline row values into Django formset data,
  including `MultiValueField` expansion for custom inline forms.
- Added structured `SelectDateWidget` form metadata for split date-select
  rendering, including part order, generated field names, choices, empty
  choices, and selected values.
- Added an admin system check rejecting duplicate `readonly_fields` entries,
  including duplicate callable readonly fields.

## 0.1.13 - 2026-07-01

- Added native Pydantic request schema typing and mutation normalization for
  Django `SplitDateTimeField` payloads.
- Added recursive Pydantic request schema typing and mutation normalization for
  generic Django `MultiValueField` payloads.
- Added `FilePathField` request schema coverage and form metadata for path,
  match, recursion, and allowed target kinds.
- Added `ComboField` request validation/schema hints and subfield metadata for
  stacked Django form validators.
- Added numeric `step_size` request validation/OpenAPI hints and form metadata,
  including offset step validation through Django form cleaners.
- Added Django temporal form-field cleaners to Pydantic request schemas so
  custom date, time, and datetime input formats are accepted before persistence.
- Added typed-choice enum/member validation for float, decimal, and UUID
  coercion hooks.
- Preserved Pydantic-cleaned Python values when binding mutation payloads to
  Django forms, including custom temporal, URL, IP address, and UUID form
  fields.

## 0.1.12 - 2026-07-01

- Added JSON-safe form field error-message and localization metadata, plus
  structured radio and prepopulated field descriptors.
- Added structured form field validator metadata for frontend form rendering.
- Added native Pydantic request schema typing for Django typed choice fields
  whose `coerce` hook uses a concrete Python type.
- Added enum-style Pydantic request schema validation for concrete Django
  choice values, including grouped choices.
- Added post-coercion enum validation for Django typed choice form fields.
- Added native Pydantic request schema validation for Django email form fields.
- Added native Pydantic request schema typing for Django URL form fields.
- Added Pydantic request schema constraints for Django form string lengths,
  field/validator regex patterns, numeric bounds, and decimal precision.

## 0.1.11 - 2026-07-01

- Added native Pydantic request schema typing for duration form fields and
  exposed temporal input formats in form field descriptions.
- Added structured raw-id widget metadata to form field descriptions.
- Added typed Pydantic request schema entries for multiple-choice form fields
  based on their declared choice values.
- Added structured filter-horizontal/filter-vertical widget metadata to form
  field descriptions.

## 0.1.10 - 2026-07-01

- Added custom `form_class` support for inline formsets, including admin checks,
  form metadata, and mutation validation through the inline `ModelForm`.
- Added `get_changeform_initial_data()` support so add-form descriptions expose
  querystring and hook-provided initial values, including relation labels.
- Added richer Pydantic request schema types for JSON, UUID, and generic IP
  address form fields.
- Added form widget template, fieldset, format, and `MultiWidget` subwidget
  metadata to form field descriptions.

## 0.1.9 - 2026-07-01

- Added relation `limit_choices_to` metadata to form field descriptions,
  including callable and structured `Q` object constraints.
- Added stable model-field identity metadata to form field descriptions,
  including field class, internal type, attname, and database column when
  available.
- Added form-level media metadata to form descriptions so custom widget CSS and
  JavaScript assets are available through mounted Ninja form routes.
- Added inline formset media metadata and routed inline formset fields through
  `formfield_for_dbfield()` customization hooks.

## 0.1.8 - 2026-07-01

- Added automatic `select_related()` inference for relation-path fields in
  `list_display`, even when those columns are not sortable.
- Added changelist display and sorting support for single-valued relation paths
  in `list_display`.
- Added an admin system check rejecting empty `list_display` configurations.
- Added selected relation labels to form field metadata for foreign-key and
  many-to-many fields.
- Added Django-style human-readable change-message text to history responses,
  including inline add/change/delete wording.
- Added OpenAPI response maps for built-in site-route error responses.

## 0.1.7 - 2026-07-01

- Added current page and page-size metadata to history pagination responses.
- Added structured relation metadata and autocomplete request parameters to
  form field descriptions.
- Added count, page, page-size, and next/previous metadata to autocomplete
  pagination responses while preserving the existing `more` flag.
- Added mounted-route coverage for `save_form()` during create/change
  mutations and bulk list-editable updates.
- Added richer changelist pagination metadata with `multi_page`,
  `pagination_required`, and an elided `page_range` for frontend controls.
- Improved `lookup_allowed()` parity with Django admin by allowing local field
  lookup suffixes and `limit_choices_to` reverse-FK lookup parameters while
  preserving relational lookup validation.

## 0.1.6 - 2026-07-01

- Added admin system checks rejecting non-sequence `inlines` and `actions`
  configurations.
- Added relation-path support for `date_hierarchy` checks and changelist
  metadata/filtering.
- Extended changelist `select_related()` inference to display callables and
  methods that declare related-field ordering metadata.
- Hardened collected-object delete permission checks so `delete_selected`
  returns permission-needed details when object-level delete hooks deny a row.
- Aligned direct delete with collected-object permission reporting for
  object-level delete hook denials.
- Added admin system checks for malformed boolean options used by form and
  changelist metadata.
- Exported `ShowFacets` from the package root and added an admin system check
  for malformed `show_facets` values.
- Added an admin system check for malformed `search_help_text` values before
  changelist metadata serialization.
- Added an admin system check for malformed custom `paginator` classes before
  changelist pagination runs.
- Added explicit changelist coverage for `ShowFacets.NEVER` and
  `ShowFacets.ALWAYS` behavior.
- Aligned all-values list filters with Django-admin null-choice behavior by
  using `__isnull` query strings for `NULL` values.
- Tightened list-filter `__isnull` handling so malformed boolean values return
  typed lookup errors instead of being treated as false.

## 0.1.5 - 2026-07-01

- Improved related list-filter parity: many-to-many filters now expose and apply
  the empty relation choice, and related-only filters preserve related-admin
  ordering while limiting choices to used relations.
- Added an admin system check for first-column `list_editable` fields without an
  explicit `list_display_links` target, matching Django admin's configuration
  guard.
- Added admin system checks for non-integer `list_per_page` and
  `list_max_show_all` values.
- Added admin system checks for invalid `save_as`, `save_on_top`, and
  `view_on_site` option types.
- Extended `list_display` system checks to reject reverse relation fields in
  addition to many-to-many fields.
- Added an admin system check rejecting `ordering` configurations that combine
  random ordering (`"?"`) with other fields.
- Tightened field-based `list_filter` validation so tuple entries must be
  two-item `(field, FieldListFilter)` declarations.
- Allowed Django ORM expression ordering entries in admin system checks while
  still validating `F("field")` references when possible.
- Added inline admin system checks for invalid `extra`, `min_num`, and
  `max_num` option types.
- Added custom inline `formset` support with system checks requiring
  `BaseInlineFormSet` subclasses.
- Added an inline admin system check rejecting `exclude` entries that remove
  the parent foreign key field.
- Added admin system checks rejecting manual-through many-to-many fields in
  explicit `fields` and `fieldsets` form layouts.
- Added admin system checks for duplicate `list_display_links` and `exclude`
  entries.

## 0.1.4 - 2026-07-01

- Added per-model Pydantic response schemas for create/update and bulk
  list-editable updates so OpenAPI advertises `ProductAdminOut`-style response
  objects.

## 0.1.3 - 2026-07-01

- Narrowed supported versions to Python 3.12+ and Django 5.0+, including
  package metadata, CI, and planning docs.
- Reframed customization docs around Ninja-native hooks and made DRF
  `serializer_class` hooks explicitly unsupported.
- Rolled back partial site registry/action mutations when autodiscovered
  `admin.py` modules raise during import.
- Added admin system checks for invalid `fields`/`exclude` entries and unknown
  fields listed in `exclude`.
- Allowed Django-style row tuples in the `fields` option during admin checks,
  matching the form-generation flattening behavior.
- Added admin system checks for malformed `fieldsets`, duplicate fieldset
  fields, and `list_editable` fields omitted from custom fieldsets.
- Added admin system checks for duplicate fields in the `fields` option,
  including row-tuples.
- Added admin system checks rejecting reverse relations in `autocomplete_fields`
  and `raw_id_fields`.
- Added admin system checks for invalid `prepopulated_fields` shapes, targets,
  and source fields.
- Added admin system checks for invalid `sortable_by` shapes and entries outside
  `list_display`.
- Added admin system checks for invalid custom `form_class` values and
  mismatched `ModelForm` models.
- Added admin system checks for invalid `formfield_overrides` mappings.
- Added form-description support for callable entries in `readonly_fields`,
  including stable string names, labels, values, and display metadata.
- Used inline `get_extra()`, `get_min_num()`, and `get_max_num()` hooks when
  emitting form-description metadata.
- Added changelist support for callable entries in `list_display`, including
  stable response keys, display metadata, and `admin_order_field` sorting.
- Improved `schema_field_overrides` serialization so computed `ModelAdmin`
  methods are included in output responses.
- Added admin system checks for action `allowed_permissions` entries, including
  support for custom `has_<permission>_permission()` hooks.
- Skipped direct change-log entries when a successful update has no parent or
  inline changes, matching Django admin's no-op change behavior.
- Added changelist row URL and object-permission metadata for detail, change
  form, delete, and view-on-site frontend actions.
- Validated action `selected_ids` through the model primary key before queryset
  dispatch, returning typed errors for malformed object IDs.
- Added image-specific response schema and form metadata for Django
  `ImageField` values, including upload hints and width/height field names.
- Added mounted-route coverage and docs for `NinjaAdminSite` auth sequences,
  including OpenAPI security metadata for multiple Ninja auth callables.
- Added route-level auth-sequence override coverage for custom admin routes,
  preserving per-route OpenAPI security metadata.
- Added readonly form-field display values and metadata for admin methods and
  model properties, including boolean flags and empty-value fallbacks.
- Added explicit registry coverage for swapped models, which are skipped during
  registration to match Django admin behavior.
- Added admin system checks rejecting `filter_horizontal`/`filter_vertical` on
  many-to-many fields with custom through models.

## 0.1.2 - 2026-07-01

- Aligned date list-filter ranges with Django admin by adding upper bounds for
  date-time choices and clearing stale date filter params when switching ranges.
- Invalidated the lazy Ninja API/OpenAPI cache when global admin actions are
  added or disabled after initial API construction.
- Exposed changelist action placement and selection-counter metadata in the
  typed response config for frontend parity with Django admin action controls.
- Added admin system checks for invalid `list_select_related` types and
  relation paths.
- Added `show_full_result_count` and `show_admin_actions` changelist metadata,
  with `full_count` omitted when full counts are disabled.
- Normalized invalid changelist lookup values into typed 400 responses instead
  of leaking Django ORM conversion errors.
- Added Django-admin-style `NULL` choice handling for choices list filters via
  `__isnull` query strings.
- Matched Django admin related-filter visibility by hiding related filters that
  have only one non-empty choice while still applying their query params, and
  exposing the real related lookup key.
- Rejected invalid `EmptyFieldListFilter` values with typed changelist lookup
  errors instead of treating arbitrary strings as false.
- Hid `SimpleListFilter` instances with no lookup choices, matching Django
  admin's filter output threshold.
- Improved inline mutations so server-side add/change/delete validation returns
  row-indexed errors across the payload before any parent or inline writes occur.
- Added multipart create/update routes for file-field forms, validating the
  JSON `data`/`inlines` parts with generated Pydantic schemas before passing
  uploads to Django `ModelForm` file handling.
- Hardened view-on-site URL resolution so relative model URLs fall back to the
  request host when the configured `Site` row is missing.
- Added Django-admin-style formfield customization hooks for generated forms,
  including `formfield_overrides`, `formfield_for_dbfield()`,
  `formfield_for_foreignkey()`, `formfield_for_manytomany()`, and
  `formfield_for_choice_field()`.
- Added an admin system check that rejects `list_editable` fields omitted from
  the generated admin form by `fields`, `fieldsets`, or `exclude`.
- Expanded date hierarchy metadata with clear/back navigation query strings and
  validation for impossible year/month/day combinations.
- Aligned changelist search `__exact` handling for non-text fields with
  Django admin by casting field values to text instead of coercing search terms.
- Added multi-column ordering state metadata and sort links that preserve other
  active sort columns.
- Corrected the package repository URL to the canonical GitHub remote.

## 0.1.1 - 2026-07-01

- Added Pydantic-backed custom action input/response schemas through
  `@action(input_schema=..., response_schema=...)`.
- Added discriminated per-action request payload variants for action OpenAPI
  schemas.
- Hardened inline mutations so configured-but-forbidden inline operations
  return permission errors instead of unknown-inline validation errors.
- Hardened inline mutations so unknown or readonly inline row fields return
  validation errors instead of being silently ignored.
- Improved bulk list-editable updates so unchanged rows are validated and
  returned without invoking save hooks or writing empty change-log entries.
- Tightened `_to_field` validation to follow Django-admin relation-target
  semantics instead of allowing arbitrary fields from related models.
- Hardened history listing with permission-aware querysets, app/model/action
  filters, and typed errors for invalid history parameters.
- Hardened autocomplete pagination and added coverage for many-to-many source
  fields using the same endpoint contract.
- Added mounted-route coverage for callable `view_on_site` hooks returning
  absolute and protocol-relative external URLs.
- Added custom admin route coverage for named Ninja response schemas alongside
  route-level auth overrides.
- Added an admin check that rejects direct many-to-many fields in
  `list_display`, matching Django-admin semantics.
- Added explicit registry contract tests for option-based registration,
  duplicate/unregistered errors, abstract-model rejection, and `@register`.
- Added property-aware changelist display metadata so model properties can
  carry labels, boolean flags, and empty-value text from their getter.
- Improved inline deletion change messages so logs preserve the deleted
  inline object's display text while keeping public mutation responses stable.
- Improved changelist search so many-to-many search paths are treated as
  duplicate-prone and automatically return distinct rows.
- Improved bulk list-editable updates so server-side validation collects
  row-indexed errors across the payload before any write occurs.
- Added support for passing pytest selectors through `just test` and
  `just postgres-test`.
- Added a `just` command surface for local lint, test, package smoke, and full
  check workflows.
- Added a package smoke script that builds the wheel, installs it into an
  isolated target, verifies public API imports, and checks dependency metadata
  for absent DRF/drf-spectacular dependencies.
- Added a sample-project smoke script that installs the wheel into a temporary
  Django project and exercises docs, OpenAPI, app discovery, and a model
  changelist.
- Added env-driven PostgreSQL test settings and a CI PostgreSQL lane.
- Added an initial copyright/license audit document for release hardening.
- Added a release checklist with alpha, beta, and stable readiness criteria.
