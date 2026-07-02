# Django Ninja Admin — Plan

## Goal

Build `django-ninja-admin`: a production-ready, reusable package that exposes
`django.contrib.admin` concepts (site registry, model admins, changelists,
filters, forms, actions, inlines, history, autocomplete, checks, log entries)
as a typed HTTP API built on `django-ninja` 1.6+ and Pydantic v2, for teams
building custom admin frontends.

The north star has two axes, in this order:

1. **Django-admin semantic parity where it matters**: permissions (including
   object-level hooks), `ModelForm`/formset validation authority, admin system
   checks, changelist query semantics, protected deletes, change logging.
2. **Client-first contract**: a typed, stable, deterministic OpenAPI document
   that generated clients can actually consume — every request and response
   surface modeled with Pydantic, stable operation IDs and component names,
   honest error schemas.

Feature/wire parity with `daemon-bixia/django-api-admin` 1.3.0 is **no longer
the release bar**. `docs/parity-matrix.md` remains as a reference checklist of
admin behaviors worth covering; `scripts/parity_report.py` is advisory, not a
gate.

## Non-Goals

- DRF compatibility. `serializer_class` hooks stay unsupported; the
  replacements are `form_class`, `output_schema`, `schema_field_overrides`,
  and `form_schema_field_overrides`.
- Drop-in wire compatibility with `django-api-admin` clients.
- Rendering HTML or shipping an admin UI.
- Exposing Django widget/rendering internals over the wire (see Contract
  Decisions).

## Architecture Decisions

1. **Validation layering (kept).** Pydantic parses, coerces, rejects obvious
   contract errors, and documents OpenAPI; Django `ModelForm`/formsets remain
   the authoritative persistence validators. Both layers report through one
   error contract (see Milestone 1).
2. **Vendoring policy (new).** Delegate to `django.contrib.admin` code
   wherever the logic is HTML-free (large parts of checks, lookup/`to_field`
   validation, deletion collection); keep a slim vendored layer only for
   JSON-emitting behavior (`changelist.py`, `filters.py` output shaping,
   `LogEntry`). Maintain an inventory of vendored modules and private Django
   API usage (`_get_foreign_key`, `media._css/_js`, `widget._parse_date_fmt`,
   `request.parse_file_upload`, `_get_FIELD_display`, `queryset.query.order_by`)
   and run an upgrade audit against each new Django feature release, since
   admin security fixes (`to_field`/lookup CVE class) must not silently drift.
3. **Semantic form metadata (new).** The form-description surface is a typed
   `FieldDescription` v1 contract: field type, constraints, choices, relation
   metadata, initial values, help text, readonly/disabled state, and widget
   *intent* (autocomplete, raw-id, radio, dual-select, date-split, file). It
   does not carry rendered Django internals (`BoundField` HTML names,
   generated IDs, ARIA attributes, widget template names, rendered attrs or
   optgroups). Breaking wire changes are acceptable while pre-beta.
4. **One pagination shape** shared by changelist, history, and autocomplete.
5. **Schema strategy (kept, condensed).** Ninja `ModelSchema` /
   `create_schema()` semantics are the baseline for read schemas with explicit
   safe field lists (never `__all__`, password-class fields excluded); write
   schemas are form-derived with `extra="forbid"`; `register_field()` is
   honored for custom model fields; component names, examples, and operation
   IDs stay deterministic.
6. **Typing is part of the product.** Full annotations on the public API, a
   `py.typed` marker, and a strict type checker in CI.
7. **Package settings** (if/when any exist beyond `NinjaAdminSite` kwargs) are
   validated with pydantic-settings, not read raw from `django.conf.settings`.
8. **The schema machinery is one module.** The form→Pydantic type compiler,
   constraint extraction, and example generation currently triplicated across
   `sites.py`, `admins/base.py`, and `utils/forms.py` are extracted into a
   single shared module.

## Milestone 1 — Securable (blocks any further release)

