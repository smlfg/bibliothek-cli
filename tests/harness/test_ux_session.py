import os
import sys
import tempfile
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))

from ux_session import PtySession  # noqa: E402

SCRATCH_TMP = HARNESS.parents[1] / "scratch" / "tmp"


def _workspace() -> Path:
    SCRATCH_TMP.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="ux-session-test-", dir=SCRATCH_TMP))


def _script(root: Path, code: str) -> Path:
    path = root / "cli.py"
    path.write_text(code, encoding="utf-8")
    return path


def test_prompt_without_newline_expect_send_and_exit():
    root = _workspace()
    script = _script(
        root,
        'name = input("Name: ")\nprint(f"Hallo {name}")\n',
    )
    session = PtySession([sys.executable, str(script)], env=dict(os.environ))
    try:
        assert session.expect("Name: ", timeout=5)
        session.send_line("Ada")
        assert session.expect("Hallo Ada", timeout=5)
        assert session.wait_exit(5) == 0
        assert "Hallo Ada" in session.transcript
    finally:
        session.close()


def test_ansi_codes_are_ignored_for_expect():
    root = _workspace()
    script = _script(
        root,
        'import sys\n'
        'sys.stdout.write("\\x1b[31mName:\\x1b[0m ")\n'
        'sys.stdout.flush()\n'
        'name = input()\n'
        'print(f"\\x1b[32mHallo {name}\\x1b[0m")\n',
    )
    session = PtySession([sys.executable, str(script)], env=dict(os.environ))
    try:
        assert session.expect("Name: ", timeout=5)
        session.send_line("Ada")
        assert session.expect("Hallo Ada", timeout=5)
        assert session.wait_exit(5) == 0
    finally:
        session.close()


def test_timeout_returns_false_and_kills_process_group():
    root = _workspace()
    script = _script(root, "import time\ntime.sleep(30)\n")
    session = PtySession([sys.executable, str(script)], env=dict(os.environ))
    started = time.monotonic()
    try:
        assert session.expect("Nie", timeout=0.3) is False
        assert time.monotonic() - started < 3
        code = session.wait_exit(0.3)
        assert code is not None
        assert time.monotonic() - started < 5
    finally:
        session.close()


def test_regex_expect():
    root = _workspace()
    script = _script(root, 'print("Kurs 4711 bereit")\n')
    session = PtySession([sys.executable, str(script)], env=dict(os.environ))
    try:
        assert session.expect(r"Kurs \d+ bereit", timeout=5, regex=True)
        assert session.wait_exit(5) == 0
    finally:
        session.close()
