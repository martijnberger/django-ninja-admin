# MCP Integration

The optional MCP adapter projects the same admin operations and Pydantic
contracts through the official MCP Python SDK. It targets the stateless
`2026-07-28` protocol and Streamable HTTP transport.

```bash
python -m pip install 'django-veo-admin-api[mcp]'
```

## Create an adapter

Register models on a `CoreAdminSite`, then provide the authenticated Django
request boundary:

```python
from django.test import RequestFactory

from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core import CoreAdminSite
from django_veo_admin_api.integrations.mcp import MCPAdminServer, MCPToolPolicy

from shop.models import Product


class ProductAdmin(ModelAdmin):
    list_display = ("name", "price")
    search_fields = ("name",)


admin_site = CoreAdminSite(include_auth=False)
admin_site.register(Product, ProductAdmin)


def request_factory(info):
    request = RequestFactory().get("/mcp")
    request.user = resolve_verified_principal(info.access_token)
    request.LANGUAGE_CODE = preferred_language(request.user)
    return request


adapter = MCPAdminServer(
    admin_site,
    request_factory,
    policy=MCPToolPolicy(deny=("admin.*.*.delete",)),
)
app = adapter.streamable_http_app(host="127.0.0.1")
```

`request_factory` is the security boundary. `info.access_token` comes from the
SDK's configured token verifier. `info.headers` are untrusted client input and
must never be treated as an identity assertion. The factory must return a
Django `HttpRequest` with `user`; it may also restore trusted locale, tenant,
or other request state required by custom admin hooks.

The adapter snapshots the registry when it is constructed. Recreate it after
changing registrations. The default `max_registered_models=50` and 2 MiB
serialized-manifest caps fail before any partial tool set is exposed; raise
either only after reviewing the resulting manifest size. Tool names are also
checked against MCP's 64-character limit during construction.

## Remote bearer authorization

For a remote endpoint, pass an SDK `TokenVerifier` and `AuthSettings`:

```python
from mcp.server.auth.settings import AuthSettings

adapter = MCPAdminServer(
    admin_site,
    request_factory,
    token_verifier=ProjectTokenVerifier(),
    auth=AuthSettings(
        issuer_url="https://identity.example.com/",
        resource_server_url="https://admin.example.com/mcp",
        required_scopes=["admin:use"],
    ),
)
```

`ProjectTokenVerifier.verify_token()` must validate the bearer token and return
an SDK `AccessToken`. Map its verified `subject` or claims to an active Django
user in `request_factory`; do not reuse the raw token as a database lookup key
or log it.

The package does not expose Django cookie sessions as an MCP authentication
profile in this release. Streamable HTTP calls are independent requests, and a
cookie bridge must preserve Django authentication, CSRF, session expiry,
locale, and custom middleware state as one reviewed boundary. Trusted
first-party callers should use a scoped bearer principal or a deliberately
constructed in-process request. Never forward a session ID or CSRF value in a
tool argument or identity header.

## Hosting boundary

`streamable_http_app()` returns an ASGI application. Run it under an ASGI
server, normally as a separate process or listener behind the same reverse
proxy as Django. Django itself may still be deployed through ASGI or WSGI, but
the MCP Streamable HTTP app is ASGI-only; no WSGI or plain-Django HTTP fallback
is provided.

The adapter defaults to stateless HTTP, JSON responses, and a 4 MiB request
body limit. The SDK automatically enables localhost host/origin protection
when `host` is `127.0.0.1`, `localhost`, or `::1`. Remote deployments must pass
reviewed `TransportSecuritySettings`, terminate TLS, authenticate every call,
and configure trusted hosts/origins explicitly. Enforce timeouts and rate
limits at the ASGI server or reverse proxy; use the protocol's `Mcp-Method` and
`Mcp-Name` headers for routing and metering only, never authorization.

## Tool contract

Global tools are `admin.apps`, `admin.context`, `admin.permissions`, and
`admin.history`. A registered model may expose deterministic tools such as:

- `admin.shop.product.list`, `.detail`, `.form`, and `.autocomplete`;
- `.create`, `.update`, `.bulk_update`, and `.actions`;
- `.delete_preview` and `.delete`.

Discovery is filtered by site permission, model permission, and
`MCPToolPolicy`; every invocation repeats those checks and the core repeats
object/action/form permissions. Allow/deny patterns are case-sensitive shell
patterns. Tool output is validated against the generated output schema and
uses `{ "data": ..., "error": null }`. Expected failures set MCP `isError`,
return `{ "data": null, "error": ErrorResponse }` as structured content, and
include JSON text compatibility.

Mutation tools are conservatively marked destructive and non-idempotent.
Clients should request human confirmation before calling them. The adapter
does not treat a client-supplied confirmation boolean as authorization and
does not currently add a multi-round input-required confirmation flow. For
read-only deployments, deny mutation patterns at the adapter policy.

MCP tools accept JSON payloads. Multipart file upload remains a Ninja transport
feature; use the Ninja integration when a Django form requires uploaded files.

## Verification

```bash
just mcp-snapshot-check
just mcp-package-smoke
just mcp-conformance
```

The checked-in manifest captures exact tool names, annotations, and generated
input/output schemas. The conformance smoke pins the official suite release
associated with `2026-07-28` and exercises stateless protocol behavior, tool
discovery/name rules, and DNS-rebinding protection. The test fixture adds the
suite's capability diagnostic tool; production adapters do not.

See the [MCP tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools),
[transport requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports),
[authorization requirements](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization),
and [official Python SDK](https://github.com/modelcontextprotocol/python-sdk).
