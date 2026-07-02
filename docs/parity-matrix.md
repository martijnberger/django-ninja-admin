# Django API Admin v1.3.0 Parity Matrix

This matrix tracks parity against `daemon-bixia/django-api-admin` 1.3.0 and Django-admin behavior while keeping the v2 Ninja/Pydantic API contract. It is intentionally semantic: JSON envelopes and DRF-specific extension points are not required to match.

Statuses:

- `implemented`: covered by current code and local tests.
- `partial`: a working foundation exists, but important upstream/Django-admin semantics remain.
- `missing`: no meaningful implementation yet.
- `changed`: intentionally different in v2.

## Package And Public API

| Area | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Distribution/import package | implemented | `pyproject.toml`, `django_ninja_admin` package | Release metadata hardening in Phase 7 |
| Public exports | implemented | `django_ninja_admin/__init__.py` exports site/admin/filter/decorator APIs and `ShowFacets` | Keep stable as new hooks land |
| No DRF/drf-spectacular runtime dependency | implemented | Dependencies in `pyproject.toml`, `test_no_drf_imports`, `scripts/package_smoke.py` | Keep smoke coverage in CI |
| DRF serializer hooks | changed | Intentionally unsupported; replaced by Ninja-native `form_class`, `output_schema`, and `schema_field_overrides` hooks in `docs/api-and-auth.md` | Expand examples as hooks grow |

## Site Routes

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| `GET /apps` and `GET /apps/{app_label}` | implemented | `NinjaAdminSite.get_app_list`, API tests, and typed auth-error OpenAPI maps | Upstream fixture comparisons |
| `GET /context` | implemented | `NinjaAdminSite.each_context`, API tests, custom metadata tests, and `has_permission()` override coverage | Upstream fixture comparisons |
| `GET /permissions` | implemented | Site route in `sites.py`, site-level `has_permission`, default/auth-none API tests, and typed auth-error OpenAPI maps | Upstream fixture comparisons |
| `GET /history` | partial | History route, log model, app/model/object/action filter, permission-filter tests, client-controlled page/page-size pagination, per-row model identity/object links, and Django-style change-message text | Broader upstream history fixture comparisons |
| `GET /autocomplete` | partial | Permission-hardened route plus rich pagination metadata, remote `get_paginator()` and `get_search_fields()` hook coverage, many-to-many source-field tests, and non-PK `ForeignKey(to_field=...)` option IDs | Additional remote-field and permission edge cases |
| `GET /view-on-site/{content_type_id}/{object_id}` | implemented | Route, permission, callable hook, external URL tests, configured Site-domain URLs, and request-host fallback when Site is missing | Upstream fixture comparisons |
| Docs/OpenAPI routes | partial | `/docs`, `/openapi.json`, semantic model-route contract tests, generated JSON mutation examples, auth-aware built-in/model route maps, and custom-route success/error response maps | Full docs examples and broader snapshots |

## Registry, Model Admins, And Checks

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Model registration/unregistration | implemented | `NinjaAdminSite.register`, `unregister`, duplicate/unregistered/abstract/swapped/decorator tests | Upstream fixture comparisons |
| Default site/autodiscover | implemented | Lazy `site`, `autodiscover()`, sample-project smoke, and partial-import rollback test | Upstream fixture comparisons |
| Permission hooks | partial | `BaseAdmin.has_*_permission`, API tests | More object-level and custom hook coverage |
| Admin system checks | partial | `django_ninja_admin/checks.py`, invalid-admin, empty/callable/relation-path/many-to-many/reverse relation `list_display`, action shape/permission-hook checks, `list_display_links` item-type checks, `list_editable` item-type, form-layout, first-column link, and duplicate-field conflicts, inline shape/count/range/formset/parent-FK checks, row-tuple `fields`, duplicate `fields`/`exclude`/`readonly_fields`/`list_display_links`, callable readonly field layout names, manual-through m2m form-layout checks, fieldset shape/duplicate checks, `fields`/`exclude` item checks, `prepopulated_fields`, `sortable_by`, ordering random-marker/expression checks, field-based `list_filter` tuple/class checks, `date_hierarchy` type/path/field checks, pagination type/range/paginator options, boolean/save/action/full-count/view-on-site/facet options, search help text, empty value display, custom `form_class`, `formfield_overrides`, `schema_field_overrides`, `list_select_related`, autocomplete target registration/searchability, widget-conflict, reverse relation widget, and manual-through m2m widget tests | Match Django check IDs/coverage more closely |
| `get_changelist()` hooks | implemented | `ModelAdmin.get_changelist*`, route hook test | More subclassing examples/docs |
| Custom site/model views | partial | `admin_view()`, `get_urls()`, direct and decorator-style `route()`, route tags/descriptions, hidden routes, raw method wrapping, `auth=None`, named response schemas, generated/explicit route operation IDs with multi-method uniqueness, typed error response maps, custom route tests, and site/route-level auth-sequence route tests | Deeper override-hook parity and upstream fixture comparisons |
| Display decorator metadata | partial | `@display` descriptions, ordering, boolean flags, empty values, callable `list_display`, model-property metadata in changelist tests, and callable readonly-field metadata | More readonly-field display variants |