Security and contract defects; nothing else ships until these land.

- **Safe auth-model registration.** Auto-registered `User`/`Group` admins must
  not expose `password` (currently written verbatim/unhashed via the generic
  `ModelForm`) nor freely writable `is_superuser`/`user_permissions`. Ship a
  proper `UserAdmin` equivalent (hashed password handling or password
  excluded + dedicated flow), and make `include_auth` registration safe by
  construction. Also fix the output-side `field.name == "password"` string
  match, which silently drops unrelated fields named `password`.
- **Gate `/docs` and `/openapi.json` behind site auth** (`docs_decorator` or
  equivalent). The schema is a complete data-model map and must not be public.
- **Bound `/history`.** Filter and paginate at the DB level; no full queryset
  materialization, no per-row `get_object()` visibility queries, enforce a max
  page size. Per-object visibility filtering only when an object-level hook is
  actually overridden.
- **Bound `/autocomplete`.** Paginate the queryset directly; per-object
  permission filtering only when the hook is overridden; enforce result-size
  bounds.
- **Honest error contract.** `AdminValidationError` payloads (form, inline,
  bulk-row) must validate against the declared `ErrorResponse` schema —
  either normalize to the flat list shape or model the nested union honestly
  in OpenAPI. A client generated from our own schema must parse our own 400s.
- **Session bootstrap.** Ship login/logout/CSRF-token endpoints (or a
  documented, tested pattern) so a SPA can authenticate against the default
  session+CSRF auth without mounting `django.contrib.admin`.
- **Consistent object-level delete checks.** Pass the object to
  `has_delete_permission` on the direct delete route, matching update.

Acceptance: an anonymous user can reach nothing (including docs); a staff user
cannot escalate via the default auth admins; history/autocomplete cost is
O(page), verified by query-count tests; generated clients parse every
documented error body; a browser SPA can complete login → CSRF → mutation.

## Milestone 2 — Quality Floor

Tooling and structure debt; mostly mechanical, high leverage.

- **Type checking**: mypy strict (with django-stubs) or ty on
  `django_ninja_admin/`, CI job, `py.typed` marker, public API annotated.
- **Test suite split**: break `tests/test_admin_api.py` (9,300 lines) into
  topic modules (`test_checks`, `test_openapi_schema`, `test_changelist_filters`,
  `test_permissions_auth`, `test_inlines`, `test_actions_bulk`,
  `test_autocomplete`, …) with a shared `conftest.py` and a
  `make_site(model, **admin_attrs)` factory; adopt `parametrize` for the
  repeated one-field-mutation blocks; split multi-behavior mega-tests.
- **Golden OpenAPI contract**: replace the hand-written exact-fragment OpenAPI
  mega-asserts with a checked-in golden `openapi.json` diffed semantically by
  `scripts/openapi_diff.py` in CI. Upstream (pydantic/django-ninja) bumps then
  produce one reviewable diff instead of dozens of assertion failures.
- **Lint/format**: enable `B904`; add `SIM`, `C4`, `RUF`, `PT`, `DTZ` rule
  groups; run `ruff format --check`; add pre-commit; drop `-q` from pytest
  `addopts` (it makes `pytest -q` double-quiet).
- **Coverage**: pytest-cov with `fail_under = 90` (currently ~91%) and a CI
  job.
- **CI**: add build + `twine check` job; run `just generated-client-smoke` in
  CI; add `concurrency` cancellation; build the wheel once and share across
  matrix cells; fold `scripts/sample_project_full.py` into the smoke script
  behind a `--full` flag or delete it.
- **Dedup and dead code**: extract the shared schema machinery (Decision 8);
  remove superseded helpers, never-raised exceptions with registered
  handlers, and unused schema classes; replace broad `except Exception`
  blocks with specific exceptions.
- **Changelog hygiene**: stop cutting a version per work session; curate
  `CHANGELOG.md` into user-facing Added/Changed/Fixed sections from here on.

