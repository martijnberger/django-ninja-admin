# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning once it leaves alpha. While it remains
pre-release, minor versions may still adjust public API and wire contracts.

## Unreleased

### Changed

- Closed multipart mutation envelopes in OpenAPI and runtime validation so
  unknown top-level multipart form or file parts return the shared typed 422
  error body.

### Fixed

- Validated custom route HTTP methods at declaration time and treated
  `methods="post"` as a single `POST` route instead of iterating characters.
- Rejected duplicate multipart file parts for a single `FileField` with the
  shared typed 422 error body instead of silently selecting one uploaded file.

## 0.1.54 - 2026-07-04

### Changed

- Added a bounded `per_page` query parameter to `/autocomplete`, mirroring the
  shared pagination contract used by history while preserving the 20-result
  default.

### Fixed

- Validated delete response-hook bodies against their advertised schemas before
  the delete transaction commits, so invalid custom delete responses roll back
  the object deletion.

## 0.1.53 - 2026-07-04

### Changed

- Closed generated admin payload, action payload, output, bulk, and mutation
  response wrapper schemas with `additionalProperties: false` so Pydantic and
  OpenAPI reject undocumented top-level contract fields consistently.
- Validated add/change response-hook bodies against their advertised schemas
  before mutation transactions commit, so invalid custom hook responses roll
  back the database write.

## 0.1.52 - 2026-07-04

### Added

- Added mounted autocomplete coverage for dynamic `limit_choices_to` values,
  including callable and `Q` object relation constraints.

### Changed

- Added OpenAPI descriptions and numeric bounds for `/history` and
  `/autocomplete` query parameters; invalid page and history page-size values
  now use the shared typed 422 validation contract.
- Added OpenAPI pattern/minimum constraints for changelist `p`/`page`/`pp`
  query parameters, with invalid changelist page and page-size values using
  the shared typed 422 validation contract.
- Documented the generated-client contract for add/change/delete response
  hooks, including default statuses, custom schemas, status maps, and invalid
  return-value categories.

## 0.1.51 - 2026-07-04

### Fixed

- Aligned malformed `fieldsets` item system-check IDs with Django admin:
  non-list fieldset entries now report `E008`, while wrong-length entries
  continue to report `E009`.
- Aligned `raw_id_fields` system checks with Django admin by rejecting field
  attnames such as `category_id`; relation widget options must name the model
  field.

## 0.1.50 - 2026-07-04

### Changed

- Routed list-editable changelist metadata, bulk payload schemas/examples, and
  runtime bulk validation through `get_changelist_formset()` so custom
  formsets influence both OpenAPI and request handling.
- Closed public admin response schema components with `additionalProperties:
  false` so generated clients do not accept undocumented metadata fields.

### Added

- Added `ModelAdmin.get_changelist_formset()` and `changelist_formset` support
  for list-editable formset customization.
- Added mounted coverage for custom action object-permission enforcement when
  `select_across=True` uses the filtered changelist queryset.

### Fixed

- Aligned custom `response_change_schema` OpenAPI status maps with runtime
  update responses by advertising declared change-hook schemas on `200`/`202`
  and wrapping plain `response_change()` bodies in `Status(200, ...)`.
- Normalized plain custom `response_delete()` hook bodies to explicit `200`
  responses while preserving `None` as the default `204`.

## 0.1.49 - 2026-07-04

### Added

- Added related changelist `url` and `_to_field` query metadata to
  filtered-select form metadata for dual-select many-to-many controls.

### Changed

- Cached equivalent facet count queries within a changelist response so
  duplicate facet choices do not repeat count work.

### Fixed

- Distinct changelist search results for prefixed many-to-many search fields
  such as `^tags__name`, matching Django admin duplicate detection.

## 0.1.48 - 2026-07-04

### Added

- Added `selected_count` and `available_count` to filtered-select form metadata
  for dual-select many-to-many controls.
- Added mounted coverage for editing manual-through many-to-many relationships
  through explicit inline admins.
- Added mounted permission coverage for manual-through many-to-many inline
  add, change, and delete operations.

### Fixed

- Filtered parent form fieldset metadata to fields actually emitted in the form
  contract, avoiding stale auto-field and manual-through many-to-many entries.
