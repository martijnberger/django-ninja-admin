# Release Checklist

This package stays alpha until the parity matrix is complete or each remaining
gap is explicitly documented as a v2 contract difference.

## Local Gates

Run the full local gate before tagging any release candidate:

```bash
just check
```

`just check` runs:

- `just lint` for Ruff.
- `just test` for the pytest suite.
- `just package-smoke` to build a wheel, install it into a temporary target,
  import the public API, and confirm wheel metadata does not depend on DRF or
  drf-spectacular.
- `just sample-project-smoke` to install the built wheel into a temporary
  Django project, register a model, mount `site.urls`, open docs/OpenAPI, and
  exercise authenticated model discovery.
- CI also runs `just postgres-test` against PostgreSQL; local use requires
  `DJANGO_NINJA_ADMIN_TEST_DATABASE=postgres` and the `POSTGRES_*` connection
  environment variables.

## Alpha Criteria

- The package installs from a built wheel.
- `django_ninja_admin` imports without importing DRF or drf-spectacular.
- A clean Django project can add `django_ninja_admin` to `INSTALLED_APPS`,
  register a model, mount `site.urls`, and open Ninja docs.
- Known parity gaps are tracked in `docs/parity-matrix.md`.

## Beta Criteria

- Upstream fixture behavior has Ninja-native tests where the v2 contract keeps
  the same semantics.
- Changelist, filter, action, inline, delete, history, and form behavior cover
  common Django-admin edge cases.
- The Django and database compatibility matrix is exercised in CI.
- OpenAPI changes are guarded by semantic or snapshot tests.

## Stable Criteria

- All parity gaps are implemented or documented as intentional v2 differences.
- Release notes describe migration impact from the previous package version.
- Copyright notices for Django-derived and upstream-derived code have been
  reviewed and recorded in `docs/copyright-audit.md`.
- The version follows semantic versioning: patch for compatible bug fixes,
  minor for compatible feature additions, and major for contract-breaking API
  or wire-shape changes.
