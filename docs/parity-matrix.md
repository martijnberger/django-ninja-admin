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
| Public exports | implemented | `django_ninja_admin/__init__.py` exports site/admin/filter/decorator APIs | Keep stable as new hooks land |
| No DRF/drf-spectacular runtime dependency | implemented | Dependencies in `pyproject.toml`, `test_no_drf_imports`, `scripts/package_smoke.py` | Keep smoke coverage in CI |
| DRF serializer hooks | changed | Intentionally unsupported; replaced by Ninja-native `form_class`, `output_schema`, and `schema_field_overrides` hooks in `docs/api-and-auth.md` | Expand examples as hooks grow |

## Site Routes

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| `GET /apps` and `GET /apps/{app_label}` | implemented | `NinjaAdminSite.get_app_list`, API tests | Upstream fixture comparisons |
| `GET /context` | implemented | `NinjaAdminSite.each_context`, API tests | Add site customization tests |
| `GET /permissions` | implemented | Site route in `sites.py` | Broader auth matrix |
| `GET /history` | partial | History route, log model, app/model/object/action filter, and permission-filter tests | Upstream change message parity |
| `GET /autocomplete` | partial | Permission-hardened route plus pagination and many-to-many source-field tests | More remote-field edge cases |
| `GET /view-on-site/{content_type_id}/{object_id}` | implemented | Route, permission, callable hook, external URL tests, configured Site-domain URLs, and request-host fallback when Site is missing | Upstream fixture comparisons |
| Docs/OpenAPI routes | partial | `/docs`, `/openapi.json`, and semantic model-route contract tests | Full docs examples and broader snapshots |

## Registry, Model Admins, And Checks

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Model registration/unregistration | implemented | `NinjaAdminSite.register`, `unregister`, duplicate/unregistered/abstract/swapped/decorator tests | Upstream fixture comparisons |
| Default site/autodiscover | partial | Lazy `site`, `autodiscover()` | Project-level smoke test |
| Permission hooks | partial | `BaseAdmin.has_*_permission`, API tests | More object-level and custom hook coverage |
| Admin system checks | partial | `django_ninja_admin/checks.py`, invalid-admin, many-to-many `list_display`, `list_editable` form-layout conflict, `fields`/`exclude` item checks, `list_select_related`, widget-conflict, and manual-through m2m widget tests | Match Django check IDs/coverage more closely |
| `get_changelist()` hooks | implemented | `ModelAdmin.get_changelist*`, route hook test | More subclassing examples/docs |
| Custom site/model views | partial | `admin_view()`, `get_urls()`, `route()`, route tags/descriptions, hidden routes, raw method wrapping, `auth=None`, named response schemas, custom route tests, and site/route-level auth-sequence route tests | Deeper override-hook parity and upstream fixture comparisons |
| Display decorator metadata | partial | `@display` descriptions, ordering, boolean flags, empty values, and model-property metadata in changelist tests | More readonly-field display variants |

## Changelist, Filtering, Search, And Ordering

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Shared changelist queryset for list/actions | implemented | `ChangeList`, filtered action test, and action UI metadata tests | More selected/action edge cases |
| Search fields | partial | `ModelAdmin.get_search_results`, many-to-many duplicate distinct tests, prefix lookup tests, and non-text `__exact` cast tests | Broader upstream fixture comparisons |
| Lookup validation | partial | `lookup_allowed`, invalid lookup-key tests, and invalid lookup-value typed error tests | Match Django suspicious lookup behavior |
| Pagination/show all | implemented | `ChangeList`, pagination/show-all tests, and `show_full_result_count` tests | Large-result behavior |
| Ordering/sort links | partial | Sort metadata plus multi-column ordering state/link tests | Deeper Django query-string semantics |
| `list_select_related` and direct FK optimization | partial | `auto_select_related_fields`, tests | Query-count tests and m2m/prefetch strategy |
| List display links/display metadata | partial | Changelist column metadata plus row URL/object-permission metadata tests | More readonly-field action variants and upstream fixture comparisons |
| List filters | partial | Package-owned filter classes, bounded date-range filter tests, choices-null tests, empty-filter validation tests, related-filter/simple-filter visibility tests, and common filter tests | Semantic edge-case comparison against Django/upstream |
| Facets | partial | `_facets=1`, `ShowFacets` support, tests | Query-count optimization and exact Django facet semantics |
| `date_hierarchy` | partial | Date hierarchy metadata/filter tests, clear/back navigation query strings, selected day state, and invalid date validation | Timezone edge cases and deeper Django navigation parity |