- Added the missing state migration for `LogEntry` options and manager metadata
  so `makemigrations --check` stays clean.

## 0.1.47 - 2026-07-04

### Changed

- Aligned invalid `form_class` inheritance checks with Django admin's `E016`
  numbering and moved package-owned `form_class` model-mismatch plus
  `formfield_overrides` checks into package-specific IDs.
- Aligned invalid `view_on_site` checks with Django admin's `E025` numbering
  and moved package-owned paginator, action display, facet, search help, and
  empty-value display checks into package-specific IDs.
- Aligned mixed random ordering checks with Django admin's `E032` numbering
  and moved package-owned empty `list_display`, `list_select_related`, and
  non-sequence `actions` checks into package-specific IDs.
- Aligned inline model checks with Django admin's distinction between missing
  inline models (`E105`) and invalid non-model values (`E106`).
- Added history and autocomplete query-count guards for large result sets to
  verify page-bounded behavior.

## 0.1.46 - 2026-07-04

### Changed

- Aligned `list_display`, `list_display_links`, and `list_editable` item-level
  check IDs with Django admin's numbering while moving package-only duplicate
  and item-type checks into package-specific IDs.
- Aligned `list_filter` class and field-path check IDs with Django admin's
  numbering, moved package-only tuple-shape and missing-parameter checks into
  package-specific IDs, and allowed direct `ListFilter` subclasses at runtime.
- Added Django-aligned duplicate action-name system checks using
  `django_ninja_admin.E130`.
- Moved package-owned `sortable_by` system checks into package-specific IDs.
- Moved package-owned `schema_field_overrides` system checks into
  package-specific IDs.

## 0.1.45 - 2026-07-04

### Changed

- Aligned common `ModelAdmin` sequence-option check IDs with Django admin's
  numbering while keeping the `django_ninja_admin` check namespace.
- Aligned `save_as`, `save_on_top`, `list_per_page`, and
  `list_max_show_all` check IDs with Django admin's numbering, and moved
  package-specific prefetch/form-schema checks out of that native range.
- Aligned relation-widget, prepopulated-field, radio-field, date-hierarchy,
  and action-permission check IDs with Django admin's numbering while moving
  package-only lookup/conflict checks into package-specific IDs.
- Aligned core inline admin check IDs with Django admin's numbering and moved
  package-only inline layout/range/boolean checks into package-specific IDs.
- Aligned form-layout, fieldset, exclude, readonly-field, and manual-through
  many-to-many check IDs with Django admin's numbering while moving
  generated-form/list-editable checks into package-specific IDs.

## 0.1.44 - 2026-07-04

### Changed

- Extracted shared form-field and relation example generation helpers used by
  admin and site OpenAPI examples.
- Removed internal schema/example shim methods now covered by shared schema
  example helpers.
- Added a MkDocs documentation site scaffold with setup, auth/API, hook,
  frontend integration, and contract reference guides plus docs navigation and
  strict-build checks.
- Tightened autodiscovery rollback so missing admin modules are ignored, while
  unexpected import-time errors roll back partial registration and bubble.
- Added async-aware wrapping for custom site and model admin routes registered
  through `admin_view()`.

## 0.1.43 - 2026-07-04

### Changed

- Extracted shared form-data example selection, relation-target lookup, and
  JSON request-example wrapping so admin and site OpenAPI examples use tested
  helpers.
- Extracted schema override normalization, cache-key, and metadata helpers for
  form/output schema generation.
- Removed local choice-example shim methods now covered by shared schema
  example helpers.
- Removed unused internal exception classes left over from earlier admin
  compatibility scaffolding.
- Removed site-local Pydantic/JSON example shim methods now covered by shared
  schema example helpers.

## 0.1.42 - 2026-07-04

### Added

- Added Django Ninja throttle hooks for history, autocomplete, model
  changelist routes, and custom admin routes, with typed 429 error responses.
- Added a private Django API audit document and `just private-api-audit` gate to
  keep private API usage explicit during Django upgrades.

### Changed

- Routed core site, changelist, inline, and bulk API error messages through
  Django gettext while preserving the existing typed error response shapes.
