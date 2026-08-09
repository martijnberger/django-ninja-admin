import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_isolated(code: str) -> None:
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_core_public_imports_do_not_import_ninja():
    run_isolated(
        """
import sys

import django_veo_admin_api
import django
from django.conf import settings

settings.configure(
    SECRET_KEY="optional-dependency-test",
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django_veo_admin_api",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
django.setup()

from django_veo_admin_api import ModelAdmin
from django_veo_admin_api.core.operations import AdminRequestContext, OperationResult
from django_veo_admin_api.schemas import AdminSchema

assert django_veo_admin_api is not None
assert ModelAdmin is not None
assert AdminRequestContext is not None
assert OperationResult is not None
assert AdminSchema is not None
assert not any(name == "ninja" or name.startswith("ninja.") for name in sys.modules)
"""
    )


def test_missing_ninja_extra_has_an_actionable_error():
    run_isolated(
        """
import sys

import django
from django.conf import settings

settings.configure(
    SECRET_KEY="optional-dependency-test",
    INSTALLED_APPS=[
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django_veo_admin_api",
    ],
    DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}},
)
django.setup()


class BlockNinjaImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "ninja" or fullname.startswith("ninja."):
            raise ModuleNotFoundError(f"blocked import: {fullname}", name=fullname)
        return None


sys.meta_path.insert(0, BlockNinjaImports())

import django_veo_admin_api

try:
    django_veo_admin_api.NinjaAdminSite
except ImportError as exc:
    assert str(exc) == (
        "Django Ninja is required for django_veo_admin_api.integrations.ninja; "
        "install it with `pip install 'django-veo-admin-api[ninja]'`."
    )
else:
    raise AssertionError("NinjaAdminSite unexpectedly imported without Django Ninja")
"""
    )


def test_missing_mcp_extra_has_an_actionable_error():
    run_isolated(
        """
import sys


class BlockMCPImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ModuleNotFoundError(f"blocked import: {fullname}", name=fullname)
        return None


sys.meta_path.insert(0, BlockMCPImports())

try:
    from django_veo_admin_api.integrations.mcp import MCPAdminServer
except ImportError as exc:
    assert str(exc) == (
        "The MCP SDK is required for django_veo_admin_api.integrations.mcp; "
        "install it with `pip install 'django-veo-admin-api[mcp]'`."
    )
else:
    raise AssertionError(f"MCPAdminServer unexpectedly imported without the MCP SDK: {MCPAdminServer}")
"""
    )
