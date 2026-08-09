# Django Veo Admin API — Plan

## Direction

Commit to a transport split: `django-veo-admin-api` becomes a Django-admin engine
with optional transport integrations.

The package keeps one source of truth for Django admin semantics and one set of
Pydantic contracts. Django Ninja and MCP translate their protocols to that
shared core; neither integration reimplements permissions, validation,
serialization, mutations, or audit behavior.

The north star remains, in this order:

1. **Django-admin semantic parity where it matters**: registry and admin hooks,
   object permissions, `ModelForm`/formset validation authority, changelist
   semantics, protected deletes, transactions, and `LogEntry` behavior.
2. **Client-first contracts**: closed Pydantic v2 models, deterministic schema
   names and examples, stable error bodies, and outputs that generated clients
   and MCP clients can validate.
3. **Replaceable transports**: the core imports neither Django Ninja nor an MCP
   SDK. A bare install is useful to integrations and does not construct HTTP
   routes by itself.

## Current Baseline

The earlier security and quality milestones have largely graduated into the
current tree and are no longer future roadmap items:

- session/CSRF bootstrap, protected docs, safe auth-admin registration, bounded
  history/autocomplete, object permission checks, and typed delete errors;
- a split test suite, strict `ty` gate, `py.typed`, 90% coverage floor, installed
  package/sample-project/generated-client smoke tests;
- the checked-in `tests/golden/openapi.json` semantic snapshot and a closed
  Pydantic error contract exercised against mounted runtime responses;
- typed semantic form metadata, one pagination contract, deterministic OpenAPI
  operation/component naming, and broad Django-admin parity coverage.

Those are preservation constraints for the split, not work to redo.

## Non-Goals

- A plain-Django REST fallback. Removing the Ninja dependency does **not** mean
  rebuilding Ninja's routing, request parsing, response dispatch, auth,
  throttling, docs, and OpenAPI generation with Django views.
- DRF compatibility or a second serializer/form abstraction.
- Rendering an HTML admin or shipping a frontend.
- Making Pydantic authoritative for persistence validation. Django forms and
  formsets remain authoritative.
- Sharing implementation by making one integration issue internal HTTP requests
  to another integration.
- Preserving every pre-beta import path forever. We will provide deliberate
  compatibility shims and a migration guide, but the dependency boundary wins.

## Committed Architecture

```text
                    django_veo_admin_api core
       Django admin semantics + Pydantic contracts + operations
                 /                                  \
 django_veo_admin_api.integrations.ninja   django_veo_admin_api.integrations.mcp
 Ninja routes/auth/Status/OpenAPI          MCP tools/auth/protocol results
```

### Core

Core owns:

- admin registry, `ModelAdmin`/inline behavior, checks, filters, changelists,
  forms, formsets, permissions, deletion collection, and audit logging;
- Pydantic `BaseModel` request/response/metadata/error contracts;
- the form-to-Pydantic and model-to-Pydantic compilers;
- JSON-safe, permission-aware object serialization;
- transport-neutral operation services for context/permissions, list/detail,
  form description, create/update/delete, list-editable bulk mutation, inlines,
  actions, history, autocomplete, and delete preview;
- transaction boundaries and response-hook validation;
- a typed operation result/error vocabulary that adapters can map to their wire
  protocols without knowing how the operation was implemented.

Core may accept Django `HttpRequest` because Django admin hooks are explicitly
request-aware. It must not import `ninja`, an MCP SDK, or adapter response
classes.

Target internal layout (exact moves may be incremental):

```text
django_veo_admin_api/
  core/
    admins/
    contracts/
    operations/
    serialization/
    field_types.py
  integrations/
    ninja/
      site.py
      routes.py
      auth.py
      schemas.py
      field_types.py
    mcp/
      server.py
      tools.py
      auth.py
      results.py
```

Models, migrations, and small compatibility re-exports can remain at the package
root where moving them would create needless Django app-label or migration risk.

