# Historical Implementation Status Log

This file preserves the accreted "Current Parity Status" section that used to live in `PLAN.md`. It is an append-style development log, not a curated changelog; see `CHANGELOG.md` for per-release notes and `docs/parity-matrix.md` for the parity reference table. Extracted 2026-07-02.

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
- Installed-project smoke gates can now pin their Django requirement through
  `DJANGO_NINJA_ADMIN_SMOKE_DJANGO`, allowing CI matrix lanes to verify the
  built wheel against the same Django version as the source-tree tests.
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
- Direct delete and default `delete_selected` error bodies now include a
  JSON-safe `deleted_objects` tree derived from Django's `NestedObjects`
  collector so clients can render delete previews alongside protected/perms
  details.
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

