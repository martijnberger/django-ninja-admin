NINJA_INSTALL_COMMAND = "pip install 'django-veo-admin-api[ninja]'"


def missing_ninja_dependency(exc: ModuleNotFoundError) -> ImportError:
    return ImportError(
        "Django Ninja is required for django_veo_admin_api.integrations.ninja; "
        f"install it with `{NINJA_INSTALL_COMMAND}`."
    )
