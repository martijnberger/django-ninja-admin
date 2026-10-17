import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "django_veo_admin_api"


def test_optional_sdk_imports_stay_inside_their_integrations():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        if relative.parts[:2] in {("integrations", "ninja"), ("integrations", "mcp")}:
            continue
        for module in _imported_modules(path):
            if module.split(".", 1)[0] in {"ninja", "mcp"}:
                violations.append(f"{relative}: {module}")
    assert violations == []


def test_core_does_not_import_transport_integrations():
    violations = []
    for path in (PACKAGE / "core").rglob("*.py"):
        relative = path.relative_to(PACKAGE)
        for module in _imported_modules(path):
            if module == "django_veo_admin_api.integrations" or module.startswith("django_veo_admin_api.integrations."):
                violations.append(f"{relative}: {module}")
    assert violations == []


def _imported_modules(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
