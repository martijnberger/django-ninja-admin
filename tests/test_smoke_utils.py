from pathlib import Path

import pytest

from scripts.smoke_utils import resolve_prebuilt_wheel


def test_resolve_prebuilt_wheel_returns_none_without_env(monkeypatch):
    monkeypatch.delenv("DJANGO_NINJA_ADMIN_WHEEL", raising=False)

    assert resolve_prebuilt_wheel() is None


def test_resolve_prebuilt_wheel_accepts_file(monkeypatch, tmp_path):
    wheel = tmp_path / "django_ninja_admin-1.2.3-py3-none-any.whl"
    wheel.write_text("wheel", encoding="utf-8")
    monkeypatch.setenv("DJANGO_NINJA_ADMIN_WHEEL", str(wheel))

    assert resolve_prebuilt_wheel() == wheel.resolve()


def test_resolve_prebuilt_wheel_accepts_directory(monkeypatch, tmp_path):
    older = tmp_path / "django_ninja_admin-1.2.2-py3-none-any.whl"
    newer = tmp_path / "django_ninja_admin-1.2.3-py3-none-any.whl"
    older.write_text("older", encoding="utf-8")
    newer.write_text("newer", encoding="utf-8")
    monkeypatch.setenv("DJANGO_NINJA_ADMIN_WHEEL", str(tmp_path))

    assert resolve_prebuilt_wheel() == newer.resolve()


@pytest.mark.parametrize(
    "path",
    [
        "missing.whl",
        "other_package-1.2.3-py3-none-any.whl",
        "django_ninja_admin-1.2.3.tar.gz",
    ],
)
def test_resolve_prebuilt_wheel_rejects_invalid_values(monkeypatch, tmp_path, path):
    candidate = tmp_path / path
    if not path.startswith("missing"):
        candidate.write_text("invalid", encoding="utf-8")
    monkeypatch.setenv("DJANGO_NINJA_ADMIN_WHEEL", str(candidate))

    with pytest.raises(SystemExit):
        resolve_prebuilt_wheel()


def test_resolve_prebuilt_wheel_rejects_empty_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("DJANGO_NINJA_ADMIN_WHEEL", str(Path(tmp_path)))

    with pytest.raises(SystemExit):
        resolve_prebuilt_wheel()
