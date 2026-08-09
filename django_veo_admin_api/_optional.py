NINJA_INSTALL_COMMAND = "pip install 'django-veo-admin-api[ninja]'"
MCP_INSTALL_COMMAND = "pip install 'django-veo-admin-api[mcp]'"


def missing_ninja_dependency(exc: ModuleNotFoundError) -> ImportError:
    return ImportError(
        "Django Ninja is required for django_veo_admin_api.integrations.ninja; "
        f"install it with `{NINJA_INSTALL_COMMAND}`."
    )


def missing_mcp_dependency(exc: ModuleNotFoundError) -> ImportError:
    return ImportError(
        f"The MCP SDK is required for django_veo_admin_api.integrations.mcp; install it with `{MCP_INSTALL_COMMAND}`."
    )