### Operation boundary

Each externally callable behavior gets one operation service with a typed input
and result. An adapter is limited to:

1. authenticate and build the request context;
2. parse path/query/body/file input into the operation's input model;
3. call the operation exactly once;
4. map the typed result or error to its protocol;
5. validate/serialize the declared output.

Operations, not routes, own permission sequencing, form/formset construction,
transactions, save hooks, inline rollback, delete collection, log entries, and
the canonical error payload. This is the seam that makes Ninja optional and MCP
possible without two implementations of the admin.

### Field-type resolver boundary

Replace `BaseAdmin`'s direct `ninja.orm.fields.TYPES` lookup with an explicit
resolver protocol.

Resolution order:

1. core mappings for Django's built-in model/form fields;
2. explicit core/user registrations;
3. adapter-provided resolvers;
4. the documented string/JSON fallback where one already exists.

The Ninja adapter owns a resolver that honors Ninja `register_field()` mappings.
Any necessary access to Ninja's registry is isolated and version-tested there.
MCP and future adapters can use the core registry without installing Ninja.

### Pydantic contract base

`AdminSchema` and all shared schemas inherit from Pydantic `BaseModel`, not
`ninja.Schema`. Preserve the current `ConfigDict`, validators, serializers,
aliases, examples, titles, closed-object policy, and lazy-string handling.

The core eventually generates model schemas with Pydantic `create_model()` and
the explicit field resolver. `ninja.orm.create_schema()` may remain temporarily
during the compatibility spike, but cannot remain in the final core because it
would keep Ninja as a runtime dependency.

## Packaging And Public API

Runtime dependencies of the base distribution:

- Django;
- Pydantic v2 (direct core dependency).

Optional dependency profiles:

- `django-veo-admin-api[ninja]` — Django Ninja and the Ninja integration;
- `django-veo-admin-api[mcp]` — the supported MCP SDK and MCP integration;
- `django-veo-admin-api[all]` — both integrations, primarily for evaluation and
  CI rather than as a requirement for normal consumers.

The canonical Ninja import becomes:

```python
from django_veo_admin_api.integrations.ninja import NinjaAdminSite
```

The top-level `NinjaAdminSite` and `site` imports get lazy compatibility shims
during the pre-beta migration window. Access without the `ninja` extra must
raise one clear optional-dependency error with the exact install command; merely
importing core APIs must not import Ninja.

The bare-install contract is explicit: it provides the admin engine and
operation APIs, but no REST URL configuration. Existing users migrate from
`pip install django-veo-admin-api` to `pip install django-veo-admin-api[ninja]`.

## Architectural Decisions

1. **Django validation remains authoritative.** Pydantic parses and documents;
   the real request-aware `ModelForm`/formset performs persistence validation.
2. **One operation implementation.** Ninja routes and MCP tools call the same
   services and receive the same canonical payload/error models.
3. **No HTTP loopback.** MCP does not resolve and invoke Ninja/Django routes in
   process, create synthetic requests, or copy a hand-picked subset of
   middleware attributes. It calls operations directly with the authenticated
   Django request context.
4. **No Django REST substitute.** Ninja remains the sole REST/OpenAPI transport.
5. **Schema behavior is an executable contract.** The golden OpenAPI document,
   mounted mutation suite, and generated client decide compatibility—not an
   assumption about BaseModel support.
6. **Adapter-owned extensions.** Ninja auth, `Status`, `NOT_SET`, throttles,
   async route handling, docs, OpenAPI normalization, and `register_field()`
   compatibility stay under `integrations.ninja`.
7. **Core-owned errors.** Form, inline, bulk-row, permission, not-found,
   request-validation, conflict, and protected-delete errors share the current
   Pydantic error models. Adapters only map protocol/status representation.
8. **Closed schemas by default.** Request, response, OpenAPI, and MCP tool
   schemas keep `extra="forbid"`/`additionalProperties: false` unless a field is
   intentionally a typed map.
