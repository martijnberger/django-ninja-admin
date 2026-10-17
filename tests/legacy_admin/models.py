"""Frozen pre-rename audit model used only to build real upgrade databases."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class LogEntry(models.Model):
    action_time = models.DateTimeField(default=timezone.now, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE)
    content_type = models.ForeignKey("contenttypes.ContentType", models.SET_NULL, blank=True, null=True)
    object_id = models.TextField(blank=True, null=True)
    object_repr = models.CharField(max_length=200)
    action_flag = models.PositiveSmallIntegerField(choices=[(1, "Addition"), (2, "Change"), (3, "Deletion")])
    change_message = models.TextField(blank=True)

    class Meta:
        db_table = "django_ninja_admin_log"