- Routed default site labels through Django gettext while preserving custom
  project-provided labels unchanged.

## 0.1.41 - 2026-07-04

### Changed

- Typed changelist `pp`, `all`, and `_facets` query parameters as integer and
  boolean OpenAPI parameters, with documented 422 validation errors.
- Constrained generated inline mutation response schemas to registered inline
  identifiers instead of advertising arbitrary inline response keys.
- Closed the default action response schema so untyped action responses cannot
  advertise arbitrary extra fields.

## 0.1.40 - 2026-07-04

### Changed

- Advertised form input-schema override metadata with typed OpenAPI
  components, including recursive JSON-schema values.
- Replaced the default custom-route `dict[str, Any]` response with a named
  JSON-object response schema for site and model admin routes.
- Expanded the installed-wheel generated-client smoke to cover site context,
  permissions, app-list, history, autocomplete, and view-on-site routes.
- Expanded the installed-wheel generated-client smoke to verify CSRF bootstrap,
  session login, authenticated mutation, and logout with CSRF checks enabled.

## 0.1.39 - 2026-07-04

### Changed

- Added an `output_exclude` model-admin hook and applied it to default auth
  admins so sensitive user/group permission fields are omitted from read
  schemas and serialized responses.
- Expanded the installed-wheel generated-client smoke to validate core model
  workflow success responses against the OpenAPI response schemas.
- Expanded the installed-wheel generated-client smoke to cover inline add/change
  results, full-object update, and delete flows.
- Expanded the installed-wheel generated-client smoke to validate documented
  error responses against the OpenAPI response schemas.

## 0.1.38 - 2026-07-03

### Changed

- Typed action selected IDs, bulk row primary keys, and inline change/delete
  identifiers as reusable JSON scalar OpenAPI components.
- Removed arbitrary extra fields from the default mutation response data
  schema; custom response bodies should use declared hook response schemas.
- Typed default mutation inline response values as per-inline add/change/delete
  operation result schemas.
- Expanded the generated-client smoke check to validate declared path/query
  parameters before exercising changelist queries from an installed wheel.

## 0.1.37 - 2026-07-03

### Changed

- Typed validator detail, widget-attribute, subwidget, input-format, and
  select-date form metadata OpenAPI components.
- Typed combo-field child metadata and JSON-compatible scalar field metadata
  values in `FieldDescription.attrs`.
- Typed changelist row IDs, cells, and cell metadata values as JSON-compatible
  OpenAPI fields.
- Typed form and inline prepopulated-field maps plus form radio-field
  orientation maps.
- Typed list-editing row primary keys and history item identifiers/change
  messages as JSON-compatible OpenAPI fields.

## 0.1.36 - 2026-07-03

### Changed

- Reused a single prebuilt wheel artifact across CI smoke jobs via
  `DJANGO_NINJA_ADMIN_WHEEL`, while keeping local smoke commands able to build
  their own wheel.
- Folded the full installed-project smoke writer into `sample_project_smoke.py`
  behind `--full`.
- Expanded script type checking to cover release smoke scripts.
- Typed nested form metadata OpenAPI components for relation widgets,
  filtered selects, radio fields, and prepopulated-field sources.
- Typed form choice metadata OpenAPI components for two-item choice pairs,
  choice options, grouped choices, and JSON-compatible raw/coerced values.

## 0.1.35 - 2026-07-03

### Changed

- Extracted shared schema/example helpers into
  `django_ninja_admin.utils.schema_examples` for generated OpenAPI examples
  and choice-field schema/example handling.
- Extracted shared Pydantic constraint helpers into
  `django_ninja_admin.utils.schema_constraints`.
- Routed site pagination payload helpers through the shared `Pagination`
  schema used by changelist, history, and autocomplete responses.
- Removed unused generic payload/response schema classes in favor of the
  dynamic model-specific components advertised in OpenAPI.

## 0.1.34 - 2026-07-03

### Changed

- Narrowed safe metadata and schema exception handlers so deletion collection,
  related filters, form metadata, multivalue decompression, validator
  introspection, and Pydantic schema probes catch expected exception types
  instead of broad `Exception`.
