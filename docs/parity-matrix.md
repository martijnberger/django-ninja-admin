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
| No DRF/drf-spectacular runtime dependency | implemented | Dependencies in `pyproject.toml`, `test_no_drf_imports` | Add packaging smoke in Phase 7 |
| DRF serializer hooks | changed | Replaced by `form_class`, `output_schema`, `schema_field_overrides` | Add migration docs in Phase 6 |

## Site Routes

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| `GET /apps` and `GET /apps/{app_label}` | implemented | `NinjaAdminSite.get_app_list`, API tests | Upstream fixture comparisons |
| `GET /context` | implemented | `NinjaAdminSite.each_context`, API tests | Add site customization tests |
| `GET /permissions` | implemented | Site route in `sites.py` | Broader auth matrix |
| `GET /history` | partial | History route and log model tests | More filters, permission edge cases, upstream change message parity |
| `GET /autocomplete` | partial | Permission-hardened route and tests | More pagination/source-field/remote-field edge cases |
| `GET /view-on-site/{content_type_id}/{object_id}` | implemented | Route and permission tests | External URL and custom callable variants |
| Docs/OpenAPI routes | partial | `/docs` and `/openapi.json` smoke tests | Stable snapshots and richer per-model payload schemas |

## Registry, Model Admins, And Checks

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Model registration/unregistration | implemented | `NinjaAdminSite.register`, `unregister` | More duplicate/swapped/abstract tests |
| Default site/autodiscover | partial | Lazy `site`, `autodiscover()` | Project-level smoke test |
| Permission hooks | partial | `BaseAdmin.has_*_permission`, API tests | More object-level and custom hook coverage |
| Admin system checks | partial | `django_ninja_admin/checks.py`, invalid-admin tests | Match Django check IDs/coverage more closely |
| `get_changelist()` hooks | implemented | `ModelAdmin.get_changelist*`, route hook test | More subclassing examples/docs |
| Custom site/model views | partial | `admin_view()`, `get_urls()`, `route()`, custom route tests | More auth/tag/response-schema override coverage |
| Display decorator metadata | partial | `@display` descriptions, ordering, boolean flags, empty values in changelist tests | More model-method/property and readonly-field display variants |

## Changelist, Filtering, Search, And Ordering

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Shared changelist queryset for list/actions | implemented | `ChangeList`, filtered action test | More selected/action edge cases |
| Search fields | partial | `ModelAdmin.get_search_results`, tests | More lookup suffix and duplicate handling tests |
| Lookup validation | partial | `lookup_allowed`, invalid lookup tests | Match Django suspicious lookup behavior |
| Pagination/show all | implemented | `ChangeList`, pagination/show-all tests | Large-result behavior |
| Ordering/sort links | partial | Sort metadata and tests | Multi-column ordering UI parity |
| `list_select_related` and direct FK optimization | partial | `auto_select_related_fields`, tests | Query-count tests and m2m/prefetch strategy |
| List display links/display metadata | partial | Changelist column metadata | URL/action metadata for frontend rendering |
| List filters | partial | Package-owned filter classes and tests | Semantic edge-case comparison against Django/upstream |
| Facets | partial | `_facets=1`, `ShowFacets` support, tests | Query-count optimization and exact Django facet semantics |
| `date_hierarchy` | partial | Date hierarchy metadata/filter tests | Navigation state and timezone edge cases |

## Forms, Fields, And Serialization

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Dynamic output schemas | partial | `BaseAdmin.get_output_schema`, schema override test | Stable component names and richer custom fields |
| Pydantic request envelopes | partial | Per-model create/update/bulk, per-inline operation, and action-name schemas with OpenAPI tests | Custom action extra payload schemas |
| Django ModelForm validation | implemented | Create/update tests | More field/widget variants |
| Form descriptions | partial | Widget, validator, relation, numeric, decimal, choice, readonly, file, m2m, and admin-widget metadata tests | Image metadata and advanced widget details |
| File/image fields | partial | FileField output schema/serialization, current-file form metadata, and JSON clear tests | Multipart create/update upload handling and image-specific behavior |
| Many-to-many fields | partial | Pydantic write schema, form value metadata, output serialization, create/update tests | Through models, permissions, and richer dual-select widget semantics |
| Raw ID/radio/filter-horizontal/prepopulated | partial | Per-field `admin_widget`, radio orientation, prepopulated source, raw-id, filter-horizontal, and filter-vertical tests | Full Django widget rendering semantics and conflict checks |

## Mutations, Inlines, Delete, And Logs

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Create/update/delete routes | partial | CRUD/history tests | More save hook/response hook variants |
| Inline add/change/delete | partial | Formset implementation, typed inline schemas, max/delete/duplicate/conflict tests | Unknown objects, rollback, readonly, per-row errors |
| Bulk list-editable update | partial | Strict row schema, duplicate-PK rejection, all-rows-before-write tests | Full changelist formset semantics and richer per-row errors |
| Default delete action/actions | partial | `delete_selected`, custom return, empty-selection, select-across, and protected response tests | Additional permission edge coverage |
| Protected delete | partial | Direct and action delete return protected/perms details | Exact Django protected-object presentation |
| Log entries/change messages | partial | Field-label and inline add/change/delete tests | Exact Django-admin message format parity |

## Errors, Auth, And OpenAPI

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Staff-session auth default | implemented | `SessionAuthIsStaff`, auth tests | Docs examples |
| Custom auth and `auth=None` | implemented | Auth contract tests | Multi-auth test coverage |
| Typed error bodies | partial | Exception handlers, Ninja validation handler, API tests | Full error schema snapshots |
| Stable operation IDs/tags | partial | Explicit operation IDs in routes | Semantic OpenAPI snapshot tests |
| Per-model request/response contracts | partial | Output, write payload, inline operation, and action payload schemas in OpenAPI | Custom action schemas and Phase 6 snapshots |

## Release Hardening

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Ruff/pytest local gates | implemented | Current test/lint commands | Add CI workflow |
| Package build/install smoke | missing | No build smoke test | Phase 7 |
| Django version matrix | missing | Single local environment | Phase 7 |
| PostgreSQL coverage | missing | SQLite-only tests | Phase 7 |
| Copyright/license audit | partial | MIT and Django BSD license files | Audit any newly ported code |
| Changelog/release checklist | missing | No changelog | Phase 7 |