9. **Permission checks happen on every call.** Discovery filtering is useful
   UX, never an authorization boundary.
10. **Vendoring stays narrow and audited.** Delegate HTML-free admin behavior to
    Django where possible; retain the private-Django-API inventory and upgrade
    audit.
11. **Wire contracts remain reviewed artifacts.** Ninja OpenAPI and MCP tool
    manifests receive checked-in semantic snapshots and generated-client
    tests.
12. **Pre-beta breakage is deliberate.** Dependency/import changes ship with a
    migration guide and changelog; wire changes still require explicit golden
    review.

## Research Conclusions

### Django Ninja compatibility finding

A disposable probe against the currently pinned Django Ninja 1.6.2 established
that a plain Pydantic `BaseModel` works as both a request body and a response
schema, produces the expected OpenAPI component reference, returns the expected
422 validation shape, and is accepted as `ninja.orm.create_schema()`'s
`base_class`.

That is encouraging but intentionally not the release proof: Django Ninja's
current request-body guide still teaches `ninja.Schema`, so the supported seam
must be pinned by our full golden and mounted behavior tests.

### Lessons adopted from `django-admin-rest-api`

- Keep the library a wrapper over existing `ModelAdmin` behavior: resolve
  registered admins, start from `get_queryset()`, call the matching permission
  hook, use request-aware forms, and write the normal admin audit log.
- Use real inline formsets as a unit and raise out of `transaction.atomic()` on
  inline validation/permission failures so parent mutations roll back.
- Maintain a written wire contract, threat model, security invariants, and
  startup system checks rather than leaving those rules implicit in views.
- Keep endpoint/operation modules narrow and give every write path the same
  parsing, forbidden-field, error-envelope, and transaction helpers.
- Treat sensitive-field filtering, deny-by-default lookup, bounded pagination,
  no-store responses, and structured security logging as defense in depth.

### Lessons adapted rather than copied

- Its MCP package is correctly thin, but forwards tools into REST views through
  synthetic in-process HTTP requests. Our operation layer removes the need for
  that coupling and avoids losing locale or custom middleware request state.
- Its MCP server targets the older `2024-11-05` handshake/session protocol and
  hand-builds JSON-RPC/tool schemas. New work targets the current MCP
  `2026-07-28` stateless protocol through a supported SDK and the official
  conformance suite.
- Its generic static tools are easy to audit, but mutation `data` schemas cannot
  be model-specific at discovery time. We will generate permission-filtered,
  deterministic model-scoped tools from the same Pydantic contracts, with a
  documented cap/pagination strategy for large registries.
- We retain our typed serializer and Pydantic response models rather than
  replacing them with a broad `str()`-fallback REST contract.

## Execution Plan

### Phase 0 — Contained Compatibility Spike

Status: implemented and verified on 2026-08-09.

Land this as a small, reviewable change before moving modules.

1. Change the shared schema base from `ninja.Schema` to Pydantic `BaseModel`.
2. Add the resolver protocol and a Ninja-owned resolver; remove the direct
   `TYPES` import from core admin code while preserving `register_field()`
   behavior.
3. Keep routing and operation code otherwise unchanged.
4. Run the exact golden OpenAPI comparison, mounted CRUD/multipart/bulk/
   inline/action tests, error-contract suite, response-hook rollback tests,
   generated-client smoke, sample-project smoke, and installed-wheel smoke.
5. Add focused tests for Ninja parsing/serialization context, aliases,
   `RootModel`, dynamic `create_model()` schemas, custom registered fields,
   multipart validation, and the 422 error translation.

Exit gate: zero unreviewed OpenAPI diff and no mutation/error behavior change.
If a diff is caused only by the base-class switch, document and review it rather
than normalizing it away.

### Phase 1 — Extract The Core

1. Define `OperationResult`, the canonical operation exceptions, request
   context, and resolver interfaces.