- Continued the test-suite split by moving file/image clear, upload,
  multipart, validation, image-dimension, and storage-without-public-URL
  coverage into `tests/test_file_fields.py`.
- Continued the test-suite split by moving richer form-field Pydantic schema,
  parent/bulk/inline form schema override, and typed choice coercion coverage
  into `tests/test_form_field_schemas.py`.
- Continued the test-suite split by moving broad OpenAPI component, route
  response-map, operation-id, example, and generated contract coverage into
  `tests/test_openapi_contracts.py`.
- Completed the `tests/test_admin_api.py` split by moving the remaining
  runtime error, CRUD/history/change-log, and no-DRF package contract coverage
  into focused topic modules.

## 0.1.33 - 2026-07-03

### Changed

- Continued the test-suite split by moving isolated model-field output/write
  schema coverage into `tests/test_model_field_schemas.py`.
- Continued the test-suite split by moving schema override, custom output
  method, non-auth password field, and Ninja `register_field()` inference
  coverage into `tests/test_schema_customization.py`.
- Continued the test-suite split by moving model-route validation, delete,
  `_to_field`, action/bulk/autocomplete smoke, and view-on-site coverage into
  `tests/test_model_routes.py`.
- Continued the test-suite split by moving change-form description, readonly
  display metadata, layout/widget metadata, and relation `limit_choices_to`
  coverage into `tests/test_form_descriptions.py`.

## 0.1.32 - 2026-07-03

### Changed

- Continued the test-suite split by moving site registration, autodiscover
  rollback, OpenAPI cache invalidation, custom admin route, and context
  customization coverage into `tests/test_site.py`.
- Continued the test-suite split by moving core changelist list/detail,
  search, pagination, ordering, row metadata, action UI, and list-editable
  metadata coverage into `tests/test_changelist_core.py`.
- Continued the test-suite split by moving remaining changelist null-filter,
  direct lookup, search distinct/suffix, relation loading, prefetch, and
  changelist/paginator hook coverage out of `tests/test_admin_api.py`.
- Continued the test-suite split by moving mounted custom-form, response-hook,
  multivalue, temporal/scalar normalization, disabled-field, and formfield-hook
  coverage into `tests/test_custom_forms.py`.

## 0.1.31 - 2026-07-03

### Changed

- Continued the test-suite split by moving inline form-description, inline
  Pydantic payload, inline formset, permission, rollback, and change-message
  coverage into `tests/test_inlines.py`.
- Continued the test-suite split by moving changelist facets, date hierarchy,
  bounded date filters, lookup validation, and remote `to_field` related-list
  filter coverage into `tests/test_changelist_filters.py`.

## 0.1.30 - 2026-07-03

### Changed

- Continued the test-suite split by moving permission, auth-contract, safe
  `include_auth`, and session bootstrap coverage into
  `tests/test_permissions_auth.py`, with additional OpenAPI assertions that
  default auth-admin write schemas do not advertise sensitive user/group
  fields.
- Continued the test-suite split by moving history route filtering,
  pagination, object-permission, and page-scoped visibility coverage into
  `tests/test_history.py`.
- Continued the test-suite split by moving autocomplete route pagination,
  remote paginator/search hooks, `to_field`, `limit_choices_to`, source-access,
  and page-scoped object-permission coverage into `tests/test_autocomplete.py`.
- Continued the test-suite split by moving action dispatch, `delete_selected`,
  list-editable bulk update, `_to_field` row identity, and bulk hook coverage
  into `tests/test_actions_bulk.py`.

## 0.1.29 - 2026-07-03

### Changed

- Expanded the admin-check test split to cover inline formset validation,
  parent foreign-key exclusions, relation-path list-display checks, and action
  permission-hook validation.
- Expanded the admin-check test split to cover widget-option conflicts,
  related loading, sorting, pagination, boolean, ordering, facet, date
  hierarchy, expression ordering, and field-filter validation cases.
- Expanded the admin-check test split to cover custom form classes,
  formfield overrides, reverse relation widget fields, autocomplete target
  registration/searchability, and prepopulated-field validation.
- Completed the admin-check test extraction so all `test_admin_checks*` cases
  now live in `tests/test_checks.py`, including list-editable, form layout,
  manual-through many-to-many, and schema override validation.
