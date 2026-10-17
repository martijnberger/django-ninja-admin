# API Versioning And Deprecation

`django-veo-admin-api` is still pre-beta. Wire contracts may change while the
split is being completed, but every release reviews the generated OpenAPI and
MCP tool-manifest diffs before publication.

## Versioning Rules

- Before beta, incompatible API changes are allowed when they move the package
  toward the documented v1 contract.
- After Phase 4 is complete, the OpenAPI document and MCP tool manifest are
  treated as public wire contracts for generated clients.
- Patch releases contain compatible bug fixes and documentation corrections.
- Minor releases may add compatible endpoints, fields, schemas, examples,
  hooks, or optional behavior.
- Major releases are required for contract-breaking API or wire-shape changes.

## Release Decisions

Every release candidate must compare candidate OpenAPI and MCP manifests with
the previous reviewed artifacts. The following changes require an explicit
release decision:

- Removing a route, operation, field, schema, example, or response status.
- Renaming a route parameter, response field, component, operation ID, tag, or
  security scheme.
- Changing required fields, nullability, scalar types, enum values, request
  media types, response status maps, or documented error bodies.
- Changing authentication requirements for docs, OpenAPI, site routes, model
  routes, actions, autocomplete, history, or mutations.
- Changing an MCP tool name, annotation, input/output schema, structured error
  envelope, discovery policy, or supported protocol revision.

Compatible additions still need review, but they do not require a major version
when existing generated clients can continue to parse their current workflows.

## Deprecation Policy

After Phase 4, a deprecated field, endpoint, tool, hook, or behavior should remain
available for at least one minor release before removal unless it is a security
fix. Deprecations should be documented in user-facing release notes and, where
possible, reflected in OpenAPI descriptions.

Security fixes may remove or tighten unsafe behavior immediately. When that
happens, the release notes should call out the affected contract and migration
path.

## Contract Gate

The checked-in golden OpenAPI snapshot, golden MCP manifest,
generated-client smoke, and official MCP conformance smoke are the default
contract gates. A release is not ready if either generated diff is unreviewed
or either integration cannot exercise its documented core flows.