## Changelist, Filtering, Search, And Ordering

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Shared changelist queryset for list/actions | implemented | `ChangeList`, filtered action test, and action UI metadata tests | More selected/action edge cases |
| Search fields | partial | `ModelAdmin.get_search_results`, active search metadata and clear links, many-to-many duplicate distinct tests, prefix lookup tests, and non-text `__exact` cast tests | Broader upstream fixture comparisons |
| Lookup validation | partial | `lookup_allowed`, changelist `_to_field` validation/row identity tests, direct repeated/comma-separated `__in` and `__isnull` lookup preparation, local lookup-suffix tests, `limit_choices_to` relation-lookup tests, invalid lookup-key tests, and invalid lookup-value typed error tests | Match remaining Django suspicious lookup edge cases |
| Pagination/show all | implemented | `ChangeList`, pagination/show-all/last-page tests, presence-style `all` parameter behavior, custom paginator hook coverage, row/result indexes, page-result/range metadata, structured page choices, first/previous/next/last and show-all query strings, admin-style page range metadata, and `show_full_result_count` tests | Large-result behavior |
| Ordering/sort links | partial | Sort metadata plus default-ordering, visible custom queryset ordering, and multi-column ordering state/link tests, deterministic primary-key fallback ordering, stale-page reset in generated links, pagination query strings, and preservation of unrelated lookup params such as `price__gte` | Deeper Django query-string semantics |
| `list_select_related` and direct FK optimization | partial | `auto_select_related_fields`, direct-FK, relation-path, and callable related-ordering query-count tests | More m2m/prefetch strategy and broader query-count coverage |
| List display links/display metadata | partial | Changelist column metadata, callable display columns, single-valued relation-path columns, plus row index, URL, and object-permission metadata tests | More readonly-field action variants and upstream fixture comparisons |
| List filters | partial | Package-owned filter classes, bounded date-range filter tests, choices/all-values null tests, strict invalid `__isnull` tests, empty-filter validation tests, related-filter/simple-filter visibility tests, many-to-many empty relation tests, related-only ordering tests, stale-page reset in generated choices, filter-state and clear-all metadata, and common filter tests | Semantic edge-case comparison against Django/upstream |
| Facets | partial | `_facets=1`, `ShowFacets.NEVER`/`ALLOW`/`ALWAYS` route tests, optionality metadata, and add/remove facet query strings | Query-count optimization and exact Django facet semantics |
| `date_hierarchy` | partial | Date hierarchy metadata/filter tests, relation-path date fields, field-type/timezone metadata, bounded range filtering including max-year bounds, active-timezone DateTime bucketing, clear/back navigation query strings, stale-page reset in generated links, lowest-useful initial level selection, selected day state, and invalid date validation | Additional date edge cases and deeper Django navigation parity |

## Forms, Fields, And Serialization

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Dynamic output schemas | partial | `BaseAdmin.get_output_schema`, schema override tests including computed `ModelAdmin` methods | Stable component names and richer custom fields |
| Pydantic request envelopes | partial | Per-model create/update/bulk, unknown parent-field rejection, explicit parent/inline/bulk `form_schema_field_overrides`, richer JSON/UUID/IP/email/URL/duration/date-time-input-format/split-datetime/generic-multivalue/file-path/combo-field/file-image/null-boolean/multiple-choice/typed-choice form-field types, enum-style concrete/grouped/typed/float/decimal/UUID choices, string/field-regex/validator-regex/numeric/decimal/step constraints including Django-style stripping, disabled parent/inline field optionality, per-inline operation, discriminated action payload variants, and custom action input schemas with OpenAPI tests | Broader edge-case schemas and snapshots |
| Django ModelForm validation | implemented | Create/update tests, including Pydantic-cleaned temporal, URL, IP address, and UUID values bound into custom Django form fields | More field/widget variants |
| Custom `form_class` and formfield hooks | partial | Mounted custom-form and custom-formfield route tests cover schema fields, custom widget attrs/media, inline form classes, inline formfield hooks/media, `formfield_overrides`, `form_schema_field_overrides` request schemas/form metadata, `formfield_for_dbfield`, relation/choice hooks, form validation, persistence, and system checks for `form_class`/`formfield_overrides`/input schema overrides | More field override edge cases |
| Form descriptions | partial | Widget, custom-widget, disabled-field, hidden-initial widgets, nullable booleans, widget templates/subwidgets, option-template/checked-state/add-id-index hints, `SelectDateWidget`, temporal input formats, microsecond-support flags, form media, validator names/details, error-message, `empty_value`, localization, explicit input schema overrides, initial values, structured relation/autocomplete, selected relation labels, relation `limit_choices_to`, string stripping, numeric, decimal/step, flat/grouped choice with typed raw values, file-path/combo-field, readonly display/callable including explicit layout names, model-field identity, file/image, m2m, and admin-widget metadata tests | Custom field metadata and advanced widget details |
| File/image fields | partial | FileField output schema/serialization, ImageField typed metadata, current-file form metadata including storage backends without URLs, file-extension upload metadata, typed string-or-null JSON write schemas, JSON clear tests for files/images, multipart create/update routes including required file-field payloads, Pydantic validation for multipart JSON parts, and mounted ImageField invalid/valid upload tests with dimension metadata | Deeper storage/widget edge cases |
| Many-to-many fields | partial | Pydantic write schema, selected-label form value metadata, output serialization, create/update tests | Through models, permissions, and richer dual-select widget semantics |
| Raw ID/radio/filter-horizontal/prepopulated | partial | Per-field `admin_widget`, structured raw-id lookup metadata, structured filtered-select metadata, structured radio metadata, structured prepopulated source metadata, and conflict-check tests | Full Django widget rendering semantics and more edge cases |

