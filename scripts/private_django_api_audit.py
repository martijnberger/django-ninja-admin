from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOC = REPO_ROOT / "docs" / "private-django-api-audit.md"


@dataclass(frozen=True)
class PrivateApiUse:
    symbol: str
    pattern: str
    expected_paths: tuple[str, ...]
    reason: str
    upgrade_check: str


PRIVATE_API_INVENTORY = (
    PrivateApiUse(
        symbol="_get_foreign_key",
        pattern=r"\b_get_foreign_key\b",
        expected_paths=(
            "django_ninja_admin/admins/inline.py",
            "django_ninja_admin/checks.py",
            "django_ninja_admin/sites.py",
        ),
        reason="Match Django inline parent foreign-key resolution for formsets and system checks.",
        upgrade_check="Compare with django.forms.models._get_foreign_key when upgrading Django.",
    ),
    PrivateApiUse(
        symbol="request.parse_file_upload",
        pattern=r"\.parse_file_upload\(",
        expected_paths=("django_ninja_admin/sites.py",),
        reason="Parse multipart JSON+file requests through Django's request upload parser.",
        upgrade_check="Verify Django request upload parsing still accepts the same META/request arguments.",
    ),
    PrivateApiUse(
        symbol="queryset.query.order_by",
        pattern=r"\.query\.order_by\b",
        expected_paths=("django_ninja_admin/changelist.py",),
        reason="Detect explicit queryset ordering before applying deterministic changelist fallback ordering.",
        upgrade_check="Confirm Query.order_by remains the correct low-level source for explicit ordering.",
    ),
    PrivateApiUse(
        symbol="_get_FIELD_display",
        pattern=r"\._get_FIELD_display\(",
        expected_paths=("django_ninja_admin/utils/lookup.py",),
        reason="Reuse Django's choice-label conversion while serializing list/detail display values.",
        upgrade_check="Compare with Model._get_FIELD_display and public get_FOO_display behavior.",
    ),
    PrivateApiUse(
        symbol="media._css/_js",
        pattern=r"\bmedia\._(?:css|js)\b",
        expected_paths=("django_ninja_admin/utils/forms.py",),
        reason="Expose form/widget media assets as structured JSON for frontend clients.",
        upgrade_check="Verify django.forms.Media still stores CSS/JS assets on _css and _js.",
    ),
    PrivateApiUse(
        symbol="widget._parse_date_fmt",
        pattern=r"\._parse_date_fmt\(",
        expected_paths=("django_ninja_admin/utils/forms.py",),
        reason="Expose SelectDateWidget ordering metadata without rendering HTML.",
        upgrade_check="Check SelectDateWidget date-format parsing on each Django feature release.",
    ),
)


def source_files(repo_root: Path) -> list[Path]:
    package_root = repo_root / "django_ninja_admin"
    return sorted(path for path in package_root.rglob("*.py") if path.is_file())


def scan_private_api_usage(
    repo_root: Path,
    inventory: tuple[PrivateApiUse, ...] = PRIVATE_API_INVENTORY,
) -> dict[str, list[str]]:
    usage = {entry.symbol: set() for entry in inventory}
    compiled = {entry.symbol: re.compile(entry.pattern) for entry in inventory}
    for path in source_files(repo_root):
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(repo_root).as_posix()
        for symbol, pattern in compiled.items():
            if pattern.search(text):
                usage[symbol].add(relative_path)
    return {symbol: sorted(paths) for symbol, paths in usage.items()}


def validate_private_api_audit(
    repo_root: Path = REPO_ROOT,
    doc_path: Path = DEFAULT_DOC,
    inventory: tuple[PrivateApiUse, ...] = PRIVATE_API_INVENTORY,
) -> list[str]:
    errors: list[str] = []
    usage = scan_private_api_usage(repo_root, inventory)
    doc_text = doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
    if not doc_text:
        errors.append(f"Audit document is missing or empty: {doc_path}")

    for entry in inventory:
        observed = tuple(usage[entry.symbol])
        if observed != entry.expected_paths:
            errors.append(f"{entry.symbol}: expected {list(entry.expected_paths)}, found {list(observed)}")
        if entry.symbol not in doc_text:
            errors.append(f"{entry.symbol}: missing from {doc_path}")
        for expected_path in entry.expected_paths:
            if expected_path not in doc_text:
                errors.append(f"{entry.symbol}: {expected_path} missing from {doc_path}")
    return errors


def report_to_dict(
    repo_root: Path = REPO_ROOT,
    inventory: tuple[PrivateApiUse, ...] = PRIVATE_API_INVENTORY,
) -> dict[str, Any]:
    usage = scan_private_api_usage(repo_root, inventory)
    return {
        "private_api_count": len(inventory),
        "private_apis": [
            {
                "symbol": entry.symbol,
                "paths": usage[entry.symbol],
                "reason": entry.reason,
                "upgrade_check": entry.upgrade_check,
            }
            for entry in inventory
        ],
    }


def render_text(payload: dict[str, Any]) -> str:
    lines = ["Private Django API Audit", f"Private APIs: {payload['private_api_count']}"]
    for entry in payload["private_apis"]:
        paths = ", ".join(entry["paths"]) or "<none>"
        lines.append(f"- {entry['symbol']}: {paths}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit private Django API usage.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--json", action="store_true", help="Print machine-readable audit output.")
    args = parser.parse_args(argv)

    errors = validate_private_api_audit(args.repo_root, args.doc)
    payload = report_to_dict(args.repo_root)
    if args.json:
        print(json.dumps({**payload, "errors": errors}, indent=2, sort_keys=True))
    else:
        print(render_text(payload))
        if errors:
            print("\nErrors:")
            for error in errors:
                print(f"- {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
