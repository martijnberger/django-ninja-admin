# Architecture

The package has one Django-admin engine and optional protocol projections:

```text
                         Django HttpRequest context
                                   |
                     +-------------v-------------+
                     | CoreAdminSite + ModelAdmin|
                     | forms, permissions, audit |
                     | Pydantic contracts        |
                     | operation services        |
                     +-------------+-------------+
                                   |
                    +--------------+--------------+
                    |                             |
          +---------v---------+         +---------v---------+
          | Ninja integration |         | MCP integration   |
          | HTTP/auth/Status  |         | tools/auth/results|
          | OpenAPI/docs      |         | Streamable HTTP   |
          +-------------------+         +-------------------+
```

The core never imports either transport SDK. Optional SDK imports are confined
to `django_veo_admin_api.integrations.ninja` and
`django_veo_admin_api.integrations.mcp`; an AST boundary test and clean-wheel
profiles enforce this rule.

## One semantic path

For any operation, an integration authenticates a principal, constructs the
request context, parses the declared Pydantic input, calls exactly one core
service, and maps the result. The core owns permission sequencing, queryset
construction, object lookup, forms/formsets, transactions, protected-delete
collection, serialization, and `LogEntry` writes.

The MCP integration does not issue synthetic HTTP requests to the Ninja API.
The Ninja integration does not depend on MCP. Both use the same generated
Pydantic models, which are reviewed through the golden OpenAPI document and MCP
tool manifest.

## Dependency profiles

| Profile | Django | Pydantic | Django Ninja | MCP SDK |
| --- | --- | --- | --- | --- |
| base | yes | yes | no | no |
| `[ninja]` | yes | yes | yes | no |
| `[mcp]` | yes | yes | no | yes |
| `[all]` | yes | yes | yes | yes |

There is deliberately no plain-Django REST fallback. Reimplementing routing,
parsing, response dispatch, authentication, and OpenAPI would create a second,
weaker HTTP transport instead of preserving one operation boundary.
