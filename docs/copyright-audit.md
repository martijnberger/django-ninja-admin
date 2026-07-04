# Copyright And License Audit

Audit date: 2026-07-01.

## Current Status

- Project license: MIT, recorded in `LICENSE` and `pyproject.toml`.
- Django-derived admin behavior: attributed through `LICENSE-DJANGO`.
- Runtime dependency policy: Django, Django Ninja, and Pydantic only; DRF and
  drf-spectacular are intentionally absent from dependencies.
- Upstream `django-api-admin` parity target: tracked semantically in
  `docs/parity-matrix.md`; v2 does not preserve DRF imports or old wire shapes.
- Private Django API usage is inventoried and checked by
  `docs/private-django-api-audit.md` and `just private-api-audit`.

## Source Scan

The current source scan checked for copyright, Django BSD, MIT, DRF,
drf-spectacular, and upstream package references across tracked source and docs.
The matches are expected references in:

- `LICENSE` and `LICENSE-DJANGO`.
- `PLAN.md`, `README.md`, and docs.
- no-DRF test and package smoke metadata checks.
- Django template/settings strings in tests and smoke tooling.

No vendored DRF or drf-spectacular code is present.

## Release Checklist

Before each release candidate:

- Re-run the source scan after any substantial port from Django admin or
  upstream `django-api-admin`.
- Run `just private-api-audit` after Django upgrades and before release
  candidates.
- Confirm any newly ported Django-derived logic is covered by the BSD notice.
- Confirm package metadata still reports MIT and has no DRF/drf-spectacular
  dependency metadata.
- Keep this audit document and `docs/parity-matrix.md` in sync with any new
  source attribution.