- Started the OpenAPI test split with `tests/test_openapi_schema.py`, moving
  docs/auth and semantic error-schema coverage out of `tests/test_admin_api.py`
  and promoting shared API fixtures into `tests/conftest.py`.

## 0.1.28 - 2026-07-03

### Changed

- Expanded the package typecheck gate to cover changelist and list-filter
  modules, including the validated date-hierarchy field invariant.
- Expanded the package typecheck gate to cover admin system checks, with
  explicit narrowing for validated numeric admin options.
- Expanded the package typecheck gate to cover site/route registration logic,
  including typed app-list dictionaries, auth callables, Ninja query metadata,
  and Pydantic payload extraction.
- Expanded the package typecheck gate to cover inline and model admin modules,
  including dynamic Pydantic payload schemas and inline model metadata.
- Expanded the package typecheck gate to cover the base admin schema/form
  machinery, including subclass-provided admin attributes, dynamic Pydantic
  schemas, list-valued relation/choice types, and validator-derived bounds.
- Simplified the package typecheck gate to run `ty check django_ninja_admin`
  now that the full package passes.
- Started the test-suite split by extracting admin-check coverage into
  `tests/test_checks.py` with a shared `make_site` fixture.
- Expanded the admin-check test split to cover inline boolean, layout, and
  fieldset validation cases.

## 0.1.27 - 2026-07-03

- Bounded history and autocomplete object-level permission filtering to the
  current database page, avoiding full-queryset materialization when custom
  object permission hooks are present.
- Tightened typed error contracts with explicit `ErrorMessage` and recursive
  `DeletedObject` OpenAPI components instead of unconstrained message and
  deleted-object item schemas.
- Expanded the package typecheck gate to cover action/decorator/app config and
  auth-admin/log-model modules, including dynamic admin metadata helpers and
  Django model descriptor casts.

## 0.1.26 - 2026-07-03

- Removed rendered Django `BoundField`/widget internals from
  `FieldDescription.attrs` and the `FieldAttributes` OpenAPI component,
  keeping semantic field metadata while dropping generated HTML names, IDs,
  ARIA/rendered attrs, widget template names, rendered option groups, rendered
  subwidgets, hidden-initial widgets, and clear-checkbox HTML identifiers.
- Added `response_add_schema`, `response_change_schema`, and
  `response_delete_schema` hooks for custom mutation/delete `Status(...)`
  responses, and stopped advertising generic 200/202 objects for default model
  mutation routes.
- Added a typed default `ActionResponse` for model actions and tightened action
  success response maps so 200/202 responses use the default action schema plus
  declared `@action(response_schema=...)` variants instead of arbitrary object
  payloads.

## 0.1.25 - 2026-07-03

- Added a typed `FieldAttributes` OpenAPI component for
  `FieldDescription.attrs`, preserving sparse runtime metadata while replacing
  the previous unconstrained object schema with explicit Pydantic-described
  form/admin attributes.
- Added a typed `SelectedOption` component for relation widget selected-option
  metadata and refreshed the OpenAPI snapshot to advertise file/image metadata,
  widget details, relation hints, choice metadata, numeric bounds, and
  prepopulation hints as named field-attribute properties.
- Removed raw Django `fieldsets` data from form and inline response contracts;
  consumers should use the normalized `fieldset_layout` schema.
- Tightened the `FieldDescription.attrs` OpenAPI example so it highlights
  stable semantic admin metadata instead of renderer/internal bound-field
  details.
- Documented changelist query parameters in generated OpenAPI, including
  pagination, search, ordering, filter, and `_to_field` controls.
- Typed changelist ordering indexes as integers in response schemas.
- Documented the alpha API versioning and deprecation policy.

## 0.1.24 - 2026-07-02

- Honored Ninja `register_field()` model-field mappings in admin-owned schema
  inference paths such as custom primary keys, relation output IDs, and
  form-derived relation input schemas.
- Tightened generated output schemas for decimal model fields so response
  components preserve `max_digits` and `decimal_places` precision constraints.
- Tightened relation-target schemas so string target constraints such as
  `max_length` are preserved for foreign-key write payloads and many-to-many
  output/write item schemas.
