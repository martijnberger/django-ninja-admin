from django.apps import AppConfig


class TestAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tests.testapp"
    label = "testapp"

    def ready(self):
        from importlib import import_module

        import_module("tests.testapp.admin")
