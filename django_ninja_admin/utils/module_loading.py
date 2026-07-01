from importlib import import_module

from django.apps import apps
from django.utils.module_loading import module_has_submodule


def autodiscover_modules(*args, **kwargs):
    register_to = kwargs.get("register_to")
    for app_config in apps.get_app_configs():
        for module_to_search in args:
            try:
                import_module(f"{app_config.name}.{module_to_search}")
            except Exception:
                if module_has_submodule(app_config.module, module_to_search):
                    raise
                if register_to is not None:
                    register_to.clear_cache()

