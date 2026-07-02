from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = ROOT / "docs" / "parity-matrix.md"
KNOWN_STATUSES = ("implemented", "partial", "missing", "changed")
EMPTY_EVIDENCE = {"", "-", "n/a", "na", "none", "todo", "tbd"}


@dataclass(frozen=True)
class ParityRow:
    section: str
    item: str
    status: str
    evidence: str
    remaining_work: str
    line_number: int

    @property
    def has_evidence(self) -> bool:
        return self.evidence.strip().lower() not in EMPTY_EVIDENCE


@dataclass(frozen=True)
class ParityReport:
    source: str
    rows: tuple[ParityRow, ...]

    @property
    def status_counts(self) -> Counter[str]:
        return Counter(row.status for row in self.rows)

    @property
    def evidence_gaps(self) -> tuple[ParityRow, ...]:
        return tuple(row for row in self.rows if not row.has_evidence)

    @property
    def missing_rows(self) -> tuple[ParityRow, ...]:
        return tuple(row for row in self.rows if row.status == "missing")

    @property
    def partial_rows(self) -> tuple[ParityRow, ...]:
        return tuple(row for row in self.rows if row.status == "partial")


def parse_parity_matrix(path: Path = DEFAULT_MATRIX) -> ParityReport:
    rows: list[ParityRow] = []
    section = ""
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if not line.startswith("|") or set(line.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue
        cells = _split_markdown_row(line)
        if len(cells) != 4:
            continue
        item, status, evidence, remaining_work = cells
        if item in {"Area", "Behavior"} or status == "Status":
            continue
        normalized_status = status.strip().lower()
        if normalized_status not in KNOWN_STATUSES:
            continue
        rows.append(
            ParityRow(
                section=section,
                item=item,
                status=normalized_status,
                evidence=evidence,
                remaining_work=remaining_work,
                line_number=line_number,
            )
        )
    return ParityReport(source=str(path), rows=tuple(rows))


def _split_markdown_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def report_to_dict(report: ParityReport) -> dict[str, object]:
    status_counts = report.status_counts
    return {
        "source": report.source,
        "total_rows": len(report.rows),
        "status_counts": {status: status_counts.get(status, 0) for status in KNOWN_STATUSES},
        "evidence_gaps": [asdict(row) for row in report.evidence_gaps],
        "missing_rows": [asdict(row) for row in report.missing_rows],
        "partial_rows": [asdict(row) for row in report.partial_rows],
    }


def render_text(report: ParityReport, *, show_rows: Sequence[str]) -> str:
    status_counts = report.status_counts
    lines = [
        "Parity Matrix Report",
        f"Source: {report.source}",
        f"Rows: {len(report.rows)}",
        "Status counts:",
    ]
    for status in KNOWN_STATUSES:
        lines.append(f"  {status}: {status_counts.get(status, 0)}")

    if report.evidence_gaps:
        lines.append("")
        lines.append(f"Rows lacking evidence: {len(report.evidence_gaps)}")
        for row in report.evidence_gaps:
            lines.append(f"  {row.line_number}: [{row.section}] {row.item} ({row.status})")
    else:
        lines.append("")
        lines.append("Rows lacking evidence: 0")

    for status in show_rows:
        rows = tuple(row for row in report.rows if row.status == status)
        lines.append("")
        lines.append(f"{status.title()} rows: {len(rows)}")
        for row in rows:
            lines.append(f"  {row.line_number}: [{row.section}] {row.item}")
            if row.remaining_work:
                lines.append(f"    remaining: {row.remaining_work}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize parity matrix status and evidence gaps.")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX, help="Path to the parity matrix markdown file.")
    parser.add_argument("--json", action="store_true", help="Write machine-readable JSON instead of text.")
    parser.add_argument(
        "--show-rows",
        default="partial,missing",
        help="Comma-separated statuses to list in text output. Use an empty value to hide row details.",
    )
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero when any row is still missing.")
    parser.add_argument(
        "--fail-on-evidence-gaps",
        action="store_true",
        help="Exit non-zero when any parity row has empty or placeholder evidence.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Equivalent to --fail-on-missing --fail-on-evidence-gaps.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = parse_parity_matrix(args.matrix)

    if args.json:
        print(json.dumps(report_to_dict(report), indent=2, sort_keys=True))
    else:
        show_rows = tuple(status for status in _parse_status_list(args.show_rows) if status in KNOWN_STATUSES)
        print(render_text(report, show_rows=show_rows))

    fail_on_missing = args.fail_on_missing or args.strict
    fail_on_evidence_gaps = args.fail_on_evidence_gaps or args.strict
    if fail_on_missing and report.missing_rows:
        return 1
    if fail_on_evidence_gaps and report.evidence_gaps:
        return 1
    return 0


def _parse_status_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


if __name__ == "__main__":
    raise SystemExit(main())
