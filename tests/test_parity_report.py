from __future__ import annotations

import json
from pathlib import Path

from scripts.parity_report import main, parse_parity_matrix, render_text, report_to_dict


def write_matrix(path: Path) -> None:
    path.write_text(
        """
# Matrix

## Area One

| Area | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| Public API | implemented | import tests | Keep stable |
| Serializer hooks | changed | docs/api-and-auth.md | More examples |

## Area Two

| Behavior | Status | Evidence | Remaining Work |
| --- | --- | --- | --- |
| OpenAPI | partial | route tests | Snapshots |
| Legacy view | missing | TODO | Port behavior |
""".lstrip(),
        encoding="utf-8",
    )


def test_parse_parity_matrix_counts_statuses_and_evidence_gaps(tmp_path):
    matrix = tmp_path / "matrix.md"
    write_matrix(matrix)

    report = parse_parity_matrix(matrix)

    assert len(report.rows) == 4
    assert report.status_counts == {"implemented": 1, "changed": 1, "partial": 1, "missing": 1}
    assert [row.item for row in report.evidence_gaps] == ["Legacy view"]
    assert [row.item for row in report.missing_rows] == ["Legacy view"]
    assert [row.item for row in report.partial_rows] == ["OpenAPI"]


def test_render_text_lists_requested_status_rows(tmp_path):
    matrix = tmp_path / "matrix.md"
    write_matrix(matrix)

    output = render_text(parse_parity_matrix(matrix), show_rows=("partial", "missing"))

    assert "Rows: 4" in output
    assert "implemented: 1" in output
    assert "Rows lacking evidence: 1" in output
    assert "[Area Two] OpenAPI" in output
    assert "[Area Two] Legacy view" in output


def test_report_to_dict_is_json_serializable(tmp_path):
    matrix = tmp_path / "matrix.md"
    write_matrix(matrix)

    payload = report_to_dict(parse_parity_matrix(matrix))

    assert payload["total_rows"] == 4
    assert payload["status_counts"]["missing"] == 1
    json.dumps(payload)


def test_main_strict_fails_for_missing_rows_and_evidence_gaps(tmp_path, capsys):
    matrix = tmp_path / "matrix.md"
    write_matrix(matrix)

    exit_code = main(["--matrix", str(matrix), "--strict", "--show-rows", ""])

    assert exit_code == 1
    assert "Rows lacking evidence: 1" in capsys.readouterr().out


def test_main_passes_for_current_matrix(capsys):
    exit_code = main(["--show-rows", ""])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Parity Matrix Report" in output
    assert "Rows lacking evidence: 0" in output
