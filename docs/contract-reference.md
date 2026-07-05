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
validation runs. Generated admin payload wrappers, action payload variants,
model output components, and mutation/bulk response wrappers are closed with
`additionalProperties: false` in OpenAPI.

Model routes document every declared query parameter in OpenAPI, including
`_to_field` on changelist, detail, form, update, multipart update, and delete
routes. `_to_field` only accepts fields allowed by the registered
`ModelAdmin.to_field_allowed()` implementation.

## Response Shapes

Standard mutation responses return typed `data` and optional typed `inlines`.
Default action responses return the typed `ActionResponse`. Custom hooks and
actions should declare schemas when they return custom bodies or status maps.
Declared custom action and response-hook object schemas must be closed with
`additionalProperties: false` or shaped as typed maps; the admin system checks
reject open object contracts so generated clients do not silently accept extra
fields.
Add/change/delete response hook bodies are validated against the advertised
response schema before the surrounding mutation transaction commits.
The concrete response-hook rules are documented in the
[hook reference](hook-reference.md#save-delete-and-response-hooks).

Custom site and model routes default to `JsonObjectResponse`, a named JSON
object schema. Declare a concrete Ninja/Pydantic schema for generated clients
that require field-level response typing.

Form-description responses expose typed semantic widget metadata, including
relation lookup hints for autocomplete, raw-id, and dual-select filtered
controls. These hints describe source fields, related models, target fields,
and mount-aware endpoint/query data without exposing rendered Django widget
internals.

Changelist responses expose typed row/cell metadata and typed action controls.
Cells marked as display links include a `link_url` pointing at the same
permission-filtered detail route advertised by the row metadata.
The `action_form` response keeps Django-admin field semantics, but its OpenAPI
items are narrowed to the supported action, selected-id, and select-across
controls so generated clients do not need to treat them as arbitrary form
fields.

Inline and list-editable formset management metadata uses the same response
shape as Django form descriptions, but the OpenAPI items are narrowed to the
four supported hidden integer controls: `TOTAL_FORMS`, `INITIAL_FORMS`,
`MIN_NUM_FORMS`, and `MAX_NUM_FORMS`.

Changelist, history, and autocomplete responses share the `Pagination`
component. History and autocomplete page-size parameters are bounded in
OpenAPI; changelist keeps Django-admin-style `pp` and `all` controls.

## Error Shapes

Runtime errors use HTTP status codes and the shared `ErrorResponse` body.
Representative auth, permission, not-found, validation, form, inline, bulk-row,
and protected-delete errors are validated against the advertised schemas.

## Release Contract

Before beta, wire shapes may still change when needed to finish the v1
contract. After Milestone 3, follow the [API versioning policy](versioning.md)
for removed fields, renamed components, changed required fields, changed auth,
or changed error/status maps.