- Tightened generated output schemas for bounded numeric model fields, including
  nullable positive integer fields, so response components preserve min/max
  validator constraints.
- Collapsed multiple numeric model-field validators to the strictest generated
  output-schema bounds, including foreign-key and many-to-many relation target
  schemas.
- Tightened generated output schemas for email and URL model fields so response
  components preserve `format: email` and `format: uri` metadata.
- Tightened generated output and relation-target schemas for
  `GenericIPAddressField` so response and relation input components use native
  Pydantic IP address validation metadata.
- Tightened JSON field request and response schemas so generated components
  advertise explicit JSON-compatible values instead of unconstrained payloads.
- Tightened generated output schema examples for many-to-many target fields and
  Ninja-registered custom model fields so examples validate against their
  generated component schemas.
- Expanded generated output schema examples for common explicit
  `schema_field_overrides` types such as UUID, temporal, URL, IP address, and
  constrained annotated/container Pydantic types.
- Serialized binary model fields as deterministic base64 strings in JSON output
  and advertised their `contentEncoding`/`contentMediaType` metadata in
  generated response schemas.
- Propagated model-field regex validators, including `SlugField` patterns, into
  generated output schemas and relation target schemas.
- Propagated model-field string length validators into generated output schemas
  and relation target schemas, including stricter `MaxLengthValidator` limits
  and explicit `MinLengthValidator` limits.
- Propagated zero-offset model `StepValueValidator` constraints into generated
  output schemas and relation target schemas as OpenAPI `multipleOf` metadata.
- Propagated explicit form-field string length validators into generated
  Pydantic request schemas, including stricter `MaxLengthValidator` limits and
  `MinLengthValidator` limits on custom `CharField` and `ComboField` inputs.
- Propagated explicit form-field numeric validators into generated Pydantic
  request schemas, including custom integer, float, and decimal fields, and
  fixed custom `FloatField` inputs to advertise OpenAPI `number` schemas.
- Reflected explicit form-field string and numeric validator bounds in form
  description metadata, including custom `CharField`, `ComboField`, integer,
  float, and decimal inputs.
- Generated request schema examples now honor `form_schema_field_overrides` for
  parent, bulk, inline, and route-level payload examples, and validate against
  their generated Pydantic schemas.
- Added `just parity-report` to summarize parity-matrix statuses, remaining
  partial/missing rows, and placeholder evidence gaps during release
  verification.
- Added `just openapi-diff` for semantic OpenAPI contract comparisons across
  reviewed artifacts or release candidates.
- Expanded `GET /permissions` with registered-model permission summaries and
  covered custom/object-level permission metadata hooks.
- Added `just generated-client-smoke` to exercise a clean installed project
  through OpenAPI operation IDs and advertised request examples.
- Added `@display(ordering=...)` ordering hints to readonly form-field
  metadata and the `FieldDescription.attrs` OpenAPI example.
- Added mounted autocomplete coverage for source-field `limit_choices_to`
  constraints, including form metadata, OpenAPI relation schemas, selected
  options, detail serialization, and filtered autocomplete results.
- Added `just sample-project-full`, an installed-wheel sample project gate that
  exercises richer registered-admin workflows including autocomplete,
  filter/search changelists, list-editable bulk updates, inlines, actions,
  multipart file upload, history, custom routes, and view-on-site URLs.
- Added semantic OpenAPI snapshot coverage for `ErrorItem` and `ErrorResponse`
  plus representative runtime validation for auth, permission, not-found,
  request-validation, and protected-delete error bodies.
- Added mounted `delete_selected` coverage for `select_across` over filtered
  changelists with object-level delete permission denial, preserving
  all-or-nothing action behavior.
- Fixed related and related-only list filters to emit remote `to_field` values
  in filter choices and query strings, including `ForeignKey(to_field=...)`
  relations.
- Expanded CI release-hardening coverage to include Python 3.13 and 3.14 lanes,
  non-experimental Django 6.0 checks, and matrix-pinned installed-project
  sample smoke via `DJANGO_NINJA_ADMIN_SMOKE_DJANGO`.
- Added JSON-safe `deleted_objects` tree details to protected-delete and
  permission-needed delete error bodies for direct deletes and
  `delete_selected`.
