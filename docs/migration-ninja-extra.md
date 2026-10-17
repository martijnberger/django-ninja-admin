# Migrating To The Ninja Extra

## Upgrading from `django-ninja-admin`

The 0.2 package rename changes both the Python package and Django's app label:
`django_ninja_admin` becomes `django_veo_admin_api`. Existing databases require
the explicit adoption step below; a normal `migrate` by itself creates a new,
empty audit table rather than adopting the old history.

1. Back up the database and stop application workers, scheduled jobs, and
   other writers for the upgrade window. Rehearse the steps against a restored
   backup first.
2. Replace the installed distribution with `django-veo-admin-api[ninja]` (or
   `[mcp]`/`[all]` as appropriate). Remove the old package/app; do not install
   both Django apps together.
3. Replace `django_ninja_admin` imports and the `INSTALLED_APPS` entry with
   `django_veo_admin_api`. Update settings, permission strings such as
   `django_veo_admin_api.view_logentry`, and code using reverse relation names
   (`django_veo_admin_api_logentry_user` and
   `django_veo_admin_api_logentry_logentries`).
4. Review project-owned migration files for dependencies on
   `("django_ninja_admin", ...)`, relation targets such as
   `"django_ninja_admin.LogEntry"`, and imports from the old package. Update
   those references to the new label/package so Django can load the project
   migration graph after the package is replaced. The package command retains
   the old recorded migration rows and records the matching new ones.
5. Preview the database adoption **before running `migrate`**:

   ```bash
   python manage.py migrate_legacy_admin
   ```

6. Review the preview, then apply it to the same database:

   ```bash
   python manage.py migrate_legacy_admin --apply
   python manage.py migrate
   python manage.py check
   ```

7. Verify audit history and user/group permissions in the upgraded project,
   then restart workers. Clear application caches that contain old permission
   strings or serialized model labels.

Use `--database <alias>` on both management commands for a non-default audit
database. The adoption step supports PostgreSQL and SQLite with transactional
DDL and checks the database router before changing anything.

The command renames `django_ninja_admin_log` to
`django_veo_admin_api_log`, preserves every row/primary key, changes the audit
model's content-type label **without changing its ID**, and records matching
initial migration history. User/group permission assignments, audit references,
generic foreign keys through the content type, and foreign keys to audit rows
therefore keep their identifiers. Existing sequences continue to generate new
IDs. Both known legacy migration states (initial only, or initial plus the
manager/options migration) are supported. Rerunning the completed adoption is
a no-op.

The command refuses unknown schemas/migration history, conflicting content
types, or a database containing both old and new audit tables. It does not
merge, delete, or overwrite those installations. If `migrate` was already run
against the renamed app, restore the pre-upgrade backup or reconcile that
specific database before adopting it. A failed adoption transaction rolls back
the table rename, content type change, and migration records together. To roll
back the whole package upgrade after resuming writes, restore the backup and
the previous application version together.

Fresh installations have no legacy data to adopt and should run `migrate`
normally.

## Installing the optional Ninja integration

Django Ninja is no longer an unconditional dependency. Existing HTTP/OpenAPI
users should change their installation command from:

```bash
python -m pip install django-veo-admin-api
```

to:

```bash
python -m pip install 'django-veo-admin-api[ninja]'
```

The base installation contains Django-admin semantics, Pydantic contracts,
schema compilers, serialization, error contracts, and operation services. It
does not construct REST routes or generate OpenAPI by itself.

## Imports

Use the integration namespace for Ninja transport objects:

```python
from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.integrations.ninja import NinjaAdminSite, site
```

The pre-beta compatibility window keeps these imports lazy:

```python
from django_veo_admin_api import NinjaAdminSite, site
```

They still require the `[ninja]` extra. Accessing either object without it
raises an `ImportError` that includes the exact installation command. Importing
the package, core admin classes, schemas, or operation services does not import
Django Ninja.

There is intentionally no plain-Django HTTP fallback. Routing, parsing,
response handling, authentication, docs, and OpenAPI remain the responsibility
of the Ninja adapter.
