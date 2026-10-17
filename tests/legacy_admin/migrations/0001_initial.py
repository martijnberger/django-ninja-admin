"""The durable database shape of django-ninja-admin before its package rename."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [
        migrations.CreateModel(
            name="LogEntry",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("action_time", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("object_id", models.TextField(blank=True, null=True)),
                ("object_repr", models.CharField(max_length=200)),
                (
                    "action_flag",
                    models.PositiveSmallIntegerField(choices=[(1, "Addition"), (2, "Change"), (3, "Deletion")]),
                ),
                ("change_message", models.TextField(blank=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={"db_table": "django_ninja_admin_log"},
        )
    ]
