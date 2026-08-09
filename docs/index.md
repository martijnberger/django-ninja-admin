# Django Veo Admin API

`django-veo-admin-api` provides a typed Django admin engine and exposes it
through optional transport integrations. The Django Ninja adapter provides an
HTTP API for custom admin frontends. The shared core keeps Django's registry, model-admin hooks,
`ModelForm` validation, changelists, actions, inlines, history, autocomplete,
permission checks, protected deletes, and admin log entries, while publishing
the contract through Django Ninja and Pydantic v2.

This is a v2 package, not a DRF-compatible replacement for
`django-api-admin`. The public contract is the generated OpenAPI document and
the Pydantic schemas behind it.

## Start Here

- [Setup](setup.md) shows the smallest Django project integration.
- [API And Authentication](api-and-auth.md) covers auth, request shapes,
  response hooks, actions, and throttling.
- [Frontend Integration](frontend-integration.md) explains how a custom SPA can
  consume the API safely.
- [Hook Reference](hook-reference.md) summarizes the Django-admin-style hooks
  that shape behavior.
- [Contract Reference](contract-reference.md) explains the OpenAPI, schema, and
  versioning expectations for generated clients.

## Supported Runtime

- Python 3.12 and newer.
- Django 5.0 and newer, up to the package's declared dependency ceiling.
- Pydantic v2 in the base package.
- Django Ninja 1.6 when the `[ninja]` integration extra is installed.