## Milestone 3 — Contract Freeze (v1 wire contract)

Everything a generated client touches becomes typed, then frozen.

- `FieldDescription` v1 per Decision 3: retire the `attrs: dict[str, Any]`
  bag and `fieldsets: list[Any]`; type the whole form-description and
  changelist-metadata surface.
- **Typed changelist parameters**: declare `q`, `o`, `p`, `pp`, `all`,
  `_facets`, `_to_field` as Ninja `Query` params; document the field-lookup
  filter convention (`field__in`, `field__isnull`, date-hierarchy params) in
  OpenAPI route descriptions.
- **One pagination schema** (Decision 4) across changelist/history/autocomplete.
- **Tighten response typing**: remove `dict[str, Any]` unions from mutation
  and action responses where possible; document the constraints
  `response_add`/`response_change` overrides must satisfy.
- **Naming and shape cleanups**: `Column.headerName` → snake_case,
  `ordering_index` as int, `HistoryItem.action_time` as `datetime`.
- **Versioning policy**: document API versioning/deprecation rules; the golden
  OpenAPI diff is reviewed for every release, and any removed field, renamed
  component, or changed status map is a release decision.

Acceptance: the OpenAPI document round-trips through a generated client for
list/detail/create/update/delete/action/inline/bulk flows with no hand-built
query strings and no untyped `object` schemas on documented surfaces.

## Milestone 4 — Feature Backlog (re-scoped)

Ordered by user value, drawing on `docs/parity-matrix.md` as a reference:

- Vendoring audit execution per Decision 2 (delegate HTML-free logic back to
  `django.contrib.admin`, shrink `checks.py`).
- i18n: translated labels, messages, and error text (`gettext` throughout).
- Throttling hooks (Ninja throttling) for autocomplete/search endpoints.
- Async view support where django-ninja makes it beneficial.
- Remaining Django-admin semantic gaps: deeper filter/date-hierarchy edge
  cases, check IDs aligned with Django's, richer extensibility hooks.
- A documentation site (mkdocs) before beta: setup, auth patterns, hook
  reference, frontend integration guide, contract reference.

## Verification (condensed)

The detailed testing doctrine that used to live here mostly graduated into
practice; what remains normative:

- **Default gate** (`just check`, also the PR gate): lint + format check,
  typecheck, tests with coverage floor, package smoke, sample-project smoke.
- **Contract gate**: golden OpenAPI semantic diff + generated-client smoke, in
  CI on every PR.
- **DB gate**: `just postgres-test` in CI (ORM-sensitive behavior: lookups,
  ordering, facets, transactions, JSON fields, date bucketing).
- **Test principles that stay**: behavior through mounted routes whenever
  auth/parsing/serialization/transactions are involved; direct
  `model_validate()`/`model_json_schema()` tests for generated schemas (one
  valid + one invalid payload per shape change); DB side-effect and rollback
  assertions for every mutation path; allowed *and* denied users for every
  permission-sensitive behavior; advertised examples must validate against
  their own schemas; query-count guards for changelist/history/autocomplete.
- **Release checklist**: `docs/release-checklist.md`, updated as milestones
  land. Beta requires Milestones 1–3 complete, the CI matrix green, and a
  reviewed golden-OpenAPI diff from an installed wheel.

## Status And History

- Curated per-release notes: `CHANGELOG.md`.
- Historical accreted status log (extracted from this file): `CHANGELOG_OLD.md`.
- Admin-behavior reference checklist: `docs/parity-matrix.md` (advisory).

## Assumptions

- This is a v2 package, not a drop-in replacement for existing DRF clients.
- Wire contracts may break while pre-beta; after Milestone 3 they may not
  break without a versioning decision.
- Django-derived logic keeps BSD attribution (`LICENSE-DJANGO`,
  `docs/copyright-audit.md`); upstream-inspired logic keeps MIT attribution.
