# Frontend Integration

A custom admin frontend should treat the OpenAPI document as the source of
truth for routes, request bodies, response bodies, and error shapes.

## Session Auth Flow

For the default `SessionAuthIsStaff` setup:

1. `GET /csrf` to receive a CSRF token and cookie.
2. `POST /login` with `{username, password}` to create a staff session.
3. Send `X-CSRFToken` on unsafe requests such as create, update, delete,
   actions, bulk updates, and logout.
4. `POST /logout` to clear the session.

The generated-client smoke test exercises this flow from an installed wheel.

## Discovery

Use these site routes to build navigation and permission-aware UI state:

- `GET /context`
- `GET /apps`
- `GET /apps/{app_label}`
- `GET /permissions`

Model routes expose changelist metadata, action metadata, form metadata,
pagination state, row permissions, and object permissions so the frontend does
not need to infer admin behavior from Django internals.

## Forms And Mutations

Create and update requests use a data envelope:

```json
{
  "data": {
    "name": "Tripod",
    "price": "9.00"
  }
}
```

Inline mutations live under `inlines` and are keyed by inline id:

```json
{
  "data": {"name": "Tripod"},
  "inlines": {
    "shop.productimage": {
      "add": [{"title": "Front"}],
      "change": [{"pk": 1, "title": "Profile"}],
      "delete": [2]
    }
  }
}
```

Use form-description responses to render field labels, choices, relation
metadata, initial values, readonly state, disabled state, and widget intent.
The API intentionally omits rendered Django widget internals such as generated
HTML ids, template names, and rendered attributes.

For relation widgets, prefer the semantic metadata over hard-coded endpoints.
Autocomplete metadata points at `/autocomplete` with the source-field identity;
raw-id and dual-select filtered metadata point at the related model changelist
with an `_to_field` query hint for looking up selectable objects.

## Pagination

Changelist, history, and autocomplete routes use one shared pagination shape.
Clients should use the advertised page metadata and generated query-parameter
types instead of hand-building query strings.

## Errors

Error responses use HTTP status codes plus the typed `ErrorResponse` body:

```json
{
  "errors": [
    {"message": "Permission denied.", "param": "non_field_errors"}
  ]
}
```

Generated clients should parse the documented error responses. The local
generated-client smoke validates representative 400, 401, 404, and 422 bodies
against the OpenAPI response schemas.
