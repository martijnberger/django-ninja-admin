from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
MKDOCS_CONFIG = ROOT / "mkdocs.yml"
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REQUIRED_GUIDES = {
    "setup.md",
    "api-and-auth.md",
    "frontend-integration.md",
    "hook-reference.md",
    "contract-reference.md",
}


def main() -> int:
    config = _load_config()
    docs_dir = ROOT / config.get("docs_dir", "docs")
    nav_paths = set(_iter_nav_paths(config.get("nav", [])))
    errors = []

    if not docs_dir.is_dir():
        errors.append(f"docs_dir does not exist: {docs_dir.relative_to(ROOT)}")

    missing_guides = sorted(REQUIRED_GUIDES - nav_paths)
    errors.extend(f"required guide is missing from mkdocs nav: {path}" for path in missing_guides)

    for path in sorted(nav_paths):
        target = docs_dir / path
        if not target.is_file():
            errors.append(f"mkdocs nav target is missing: {path}")

    markdown_files = [ROOT / "README.md", *sorted(docs_dir.rglob("*.md"))]
    for markdown_file in markdown_files:
        errors.extend(_broken_links(markdown_file, docs_dir=docs_dir))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"Documentation nav and links OK ({len(nav_paths)} nav pages, {len(markdown_files)} markdown files).")
    return 0


def _load_config() -> dict[str, Any]:
    with MKDOCS_CONFIG.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise SystemExit("mkdocs.yml must contain a mapping")
    return value


def _iter_nav_paths(nav: Any):
    if isinstance(nav, str):
        yield nav
        return
    if isinstance(nav, list):
        for item in nav:
            yield from _iter_nav_paths(item)
        return
    if isinstance(nav, dict):
        for item in nav.values():
            yield from _iter_nav_paths(item)


def _broken_links(markdown_file: Path, *, docs_dir: Path) -> list[str]:
    errors = []
    text = markdown_file.read_text(encoding="utf-8")
    base_dir = markdown_file.parent
    for raw_target in LINK_RE.findall(text):
        parsed = urlparse(raw_target)
        if parsed.scheme in {"http", "https", "mailto"} or raw_target.startswith("#"):
            continue
        target_path = unquote(parsed.path)
        if not target_path:
            continue
        candidate = ROOT / target_path.lstrip("/") if target_path.startswith("/") else base_dir / target_path
        if candidate.is_dir():
            candidate = candidate / "index.md"
        if not candidate.exists():
            label = markdown_file.relative_to(ROOT)
            errors.append(f"{label}: broken local link: {raw_target}")
            continue
        if docs_dir in candidate.resolve().parents and candidate.suffix != ".md":
            label = markdown_file.relative_to(ROOT)
            errors.append(f"{label}: docs links should point at markdown sources: {raw_target}")
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
