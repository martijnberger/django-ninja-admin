# Release Checklist

This package stays alpha until Milestones 1-3 in `PLAN.md` are complete and
the generated OpenAPI contract has been reviewed from an installed wheel.
`docs/parity-matrix.md` is an advisory admin-behavior checklist, not the
release bar; use it to find stale evidence and untested Django-admin edge
cases while keeping release readiness tied to the milestone criteria below.

## Local Gates

Run the full local gate before tagging any release candidate:

```bash
just check
```

`just check` runs:

- `just lint` for Ruff.
- `just format-check` for Ruff formatting.
- `just typecheck`, which treats every `ty` diagnostic as an error for the
  package and release tooling.
- `just coverage-test` for the pytest suite with the configured coverage floor.
- `just package-smoke` to build a wheel, install it into a temporary target,
  import the public API, and confirm wheel metadata does not depend on DRF or
  drf-spectacular.
- CI builds and checks the distribution once, uploads the checked wheel, and
  passes it to smoke jobs with `DJANGO_NINJA_ADMIN_WHEEL`; local smoke commands
  still build their own wheel unless that variable points at a wheel file or
  directory.
- `just sample-project-smoke` to install the built wheel into a temporary
  Django project, register a model, mount `site.urls`, open docs/OpenAPI, and
  exercise authenticated model discovery.
- `just private-api-audit` to keep private Django API usage matched to
  [`docs/private-django-api-audit.md`](private-django-api-audit.md).
- `just docs-check` to validate the MkDocs navigation and local documentation
  links.
- `just docs-build` to run a strict MkDocs build into a temporary output
  directory.
- `just openapi-snapshot-check` and `just generated-client-smoke` to preserve
  and exercise the reviewed OpenAPI contract from an installed wheel.
- Set `DJANGO_NINJA_ADMIN_SMOKE_DJANGO` to a concrete requirement such as
  `django>=5.2,<5.3` when the installed-project smoke should use the same
  Django lane as a compatibility matrix job.
- `just sample-project-full` is available as the broader installed-wheel sample
  project gate for release candidates. It exercises richer registered-admin
  workflows including autocomplete, list filters/search, list-editable bulk
  updates, inlines, actions, multipart file upload, history, custom routes, and
  view-on-site URLs.
- CI also runs `just postgres-test` against PostgreSQL; local use requires
  `DJANGO_NINJA_ADMIN_TEST_DATABASE=postgres` and the `POSTGRES_*` connection
  environment variables.

## Extended Verification

Use the broader verification pass before beta/stable release candidates and
after any change that affects generated schemas, mutation semantics, query
behavior, or permission boundaries.

- Run focused tests for the changed behavior and at least one OpenAPI/schema
  contract test when the wire shape changes.
- Validate generated Pydantic schemas directly for changed input/output
  contracts, including valid examples, invalid payloads, required fields,
  optional PATCH-style fields, and error locations.
- Verify read-schema changes against Django Ninja `ModelSchema` /
  `create_schema()` expectations where feasible: explicit safe field lists,
  registered custom field mappings, relation IDs, nullable values, constraints,
  and no accidental `__all__` exposure.
- Verify form-derived write schemas still hand off to Django `ModelForm` and
  formset validation for persistence rules, hook order, disabled fields,
  inline constraints, and rollback after late failures.
- Run `just postgres-test` for lookup, ordering, transaction, protected-delete,
  constraint, JSON-field, date/time, and facet/count behavior.
- Review CI results across the supported Django 5.0+ and Python 3.12+ matrix,
  including installed-wheel sample-project smoke pinned to each matrix Django
  requirement.
- Run `just openapi-diff <previous-openapi.json> <candidate-openapi.json>` when
  comparing release candidates or reviewed OpenAPI artifacts.
- Run `just generated-client-smoke` to prove a clean installed project can use
  OpenAPI operation IDs, request examples, and schema-declared path/query
  parameters, including typed changelist query-parameter schemas, for core
  model workflows including inline add/change, inline row URL metadata,
  filtered-select selected/unselected option metadata, full update, delete,
  CSRF bootstrap, session login, authenticated mutation, logout, site context,
  permissions, app-list, history, autocomplete, and view-on-site, and can parse
  documented success and error responses against the advertised response
  schemas.
- Run `just sample-project-full` to exercise the expanded installed-wheel
  sample project before beta/stable release candidates and after broad changes
  to forms, inlines, actions, filtering, file uploads, history, or custom
  routes.
- Compare generated OpenAPI semantically for route maps, component names,
  required fields, examples, auth/error responses, multipart request bodies,
  action payload variants, and inline/bulk schemas.
- Run `just parity-report` to summarize current matrix status, missing rows,
  partial rows, and any rows with placeholder evidence before changing release
  readiness claims.
- Inspect `docs/parity-matrix.md` for stale evidence and make sure every
  remaining gap is still accurate.
- Confirm each `implemented` parity row cites concrete evidence: focused test
  names, smoke gates, documented intentional v2 differences, or source-level
  non-applicability.
- Keep a short expected-change note for any OpenAPI diff that removes a field,
  renames a component, changes required fields, changes response status maps,
  or changes typed error bodies.
- Apply the API versioning and deprecation policy in
  [`docs/versioning.md`](versioning.md) before accepting any wire-contract
  change after Milestone 3.
- Re-run the copyright/license audit after substantial Django-derived or
  upstream-derived ports.
- Re-run `just private-api-audit` after every Django feature-version upgrade.

## Alpha Criteria

- The package installs from a built wheel.
- `django_ninja_admin` imports without importing DRF or drf-spectacular.
- A clean Django project can add `django_ninja_admin` to `INSTALLED_APPS`,
  register a model, mount `site.urls`, and open Ninja docs.
- Milestone 1 security and contract defects are either complete or explicitly
  blocking the next release.
- Known admin-behavior gaps are tracked in `docs/parity-matrix.md` as advisory
  follow-up evidence, not as release blockers by themselves.

## Beta Criteria

- Milestones 1-3 in `PLAN.md` are complete.
- Upstream fixture behavior has Ninja-native tests where the v2 contract keeps
  the same semantics.
- Changelist, filter, action, inline, delete, history, and form behavior cover
  common Django-admin edge cases.
- The Django 5.0+ and database compatibility matrix is exercised in CI.
- OpenAPI changes are guarded by semantic or snapshot tests and reviewed from
  an installed wheel.

## Stable Criteria

- Milestone 4 backlog items required for production support are complete or
  explicitly deferred with documented v2 rationale.
- Advisory parity-matrix gaps have been reviewed, with implemented rows backed
  by concrete evidence and remaining rows documented as backlog or intentional
  v2 differences.
- Release notes describe API contract impact from the previous package version.
- Copyright notices for Django-derived and upstream-derived code have been
  reviewed and recorded in `docs/copyright-audit.md`.
- The version follows the API versioning and deprecation policy in
  [`docs/versioning.md`](versioning.md).
