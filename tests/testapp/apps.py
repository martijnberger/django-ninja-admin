from django.apps import AppConfig


class TestAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.testapp"
    label = "testapp"

    def ready(self):
        from tests.testapp import admin  # noqa: F401