## Mutations, Inlines, Delete, And Logs

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Create/update/delete routes | partial | CRUD/history tests plus mounted save-form/save/delete/response hook, custom add/change/delete `Status` responses, mutation success response maps, and allowed/bad `_to_field` detail/update/delete tests | More response hook edge cases |
| Inline add/change/delete | partial | Formset implementation, typed inline schemas, custom inline form and formset support/checks, custom inline multivalue normalization, dynamic inline count validation plus extra-form metadata, row-indexed server errors, max/delete/duplicate/conflict/unknown-object/rollback/permission/unknown-key/unknown-field/readonly-field tests | Deeper upstream formset edge cases |
| Bulk list-editable update | partial | Strict row schema, duplicate-PK rejection, filtered-queryset row limiting, `_to_field` row identity support, dedicated changelist form hook coverage, structured list-editing row metadata, unchanged-row skip, empty change-log skip, row-indexed validation and permission errors, and all-rows-before-write tests | Remaining changelist formset semantics |
| Default delete action/actions | partial | `delete_selected`, permission-filtered action metadata, custom return, empty-selection, invalid selected IDs, select-across, action permission-hook checks, object-level custom-action permission checks, protected response tests, and object-level delete permission details | Additional permission edge coverage |
| Protected delete | partial | Direct and action delete return protected/perms details, including object-level delete hook denials | Exact Django protected-object presentation |
| Log entries/change messages | partial | Field-label, no-op direct update skip, Django-style human-readable history text, and inline add/change/delete tests, including deleted inline object text | Broader upstream message fixture comparisons |

## Errors, Auth, And OpenAPI

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Staff-session auth default | implemented | `SessionAuthIsStaff`, auth tests, auth docs | More project-level examples |
| Custom auth and `auth=None` | implemented | Auth contract tests, multi-auth mounted-route tests, auth-none site-route tests, and auth docs | More project-level examples |
| Typed error bodies | partial | Exception handlers, Ninja validation handler, runtime auth-error tests, and built-in/model/custom route OpenAPI error maps including conditional `401` responses | Full error schema snapshots |
| Stable operation IDs/tags | partial | Explicit and generated operation IDs plus semantic OpenAPI contract tests for core site/model routes and custom site/model routes, including multi-method uniqueness | Broader custom-route snapshot tests |
| Per-model request/response contracts | partial | Output, write payload, generated create/update/bulk/action request examples, mutation/bulk response, inline operation, multipart JSON part media hints plus required file parts, discriminated action payload/input/response, global action cache invalidation, and auth-aware response-map schemas in OpenAPI | Broader Phase 6 snapshots and examples |

## Release Hardening

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Ruff/pytest local gates | implemented | `just lint`, `just test`, `just check`, `.github/workflows/ci.yml` | Keep CI and local gates aligned |
| Package build/install smoke | implemented | `scripts/package_smoke.py`, `scripts/sample_project_smoke.py`, `just package-smoke`, `just sample-project-smoke` | Expand sample project scenarios as parity grows |
| Django version matrix | partial | `.github/workflows/ci.yml` covers Django 5.0, 5.1, 5.2, and experimental 6.0 on Python 3.12+ | Confirm CI results; keep the matrix focused on Django 5+ and Python 3.12+ |
| PostgreSQL coverage | partial | Env-driven `tests/settings.py`, `just postgres-test`, PostgreSQL CI job | Confirm CI results and broaden database-specific edge cases |
| Copyright/license audit | implemented | `LICENSE`, `LICENSE-DJANGO`, `docs/copyright-audit.md` | Re-run before each release candidate and after substantial ports |
| Changelog/release checklist | implemented | `CHANGELOG.md`, `docs/release-checklist.md` | Expand release notes before each tag |
