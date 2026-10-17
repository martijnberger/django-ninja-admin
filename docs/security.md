# Security And Threat Model

The package exposes Django-admin authority to non-HTML clients. A compromised
credential or overly broad admin hook can therefore read or mutate everything
that principal can access in Django admin.

## Trust boundaries

| Input or component | Trust decision |
| --- | --- |
| Ninja session/auth backend | Authenticates the HTTP request; CSRF remains required for session writes. |
| MCP token verifier | Authenticates the bearer token; only verified subject/claims may map to a Django user. |
| MCP headers and tool arguments | Untrusted input, never identity or authorization evidence. |
| `HttpRequest.user` and trusted middleware state | Supplied by the integration and rechecked by the site/model/object hooks. |
| Pydantic models | Parse and constrain the wire shape, but do not authorize or replace Django form validation. |
| Django forms/formsets and admin hooks | Authoritative persistence validation and business behavior. |

## Invariants

- Site, model, object, relation, inline, action, and delete permissions are
  checked on every operation; filtered discovery is not an authorization
  boundary.
- Reads begin with `ModelAdmin.get_queryset()` and use explicit generated
  output schemas. Arbitrary client-supplied model lookups are rejected.
- Writes run through request-aware `ModelForm`/formsets inside transactions.
  Late inline, hook, or response validation failures roll back parent changes.
- Deletes collect cascades, protected objects, and required permissions before
  mutation. Writes use the normal admin audit log.
- Request bodies, credentials, bearer tokens, cookie/session IDs, CSRF values,
  and field contents are not included in MCP security logs. Logs contain tool
  name, outcome, status, exception class, and user identifier only.
- MCP model exposure is bounded and deterministic. Tool policy can reduce the
  surface, and each call still repeats core permission checks.
- HTTP deployments use bounded request bodies, TLS for remote access, explicit
  host/origin rules, authentication, proxy/server timeouts, and rate limits.

## Client responsibilities

Generated schemas describe capability, not intent. Clients should show the
target object(s), action, and deletion preview before destructive calls and
require confirmation appropriate to their risk model. A confirmation value is
not an authorization credential.

Operators must review custom `ModelAdmin` querysets, permission hooks, form
classes, serializers/output schemas, actions, response hooks, and custom Ninja
routes with the same care as Django's HTML admin. The adapter cannot repair an
admin hook that grants excessive authority or returns sensitive data.

Report suspected vulnerabilities privately to the maintainers rather than in
a public issue. Do not include production credentials or personal data in a
report or reproduction.