2. Extract shared schema construction and replace
   `ninja.orm.create_schema()` with the core Pydantic compiler.
3. Extract serialization and form/formset mutation helpers from `sites.py`.
4. Move one vertical slice at a time behind services:
   - context/permissions and form descriptions;
   - list/detail/history/autocomplete;
   - create/update and inline writes;
   - bulk/action/delete and protected-delete preview.
5. For every slice, keep the existing mounted Ninja tests and add direct service
   tests proving permission ordering, form authority, transactions, output
   validation, and the canonical error payload.
6. Reduce `sites.py` to registration/cache orchestration or replace it with a
   core site plus adapter subclass once all behavior is covered.

Exit gate: core tests can run in an environment where `django-ninja` is not
installed, and an import scan finds no Ninja import outside
`integrations.ninja` and compatibility shims.

### Phase 2 — Make Ninja Optional

1. Move `NinjaAdminSite`, `NinjaAdminAPI`, routers, routes, auth, throttles,
   `Status` mapping, `NOT_SET`, async helpers, docs/OpenAPI normalization, and
   the Ninja field resolver under `django_veo_admin_api.integrations.ninja`.
2. Keep Ninja request parsing and response serialization at the mounted-route
   boundary; do not move those concerns into core.
3. Update package metadata to base + `ninja`/`mcp`/`all` extras and regenerate
   the lock file.
4. Add isolated wheel-profile tests:
   - **base**: Django + Pydantic only; core import/schema/service smoke;
   - **ninja**: the full current suite, golden OpenAPI, generated client, docs,
     multipart, auth, throttle, and sample project;
   - **all**: Ninja and MCP installed together with no route/registry conflicts.
5. Add a subprocess guard proving `import django_veo_admin_api` and core public
   imports do not add `ninja` to `sys.modules`.
6. Publish the install/import migration guide and clear missing-extra errors.

Exit gate: the base wheel has no Django Ninja requirement, while the Ninja
profile preserves the reviewed current wire contract.

### Phase 3 — Add The MCP Integration

#### Protocol/hosting spike

Before committing a public server API, prove the supported MCP SDK can be
hosted alongside Django while preserving the real authenticated request/user,
locale, and other required context. Prefer the SDK's stateless Streamable HTTP
implementation; do not hand-roll the superseded SSE transport or the old
initialize/session lifecycle.

The spike must decide and document:

- the Django session + CSRF profile for trusted first-party/browser clients;
- the standards-compliant authorization profile for remote MCP clients and how
  a verified principal maps to a Django user;
- ASGI/WSGI support boundaries and deployment topology;
- request-size, timeout, rate-limit, origin/host, and DNS-rebinding controls;
- how current `2026-07-28` requests and any SDK-provided legacy compatibility
  are tested.

#### Tool projection

1. Generate tools from operation descriptors and Pydantic input/output models;
   do not maintain parallel hand-written JSON Schemas.
2. Prefer deterministic model-scoped names such as
   `admin.shop.product.create`, filtered by the authenticated request and
   paginated/capped for large registries. Every call repeats the core permission
   check.
3. Expose discovery/list/detail/form/history/autocomplete tools first, followed
   by create/update/bulk/action/delete only after read-only behavior is stable.
4. Return `structuredContent` validated against `outputSchema`, plus the
   backwards-compatible text content required by the MCP guidance.
5. Mark tools accurately with `readOnlyHint`, `destructiveHint`,
   `idempotentHint`, and `openWorldHint`. Actions default to the conservative
   risk classification unless explicitly declared.
6. Offer adapter-level tool allow/deny policy. For destructive calls, document
   client confirmation expectations and evaluate the current multi-round-trip
   input-required mechanism without weakening the core permission path.
7. Map malformed protocol/tool arguments to protocol errors; map form,
   permission, conflict, and business failures to actionable tool execution
   errors using the same core `ErrorResponse` data.
