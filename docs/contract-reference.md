# Contract Reference

The generated OpenAPI document is the client contract. It is intentionally
Ninja-native and does not preserve DRF envelopes or serializer hooks.

## OpenAPI

Mounting `site.urls` exposes:

- `/docs`
- `/openapi.json`

Both routes use site auth unless the site is explicitly created with
`auth=None`. Operation ids, tags, component names, request examples, response
examples, and response status maps are kept deterministic and covered by local
contract tests.

## Request Shapes

Mutation requests use `{data: ...}` plus optional `inlines`. Bulk updates use
`{data: [...]}`. Actions use an action selection payload and, for typed custom
actions, a discriminated `data` payload variant selected by action name.

Unknown fields are rejected by Pydantic before Django `ModelForm` or formset
validation runs.

## Response Shapes

Standard mutation responses return typed `data` and optional typed `inlines`.
Default action responses return the typed `ActionResponse`. Custom hooks and
actions should declare schemas when they return custom bodies or status maps.

Custom site and model routes default to `JsonObjectResponse`, a named JSON
object schema. Declare a concrete Ninja/Pydantic schema for generated clients
that require field-level response typing.

## Error Shapes

Runtime errors use HTTP status codes and the shared `ErrorResponse` body.
Representative auth, permission, not-found, validation, form, inline, bulk-row,
and protected-delete errors are validated against the advertised schemas.

## Release Contract

Before beta, wire shapes may still change when needed to finish the v1
contract. After Milestone 3, follow the [API versioning policy](versioning.md)
for removed fields, renamed components, changed required fields, changed auth,
or changed error/status maps.
