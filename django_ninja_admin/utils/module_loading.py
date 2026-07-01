from copy import copy
from importlib import import_module

from django.apps import apps
from django.utils.module_loading import module_has_submodule


def _site_state(register_to):
    if register_to is None:
        return {}
    return {
        attr: copy(getattr(register_to, attr))
        for attr in ("_registry", "_actions", "_global_actions")
        if hasattr(register_to, attr)
    }


def _restore_site_state(register_to, state):
    if register_to is None:
        return
    for attr, value in state.items():
        setattr(register_to, attr, value)
    if hasattr(register_to, "clear_cache"):
        register_to.clear_cache()


def autodiscover_modules(*args, **kwargs):
    register_to = kwargs.get("register_to")
    for app_config in apps.get_app_configs():
        for module_to_search in args:
            before_import_state = _site_state(register_to)
            try:
                import_module(f"{app_config.name}.{module_to_search}")
            except Exception:
                if module_has_submodule(app_config.module, module_to_search):
                    _restore_site_state(register_to, before_import_state)
                    raise
                if register_to is not None:
                    register_to.clear_cache()