- Tightened plain Django choice-field request schemas for non-JSON scalar
  choices such as `Decimal` and `UUID` values by advertising the stringified
  Django form values as OpenAPI enums.
- Added typed choice-field metadata for coerced choice values and coerce
  callable names so form descriptions align with generated Pydantic schemas.
- Expanded the implementation plan's testing, validation, and verification
  section with concrete parity evidence rules, schema/OpenAPI contract gates,
  database/version matrix expectations, performance checks, and release
  verification criteria.

## 0.1.23 - 2026-07-02

- Tightened generated output schemas for many-to-many fields so response
  components advertise arrays of related target-field values instead of
  unconstrained arrays.
- Tightened generated relation write schemas and OpenAPI examples to use the
  related primary key or explicit `to_field_name` type instead of a blanket
  integer-or-string union.
- Tightened generated relation output schemas so serialized foreign-key
  `attname` fields use the related target-field type, including non-PK
  `ForeignKey(to_field=...)` relations.
- Added related target-field class, internal type, and attname metadata to
  relation form descriptions and relation widget hints.
- Added related target-field metadata to filter-horizontal/filter-vertical
  dual-select form widget hints.
- Tightened generated output schemas for model choice fields so response
  components advertise concrete enum values where possible.
- Tightened generated output schemas for model primary keys so persisted admin
  responses advertise non-null typed IDs.
- Tightened generated output schemas for blank-but-non-null model fields so
  response components do not advertise nullable values for persisted strings.

## 0.1.22 - 2026-07-02

- Added typed `PermissionsResponse` OpenAPI output and concrete success
  examples for built-in site-route response schemas.
- Added generated OpenAPI component examples for per-model output, mutation
  payload/response, bulk update, and inline operation schemas.
- Added per-row changelist cell metadata for display values, empty-state
  handling, links, sortability, and list-editable hints.
- Added mount-aware endpoint and query metadata for autocomplete and raw-id
  relation widgets in form descriptions.

## 0.1.21 - 2026-07-02

- Added `ModelAdmin.list_prefetch_related` / `get_list_prefetch_related()` for
  changelist relation prefetching, including string and `Prefetch` object
  support, system checks, and query-count coverage for callable many-to-many
  display columns.
- Filtered autocomplete results through object-level remote
  `has_view_permission(request, obj)` checks before pagination.
- Filtered history rows for existing objects through object-level view/change
  permissions before pagination.

## 0.1.20 - 2026-07-02

- Exposed concrete rendered child input names, IDs, attrs, and values for
  compound widgets such as `SplitDateTimeWidget` and `SelectDateWidget`.
- Exposed Django-style rendered widget attrs combining static widget attrs with
  generated IDs, required/disabled flags, and ARIA help-text links.
- Exposed rendered grouped choice optgroup metadata, including group labels and
  per-option render attrs/selection state.
- Added normalized parent and inline fieldset layout metadata with section
  names, classes, descriptions, flattened fields, and row groupings.
- Added concrete OpenAPI examples for typed admin error response bodies,
  including validation, permission, and protected-delete shapes.
- Expanded filter-horizontal/filter-vertical metadata with stacking state,
  source verbose names, and related-model identity.
- Added a concrete OpenAPI example for `FieldDescription.attrs` showing
  bound-field, rendered-attr, and rendered-subwidget metadata.
- Advertised common custom action `Status` success responses in OpenAPI and
  covered `202` action returns.

## 0.1.19 - 2026-07-02

- Added inline formset prefix, management-form, empty-form, and per-row
  prefixed bound-field metadata to form descriptions.
- Added list-editable changelist formset prefix, management-form counts, and
  per-row prefixed bound-field metadata for bulk-edit renderers.
- Added semantic OpenAPI coverage for changelist and inline formset response
  metadata components.
- Exposed Django `BoundWidget` option metadata in form descriptions for
  radio, checkbox, and other subwidget renderers.
- Exposed Django `ClearableFileInput` clear-checkbox names, IDs, and labels
  in file and image form descriptions.
- Exposed Django `BoundField.aria_describedby` metadata for accessible
  help-text rendering.

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
