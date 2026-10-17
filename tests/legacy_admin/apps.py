from django.apps import AppConfig


class LegacyAdminConfig(AppConfig):
    name = "tests.legacy_admin"
    label = "django_ninja_admin"
    default_auto_field = "django.db.models.BigAutoField"