8. Add structured security/audit logs without logging bodies, credentials,
   session IDs, CSRF values, or sensitive field contents.

#### MCP verification

- checked-in deterministic tool-manifest snapshot;
- direct operation-vs-MCP parity tests for every exposed service;
- allowed and denied users, object-level permissions, session expiry, malformed
  arguments, extra keys, large payloads, rollback, and sensitive-output tests;
- official Python SDK client smoke tests;
- official MCP conformance suite for the supported protocol revision;
- installed `django-veo-admin-api[mcp]` wheel smoke with Django Ninja absent;
- an `all` profile proving Ninja OpenAPI and MCP schemas are projections of the
  same Pydantic contracts.

Exit gate: MCP contains no admin/query/form/save logic, passes conformance, and
cannot perform an operation that the same request context would be denied by
core/Ninja.

### Phase 4 — Contract And Release Hardening

1. Document core, Ninja, and MCP public APIs separately.
2. Add architecture-boundary tests and a dependency diagram to the docs.
3. Review both golden artifacts on dependency upgrades: Ninja OpenAPI and MCP
   tool manifest/output schemas.
4. Update `docs/release-checklist.md`, security/threat-model docs, vendored code
   inventory, copyright attribution, and changelog.
5. Cut the optional-dependency change as a deliberate pre-beta release with
   before/after install and import examples.

Beta requires the base, Ninja, MCP, and all-profile gates green; reviewed golden
diffs; the Django/Python/PostgreSQL matrix; generated-client and MCP conformance
smokes; and no undocumented public compatibility shim.

## Verification Matrix

| Concern | Core | Ninja | MCP |
| --- | --- | --- | --- |
| Pydantic schema validation | direct model tests | OpenAPI + mounted parsing | input/output schema + structured content |
| Django forms/formsets | direct service tests | JSON/multipart mounted routes | tool calls through the same service |
| Permissions | service-level global/object hooks | auth + HTTP status | authenticated discovery + per-call denial |
| Transactions/audit | DB rollback and `LogEntry` | response-hook/mounted behavior | identical side effects and errors |
| Contract artifact | Pydantic JSON Schema | golden OpenAPI | golden tool manifest |
| Packaging | base wheel without Ninja/MCP | `[ninja]` wheel profile | `[mcp]` wheel profile |

Normative commands remain `just check` plus PostgreSQL and installed-profile
jobs. The split adds base/no-Ninja and MCP/conformance jobs; it does not weaken
the existing default gate.

## Remaining Product Backlog

After the split is stable:

- continue the Django private-API/vendoring audit and semantic parity work;
- complete translated package strings/catalog guidance;
- expand async support only where an adapter and Django ORM path benefit;
- continue lookup/filter/date-hierarchy edge-case parity;
- finish the documentation site and frontend/integration guides;
- define post-beta API and wire deprecation/versioning policy for both OpenAPI
  and MCP.

## Research Sources

Research snapshot: 2026-08-09.

- [`django-admin-rest-api`](https://github.com/MartinCastroAlvarez/django-admin-rest-api)
- [`django-admin-mcp-api` architecture](https://github.com/MartinCastroAlvarez/django-admin-mcp-api/blob/main/ARCHITECTURE.md)
- [Django Ninja request bodies](https://django-ninja.dev/guides/input/body/)
- [Django Ninja model schema/custom field mapping](https://django-ninja.dev/guides/response/django-pydantic/)
- [MCP 2026-07-28 tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP 2026-07-28 transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
- [MCP 2026-07-28 authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Official MCP conformance suite](https://github.com/modelcontextprotocol/conformance)

## Status And History

- Curated release notes: `CHANGELOG.md`.
- Historical accreted status log: `CHANGELOG_OLD.md`.
- Admin-behavior checklist: `docs/parity-matrix.md` (advisory).
- The golden Ninja contract: `tests/golden/openapi.json`.
