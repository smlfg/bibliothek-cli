"""Akzeptanztests: jede UX-Sitzung gegen den Fake-Server."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_DIR = REPO_ROOT / "tests" / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from fake_server import FakeServer  # noqa: E402
from ux_session import PtySession, strip_ansi  # noqa: E402
from ux_spec import parse  # noqa: E402

SPEC = parse(REPO_ROOT / "docs" / "UX.md")


@pytest.fixture
def home() -> Path:
    base = REPO_ROOT / "scratch" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="acceptance-home-", dir=base))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _tool_command() -> list[str]:
    candidate = Path(sys.executable).with_name("bibliothek")
    if candidate.is_file():
        return [str(candidate)]
    executable = shutil.which("bibliothek")
    if executable:
        return [executable]
    return [
        sys.executable,
        "-c",
        "from bibliothek_cli.cli import main; raise SystemExit(main())",
    ]


def _env(server: FakeServer, home: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    for name in (
        "BIBLIOTHEK_USER",
        "BIBLIOTHEK_PASSWORD",
        "BIBLIOTHEK_BASE_URL",
        "BIBLIOTHEK_CONFIG",
    ):
        env.pop(name, None)
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "XDG_STATE_HOME": str(home / ".local" / "state"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "BIBLIOTHEK_BASE_URL": server.base_url,
            "PYTHONPATH": str(HARNESS_DIR),
            "PYTHONUNBUFFERED": "1",
            "ACCEPTANCE_SANDBOX": "1",
            "ACCEPTANCE_NET_LOG": str(home / "net.log"),
            "TERM": "xterm",
            "LANG": "C.UTF-8",
        }
    )
    env.update(extra)
    return env


def _foreign_requests(home: Path) -> list[str]:
    log = home / "net.log"
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class PtyResult:
    code: int | None
    text: str
    missing: str | None = None


def _run_pty(
    argv: list[str],
    env: dict[str, str],
    *,
    inputs: list[tuple[object, str | None]] | None = None,
    timeout: float = 20.0,
) -> PtyResult:
    session = PtySession(argv, env=env, cwd=REPO_ROOT)
    missing: str | None = None
    try:
        for pattern, answer in inputs or []:
            found = session.expect(pattern, timeout=timeout) if pattern else True
            if not found:
                missing = str(pattern)
                session.kill()
                break
            if answer is not None:
                session.send_line(answer)
        code = session.wait_exit(timeout)
        text = strip_ansi(session.transcript)
    finally:
        session.close()
    return PtyResult(code=code, text=text, missing=missing)


def _login(server: FakeServer, home: Path) -> dict[str, str]:
    env = _env(
        server,
        home,
        BIBLIOTHEK_USER="123456789",
        BIBLIOTHEK_PASSWORD="geheim",
    )
    result = subprocess.run(
        _tool_command() + ["login", "--json"],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return env


def _session_path(home: Path) -> Path:
    return home / ".config" / "bibliothek-cli" / "session.json"


def test_login_session_gegen_fake_server(home):
    with FakeServer(SPEC, REPO_ROOT) as server:
        env = _env(server, home)
        result = _run_pty(
            _tool_command() + ["login"],
            env,
            inputs=[
                (re.compile(r"(Ausweisnummer|Benutzernummer)"), "123456789"),
                (re.compile(r"Passwort"), "geheim"),
                (re.compile(r"Login erfolgreich als 123456789"), None),
            ],
        )

        assert result.missing is None, result.text
        assert result.code == 0, result.text
        assert "Login erfolgreich als 123456789" in result.text
        assert _foreign_requests(home) == []

        posts = [
            record
            for record in server.requests
            if record.method == "POST" and "service=login" in record.query
        ]
        assert posts, "Login-POST mit service=login fehlt"
        fields = posts[-1].values
        assert fields.get("$Textfield") == ["123456789"]
        assert fields.get("$Textfield$0") == ["geheim"]

        session = _session_path(home)
        assert session.is_file()
        assert stat.S_IMODE(session.stat().st_mode) == 0o600
        data = json.loads(session.read_text(encoding="utf-8"))
        assert data["user"] == "123456789"
        assert "geheim" not in session.read_text(encoding="utf-8")


def test_search_und_show_session_gegen_fake_server(home):
    with FakeServer(SPEC, REPO_ROOT) as server:
        env = _env(server, home)

        result = _run_pty(
            _tool_command() + ["search", "Grundlagen der Hydraulik"], env
        )
        assert result.missing is None, result.text
        assert result.code == 0, result.text
        assert "Treffer: 2" in result.text
        assert "[1] Grundlagen der Hydraulik" in result.text
        assert _foreign_requests(home) == []

        search_posts = [
            record
            for record in server.requests
            if record.method == "POST" and "service=search" in record.query
        ]
        assert search_posts, "Such-POST mit service=search fehlt"
        assert search_posts[-1].values.get("$Autosuggest") == [
            "Grundlagen der Hydraulik"
        ]

        result = _run_pty(
            _tool_command() + ["show", "Grundlagen der Hydraulik"], env
        )
        assert result.missing is None, result.text
        assert result.code == 0, result.text
        assert "Titel: Grundlagen der Hydraulik" in result.text
        assert "ID: AK63638611" in result.text
        assert _foreign_requests(home) == []

        detail_posts = [
            record
            for record in server.requests
            if record.method == "POST" and "service=detail" in record.query
        ]
        assert detail_posts, "Detail-POST mit service=detail fehlt"


def test_verlaengern_session_gegen_fake_server(home):
    with FakeServer(SPEC, REPO_ROOT) as server:
        _login(server, home)
        env = _env(server, home)
        before = len(server.requests)

        result = _run_pty(
            _tool_command() + ["verlaengern", "Grundlagen der Hydraulik"],
            env,
            inputs=[
                (re.compile(r"Auswahl \[1-2\]:"), "1"),
                (re.compile(r"Verlängerung verbindlich\? \[j/N\]"), "j"),
                (re.compile(r"Verlängerung (bestätigt|erfolgreich)"), None),
            ],
        )

        assert result.missing is None, result.text
        assert result.code == 0, result.text
        assert "Neues Fälligkeitsdatum: 07.12.2026" in result.text
        assert _foreign_requests(home) == []

        sent = server.sent_formsteps()
        ids = [step_id for step_id, _record in sent]
        assert ids == [
            "konto_laden",
            "verlaengern_absenden",
            "verlaengern_bestaetigen",
        ]
        by_id = {step_id: record for step_id, record in sent}
        assert "selected" in by_id["konto_laden"].fields
        assert "cellCheck$0" in by_id["verlaengern_absenden"].fields
        assert "textButton$1" in by_id["verlaengern_absenden"].fields
        assert "bestaetigungstoken" in by_id["verlaengern_bestaetigen"].fields
        assert "textButton" in by_id["verlaengern_bestaetigen"].fields
        assert server.missing_formsteps() == []
        assert len(server.requests) > before


def test_verlaengern_ohne_tty_bricht_vor_request_ab(home):
    with FakeServer(SPEC, REPO_ROOT) as server:
        _login(server, home)
        env = _env(server, home)
        before = len(server.requests)

        result = subprocess.run(
            _tool_command() + ["verlaengern", "Grundlagen der Hydraulik"],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
        )

        assert result.returncode == 5, result.stdout + result.stderr
        assert "login" in (result.stdout + result.stderr).lower()
        assert len(server.requests) == before
        assert server.sent_formsteps() == []
        assert _foreign_requests(home) == []
