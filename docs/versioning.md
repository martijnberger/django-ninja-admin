# API Versioning And Deprecation

`django-ninja-admin` is still pre-beta. Wire contracts may change while
Milestones 1-3 are being completed, but every release reviews the generated
OpenAPI diff before publication.

## Versioning Rules

- Before beta, incompatible API changes are allowed when they move the package
  toward the documented v1 contract.
- After Milestone 3 is complete, the OpenAPI document is treated as the public
  wire contract for generated clients.
- Patch releases contain compatible bug fixes and documentation corrections.
- Minor releases may add compatible endpoints, fields, schemas, examples,
  hooks, or optional behavior.
- Major releases are required for contract-breaking API or wire-shape changes.

## Release Decisions

Every release candidate must compare the candidate OpenAPI document with the
previous reviewed artifact. The following changes require an explicit release
decision:

- Removing a route, operation, field, schema, example, or response status.
- Renaming a route parameter, response field, component, operation ID, tag, or
  security scheme.
- Changing required fields, nullability, scalar types, enum values, request
  media types, response status maps, or documented error bodies.
- Changing authentication requirements for docs, OpenAPI, site routes, model
  routes, actions, autocomplete, history, or mutations.

Compatible additions still need review, but they do not require a major version
when existing generated clients can continue to parse their current workflows.

## Deprecation Policy

After Milestone 3, a deprecated field, endpoint, hook, or behavior should remain
available for at least one minor release before removal unless it is a security
fix. Deprecations should be documented in user-facing release notes and, where
possible, reflected in OpenAPI descriptions.

Security fixes may remove or tighten unsafe behavior immediately. When that
happens, the release notes should call out the affected contract and migration
path.

## Contract Gate

The checked-in golden OpenAPI snapshot and generated-client smoke test are the
default contract gate. A release is not ready if the generated OpenAPI diff is
unreviewed or if generated clients cannot exercise the documented core flows.
