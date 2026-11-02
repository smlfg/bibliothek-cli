import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parents[1]
UX_CHECK = HARNESS / "ux_check.py"
GOOD = HARNESS / "selftest" / "good_cli"
BAD = HARNESS / "selftest" / "bad_cli"
NOCHECK = HARNESS / "selftest" / "nocheck_cli"
SCRATCH_TMP = REPO / "scratch" / "tmp"


def _workdir() -> Path:
    SCRATCH_TMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="ux-check-selftest-", dir=SCRATCH_TMP))


def _run_check(repo: Path, spec_only: bool = False):
    root = _workdir()
    report = root / "report.md"
    command = [
        sys.executable,
        str(UX_CHECK),
        str(repo),
        "--venv",
        str(root / "venv"),
        "--report",
        str(report),
    ]
    if spec_only:
        command.append("--spec-only")
    result = subprocess.run(
        command,
        cwd=str(REPO),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    text = report.read_text(encoding="utf-8") if report.is_file() else result.stdout
    return result.returncode, result.stdout, text


def _rows(report: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in report.splitlines():
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) >= 3 and parts[0].startswith("UX"):
            rows[parts[0]] = parts[1]
    return rows


def test_good_cli_passes():
    code, stdout, report = _run_check(GOOD)
    rows = _rows(report)
    assert code == 0, stdout
    assert "FAIL" not in rows.values(), report
    assert rows["UX01"] == "PASS"
    assert rows["UX04"] == "PASS"
    assert rows["UX05"] == "PASS"
    assert rows["UX08"] == "PASS"
    assert rows["UX09"] == "PASS"


def test_nocheck_cli_fails_ux09_with_both_findings():
    code, stdout, report = _run_check(NOCHECK)
    rows = _rows(report)
    assert code != 0, stdout
    assert rows.get("UX09") == "FAIL", report
    assert "(a)" in report, report
    assert "(b)" in report, report
    assert "Pflichtfeld 'status'" in report, report
    assert "nochecktool login" in report, report


def test_bad_cli_fails_expected_checks():
    code, stdout, report = _run_check(BAD)
    rows = _rows(report)
    assert code != 0, stdout
    for check in ("UX02", "UX04", "UX05", "UX06"):
        assert rows.get(check) == "FAIL", f"{check} sollte FAIL sein:\n{report}"
    assert rows.get("UX08") == "FAIL" or rows.get("UX07") == "FAIL", report
    assert "nie gesendet" in report
    assert "nie gesendet" in stdout


def test_good_cli_spec_only_passes_without_installation():
    code, stdout, _report = _run_check(GOOD, spec_only=True)
    assert code == 0, stdout
    assert "| UX01 | PASS |" in stdout
    assert "| UX06 | PASS |" in stdout
    assert "| UX07 | PASS |" in stdout