## Forms, Fields, And Serialization

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Dynamic output schemas | partial | `BaseAdmin.get_output_schema`, schema override test | Stable component names and richer custom fields |
| Pydantic request envelopes | partial | Per-model create/update/bulk, per-inline operation, discriminated action payload variants, and custom action input schemas with OpenAPI tests | Broader edge-case schemas and snapshots |
| Django ModelForm validation | implemented | Create/update tests | More field/widget variants |
| Custom `form_class` and formfield hooks | partial | Mounted custom-form and custom-formfield route tests cover schema fields, custom widget attrs, `formfield_overrides`, `formfield_for_dbfield`, relation/choice hooks, form validation, and persistence | More media and field override edge cases |
| Form descriptions | partial | Widget, custom-widget, validator, relation, numeric, decimal, choice, readonly display, model-field, file/image, m2m, and admin-widget metadata tests | Custom field metadata and advanced widget details |
| File/image fields | partial | FileField output schema/serialization, ImageField typed metadata, current-file form metadata, JSON clear tests, multipart create/update routes, and Pydantic validation for multipart JSON parts | Real image upload validation and deeper storage/widget edge cases |
| Many-to-many fields | partial | Pydantic write schema, form value metadata, output serialization, create/update tests | Through models, permissions, and richer dual-select widget semantics |
| Raw ID/radio/filter-horizontal/prepopulated | partial | Per-field `admin_widget`, radio orientation, prepopulated source, raw-id, filter-horizontal/filter-vertical, and conflict-check tests | Full Django widget rendering semantics and more edge cases |

## Mutations, Inlines, Delete, And Logs

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Create/update/delete routes | partial | CRUD/history tests plus mounted save/delete/response hook and bad `_to_field` tests | More response hook edge cases |
| Inline add/change/delete | partial | Formset implementation, typed inline schemas, row-indexed server errors, max/delete/duplicate/conflict/unknown-object/rollback/permission/unknown-key/unknown-field/readonly-field tests | Deeper upstream formset edge cases |
| Bulk list-editable update | partial | Strict row schema, duplicate-PK rejection, unchanged-row skip, row-indexed server errors, and all-rows-before-write tests | Full changelist formset semantics |
| Default delete action/actions | partial | `delete_selected`, custom return, empty-selection, select-across, and protected response tests | Additional permission edge coverage |
| Protected delete | partial | Direct and action delete return protected/perms details | Exact Django protected-object presentation |
| Log entries/change messages | partial | Field-label and inline add/change/delete tests, including deleted inline object text | Exact Django-admin message format parity |

## Errors, Auth, And OpenAPI

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Staff-session auth default | implemented | `SessionAuthIsStaff`, auth tests, auth docs | More project-level examples |
| Custom auth and `auth=None` | implemented | Auth contract tests, multi-auth mounted-route tests, and auth docs | More project-level examples |
| Typed error bodies | partial | Exception handlers, Ninja validation handler, API tests, and model-route OpenAPI error maps | Full error schema snapshots |
| Stable operation IDs/tags | partial | Explicit operation IDs and semantic OpenAPI contract tests | Broader site/custom-route snapshot tests |
| Per-model request/response contracts | partial | Output, write payload, inline operation, discriminated action payload/input/response, global action cache invalidation, and response-map schemas in OpenAPI | Broader Phase 6 snapshots and examples |

## Release Hardening

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Ruff/pytest local gates | implemented | `just lint`, `just test`, `just check`, `.github/workflows/ci.yml` | Keep CI and local gates aligned |
| Package build/install smoke | implemented | `scripts/package_smoke.py`, `scripts/sample_project_smoke.py`, `just package-smoke`, `just sample-project-smoke` | Expand sample project scenarios as parity grows |
| Django version matrix | partial | `.github/workflows/ci.yml` covers Django 5.0, 5.1, 5.2, and experimental 6.0 on Python 3.12+ | Confirm CI results and expand Python versions when supported |
| PostgreSQL coverage | partial | Env-driven `tests/settings.py`, `just postgres-test`, PostgreSQL CI job | Confirm CI results and broaden database-specific edge cases |
| Copyright/license audit | implemented | `LICENSE`, `LICENSE-DJANGO`, `docs/copyright-audit.md` | Re-run before each release candidate and after substantial ports |
| Changelog/release checklist | implemented | `CHANGELOG.md`, `docs/release-checklist.md` | Expand release notes before each tag |
