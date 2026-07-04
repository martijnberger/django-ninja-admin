from __future__ import annotations

import json

from scripts.private_django_api_audit import (
    PrivateApiUse,
    main,
    report_to_dict,
    validate_private_api_audit,
)


def test_private_django_api_audit_passes_current_tree(capsys):
    exit_code = main([])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Private Django API Audit" in output
    assert "_get_foreign_key" in output


def test_private_django_api_audit_json_output_is_serializable(capsys):
    exit_code = main(["--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["private_api_count"] >= 1
    assert payload["errors"] == []


def test_private_django_api_audit_reports_source_and_doc_drift(tmp_path):
    package_root = tmp_path / "django_ninja_admin"
    package_root.mkdir()
    (package_root / "module.py").write_text(
        "request.parse_file_upload(request.META, request)\n",
        encoding="utf-8",
    )
    doc = tmp_path / "audit.md"
    doc.write_text("request.parse_file_upload\n", encoding="utf-8")
    inventory = (
        PrivateApiUse(
            symbol="request.parse_file_upload",
            pattern=r"\.parse_file_upload\(",
            expected_paths=("django_ninja_admin/expected.py",),
            reason="test",
            upgrade_check="test",
        ),
    )

    errors = validate_private_api_audit(tmp_path, doc, inventory)

    expected = (
        "request.parse_file_upload: expected ['django_ninja_admin/expected.py'], found ['django_ninja_admin/module.py']"
    )
    assert expected in errors
    assert "request.parse_file_upload: django_ninja_admin/expected.py missing from" in "\n".join(errors)


def test_private_django_api_report_includes_expected_paths():
    payload = report_to_dict()

    paths_by_symbol = {entry["symbol"]: entry["paths"] for entry in payload["private_apis"]}
    assert "django_ninja_admin/sites.py" in paths_by_symbol["_get_foreign_key"]
