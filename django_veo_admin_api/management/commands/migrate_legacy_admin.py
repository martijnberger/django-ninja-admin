"""Adopt the pre-0.2 Django app identity without copying or losing audit rows."""

from typing import Any, cast, override

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, router
from django.db.migrations.recorder import MigrationRecorder

from django_veo_admin_api.models import LogEntry

LEGACY_APP = "django_ninja_admin"
CURRENT_APP = "django_veo_admin_api"
LEGACY_TABLE = "django_ninja_admin_log"
MIGRATIONS = ("0001_initial", "0002_alter_logentry_options_alter_logentry_managers")
log_options = cast(Any, LogEntry)._meta


class Command(BaseCommand):
    help = (
        "Preview or apply the django-ninja-admin to django-veo-admin-api database identity upgrade. "
        "Run before migrate, with application workers stopped."
    )
    requires_migrations_checks = False

    @override
    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Database alias to upgrade.")
        parser.add_argument("--apply", action="store_true", help="Apply the previewed upgrade atomically.")

    @override
    def handle(self, *args, **options):
        if any(config.label == LEGACY_APP for config in apps.get_app_configs()):
            raise CommandError("Remove the legacy django_ninja_admin app from INSTALLED_APPS first.")
        connection = connections[options["database"]]
        if not router.allow_migrate_model(connection.alias, LogEntry):
            raise CommandError("The database router does not allow the audit model on this database.")
        if not connection.features.can_rollback_ddl:
            raise CommandError("This upgrade requires transactional DDL; use PostgreSQL or SQLite.")
        plan = self._plan(connection)
        if plan is None:
            self.stdout.write("Already upgraded; no changes are needed.")
            return

        applied, old_content_type_id = plan
        self.stdout.write(f"Rename {LEGACY_TABLE} to {log_options.db_table} on {connection.alias}.")
        self.stdout.write(f"Record matching {CURRENT_APP} migrations: {', '.join(applied)}.")
        if old_content_type_id is not None:
            self.stdout.write(
                f"Relabel content type {old_content_type_id}; preserve its ID, permissions, and all foreign keys."
            )
        if not options["apply"]:
            self.stdout.write("Dry run only. Back up the database, stop writers, and rerun with --apply.")
            return

        # Enter the schema editor before its transaction so SQLite can disable
        # constraint checks. PostgreSQL and SQLite both roll back the whole step.
        with connection.schema_editor(atomic=True) as editor:
            if self._plan(connection) != plan:
                raise CommandError("Database state changed after preflight; rerun the preview.")
            editor.alter_db_table(LogEntry, LEGACY_TABLE, log_options.db_table)
            if old_content_type_id is not None:
                ContentType.objects.using(connection.alias).filter(pk=old_content_type_id).update(app_label=CURRENT_APP)
            recorder = MigrationRecorder(connection)
            for name in applied:
                recorder.record_applied(CURRENT_APP, name)
        ContentType.objects.clear_cache()
        self.stdout.write(self.style.SUCCESS("Upgrade applied. Run migrate, then restart application workers."))

    @staticmethod
    def _plan(connection):
        tables = set(connection.introspection.table_names())
        target_table = log_options.db_table
        history = MigrationRecorder(connection).applied_migrations()
        legacy = {name for app, name in history if app == LEGACY_APP}
        current = {name for app, name in history if app == CURRENT_APP}

        if LEGACY_TABLE not in tables:
            if target_table in tables and "0001_initial" in current:
                return None
            raise CommandError("No legacy audit table found. Fresh installations should run migrate normally.")
        if target_table in tables or current:
            raise CommandError(
                "Both legacy and new database state exist. Refusing to merge or overwrite data. "
                "Restore the pre-upgrade backup or reconcile the two installations explicitly."
            )
        if "0001_initial" not in legacy or legacy - set(MIGRATIONS):
            raise CommandError("Unknown or incomplete legacy migration history; refusing to adopt the table.")
        with connection.cursor() as cursor:
            columns = {column.name for column in connection.introspection.get_table_description(cursor, LEGACY_TABLE)}
        expected = {field.column for field in log_options.local_fields}
        if columns != expected:
            raise CommandError("Legacy audit table columns do not match the supported schema.")
        content_types = ContentType.objects.using(connection.alias)
        if content_types.filter(app_label=CURRENT_APP).exists():
            raise CommandError("New-app content types already exist; refusing to change IDs or permission assignments.")
        legacy_types = list(content_types.filter(app_label=LEGACY_APP).values_list("pk", "model"))
        if any(model != "logentry" for _, model in legacy_types):
            raise CommandError("Unknown legacy content types; review them before upgrading.")
        old_content_type_id = legacy_types[0][0] if legacy_types else None
        return tuple(name for name in MIGRATIONS if name in legacy), old_content_type_id
