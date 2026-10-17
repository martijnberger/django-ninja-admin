"""Run each side of a real package upgrade in its own Django process."""

import json
import os
import sys

import django
import pytest
from django.conf import settings

phase = sys.argv[1]
legacy = phase in {"seed", "seed_initial"}
settings.configure(
    SECRET_KEY="upgrade-test",
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "tests.legacy_admin" if legacy else "django_veo_admin_api",
    ],
    DATABASES={"default": json.loads(os.environ["ADMIN_UPGRADE_TEST_DATABASE"])},
    DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group, Permission  # noqa: E402
from django.contrib.contenttypes.models import ContentType  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.db import connection  # noqa: E402
from django.db.migrations.recorder import MigrationRecorder  # noqa: E402

if legacy:
    from tests.legacy_admin.models import LogEntry

    call_command("migrate", verbosity=0, interactive=False)
    if phase == "seed_initial":
        call_command("migrate", "django_ninja_admin", "0001_initial", verbosity=0, interactive=False)
    user = get_user_model().objects.create_user("upgrade-user")
    content_type = ContentType.objects.get(app_label="django_ninja_admin", model="logentry")
    user.user_permissions.add(Permission.objects.get(content_type=content_type, codename="view_logentry"))
    group = Group.objects.create(name="upgrade-group")
    group.permissions.add(Permission.objects.get(content_type=content_type, codename="change_logentry"))
    user.groups.add(group)
    entry = LogEntry.objects.create(
        user=user,
        content_type=content_type,
        object_id="42",
        object_repr="Preserved audit",
        action_flag=2,
        change_message="Preserved message",
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE upgrade_reference (id integer PRIMARY KEY, log_id bigint "
            "REFERENCES django_ninja_admin_log(id))"
        )
        cursor.execute("INSERT INTO upgrade_reference (id, log_id) VALUES (%s, %s)", [1, entry.pk])
    print(json.dumps({"content_type_id": content_type.pk, "user_id": user.pk}))
else:
    from django_veo_admin_api.models import LogEntry

    if phase == "preview":
        call_command("migrate_legacy_admin")
        assert "django_ninja_admin_log" in connection.introspection.table_names()
        assert not any(app == "django_veo_admin_api" for app, _ in MigrationRecorder(connection).applied_migrations())
    elif phase == "upgrade":
        call_command("migrate_legacy_admin", apply=True)
        call_command("migrate", verbosity=0, interactive=False)
        call_command("migrate_legacy_admin", apply=True)  # Safe to retry.
        call_command("makemigrations", "django_veo_admin_api", check=True, dry_run=True, verbosity=0)
        user = get_user_model().objects.get(username="upgrade-user")
        entry = LogEntry.objects.get(object_repr="Preserved audit")
        content_type = ContentType.objects.get(app_label="django_veo_admin_api", model="logentry")
        assert entry.content_type_id == content_type.pk
        assert entry.change_message == "Preserved message"
        assert entry.user_id == user.pk
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT log.object_repr FROM upgrade_reference ref "
                "JOIN django_veo_admin_api_log log ON ref.log_id = log.id"
            )
            assert cursor.fetchone() == ("Preserved audit",)
        assert user.has_perm("django_veo_admin_api.view_logentry")
        assert user.has_perm("django_veo_admin_api.change_logentry")
        assert not ContentType.objects.filter(app_label="django_ninja_admin").exists()
        assert "django_ninja_admin_log" not in connection.introspection.table_names()
        history = MigrationRecorder(connection).applied_migrations()
        assert ("django_ninja_admin", "0001_initial") in history
        assert ("django_veo_admin_api", "0001_initial") in history
        # The adopted table's sequence and FKs must also support new writes.
        second = LogEntry.objects.create(user=user, action_flag=1, object_repr="New audit", change_message="")
        assert second.pk > entry.pk
        print(json.dumps({"content_type_id": content_type.pk, "user_id": user.pk}))
    elif phase == "collision":
        ContentType.objects.create(app_label="django_veo_admin_api", model="logentry")
        with pytest.raises(CommandError, match="content types already exist"):
            call_command("migrate_legacy_admin", apply=True)
        assert "django_ninja_admin_log" in connection.introspection.table_names()
        assert "django_veo_admin_api_log" not in connection.introspection.table_names()
    elif phase == "rollback":
        from unittest.mock import patch

        with (
            patch.object(MigrationRecorder, "record_applied", side_effect=RuntimeError("injected failure")),
            pytest.raises(RuntimeError, match="injected failure"),
        ):
            call_command("migrate_legacy_admin", apply=True)
        assert "django_ninja_admin_log" in connection.introspection.table_names()
        assert "django_veo_admin_api_log" not in connection.introspection.table_names()
        assert ContentType.objects.filter(app_label="django_ninja_admin", model="logentry").exists()
        assert not ContentType.objects.filter(app_label="django_veo_admin_api").exists()
    elif phase == "both_tables":
        call_command("migrate", verbosity=0, interactive=False)
        with pytest.raises(CommandError, match="Both legacy and new database state"):
            call_command("migrate_legacy_admin", apply=True)
        assert {"django_ninja_admin_log", "django_veo_admin_api_log"} <= set(connection.introspection.table_names())
    else:
        raise AssertionError(f"Unknown phase: {phase}")
