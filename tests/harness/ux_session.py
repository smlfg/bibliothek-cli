"""PTY-Sitzungen und Schreibprüfungen für die UX-Harness (Standardbibliothek)."""

from __future__ import annotations

import argparse
import os
import pty
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

try:
    from fake_server import FakeServer
    from ux_spec import INSTALL_RE, Session, UxSpec, is_write_session, parse
except ImportError:  # pragma: no cover - Paketimport
    from .fake_server import FakeServer
    from .ux_spec import INSTALL_RE, Session, UxSpec, is_write_session, parse

HARNESS_DIR = Path(__file__).resolve().parent
DEFAULT_TIMEOUT = 20.0


def free_local_port() -> int:
    """Freien localhost-Port wählen, damit alle Sitzungen dieselbe Basis-URL sehen."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _AnsiStripper:
    def __init__(self) -> None:
        self.state = "normal"
        self._osc_esc = False

    def feed(self, text: str) -> str:
        out: list[str] = []
        for char in text:
            if self.state == "normal":
                if char == "\x1b":
                    self.state = "esc"
                else:
                    out.append(char)
            elif self.state == "esc":
                if char == "[":
                    self.state = "csi"
                elif char in "])PX^_":
                    self.state = "osc"
                    self._osc_esc = False
                else:
                    self.state = "normal"
            elif self.state == "csi":
                if "\x40" <= char <= "\x7e":
                    self.state = "normal"
            elif self.state == "osc":
                if self._osc_esc:
                    self._osc_esc = False
                    if char == "\\":
                        self.state = "normal"
                elif char == "\x07":
                    self.state = "normal"
                elif char == "\x1b":
                    self._osc_esc = True
        return "".join(out)


def strip_ansi(text: str) -> str:
    return _AnsiStripper().feed(text)


class _FormFieldParser(HTMLParser):
    """Sammelt Namen und required-Markierung aller Formularfelder."""

    SKIP_INPUT_TYPES = {"submit", "button", "reset", "image"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.fields: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "form":
            self.depth += 1
            return
        if not self.depth:
            return
        values = {name.lower(): (value or "") for name, value in attrs}
        name = values.get("name", "").strip()
        if not name:
            return
        if tag == "input":
            kind = values.get("type", "text").lower()
            if kind in self.SKIP_INPUT_TYPES:
                return
            if kind in {"checkbox", "radio"} and "required" not in values:
                return
        elif tag not in {"select", "textarea"}:
            return
        self.fields.append((name, "required" in values))

    def handle_endtag(self, tag) -> None:
        if tag == "form" and self.depth:
            self.depth -= 1


def form_fields(html: str) -> dict[str, bool]:
    """Feldname -> required; leeres Ergebnis, wenn kein <form> gefunden wird."""
    parser = _FormFieldParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - defektes HTML wird übersprungen
        return {}
    result: dict[str, bool] = {}
    for name, required in parser.fields:
        result[name] = result.get(name, False) or required
    return result


def check_previous_form_fields(spec: UxSpec, repo_dir, sent) -> list[str]:
    """Prüft jeden formstep ab dem zweiten gegen das Formular davor."""
    repo = Path(repo_dir)
    records: dict[str, object] = {}
    for step_id, record in sent:
        records.setdefault(step_id, record)
    fails: list[str] = []
    for index, step in enumerate(spec.formsteps):
        if index == 0 or step.id not in records:
            continue
        previous = spec.formsteps[index - 1]
        if not previous.response:
            continue
        try:
            html = (repo / previous.response).read_text(encoding="utf-8")
        except OSError:
            continue
        fields = form_fields(html)
        if not fields:
            continue
        record = records[step.id]
        values = getattr(record, "values", {})
        for name, required in fields.items():
            submitted = values.get(name)
            if submitted is None:
                fails.append(
                    f"formstep '{step.id}': Feld '{name}' aus dem Formular "
                    f"von '{previous.id}' fehlt – fragt `login` danach?"
                )
            elif required and all(not str(value).strip() for value in submitted):
                fails.append(
                    f"formstep '{step.id}': Pflichtfeld '{name}' aus dem Formular "
                    f"von '{previous.id}' leer – fragt `login` danach?"
                )
    return fails


@dataclass
class SessionResult:
    ok: bool
    fails: list[str]
    transcript: str
    confirm_time: float | None = None
    title: str = ""
    run: str = ""


@dataclass
class CheckResult:
    ok: bool
    fails: list[str]
    runs: list[SessionResult] = field(default_factory=list)


class PtySession:
    def __init__(self, command, env=None, cwd=None):
        if isinstance(command, str):
            command = ["/bin/sh", "-c", command]
        self.command = list(command)
        self.env = dict(os.environ if env is None else env)
        self.cwd = str(cwd) if cwd is not None else None
        self.transcript = ""
        self.pid = 0
        self.fd = -1
        self._pending = ""
        self._stripper = _AnsiStripper()
        self._eof = False
        self._status: int | None = None
        self._started = False
        self.start()

    def start(self) -> None:
        if self._started:
            return
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - Kindprozess
            try:
                if self.cwd:
                    os.chdir(self.cwd)
                os.execvpe(self.command[0], self.command, self.env)
            except BaseException as exc:
                try:
                    os.write(2, f"exec failed: {exc}\n".encode("utf-8", "replace"))
                finally:
                    os._exit(127)
        self.pid = pid
        self.fd = fd
        self._started = True
        try:
            import fcntl
            import struct
            import termios

            size = struct.pack("HHHH", 40, 120, 0, 0)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
        except OSError:
            pass
        os.set_blocking(fd, False)

    def _append(self, data: bytes) -> bool:
        if not data:
            self._eof = True
            return False
        text = data.decode("utf-8", "replace")
        self.transcript += text
        self._pending += self._stripper.feed(text)
        return True

    def _read_once(self, timeout: float) -> bool:
        ready, _, _ = select.select([self.fd], [], [], max(0.0, timeout))
        if not ready:
            return False
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return False
        except OSError:
            self._eof = True
            return False
        return self._append(data)

    def _drain(self) -> None:
        while True:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                return
            try:
                data = os.read(self.fd, 65536)
            except (BlockingIOError, OSError):
                return
            if not self._append(data):
                return

    def expect(self, pattern, timeout: float = DEFAULT_TIMEOUT, regex: bool = False) -> bool:
        if isinstance(pattern, re.Pattern):
            regex = True
            matcher = pattern
        elif regex:
            matcher = re.compile(pattern)
        else:
            matcher = re.compile(re.escape(pattern))
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            match = matcher.search(self._pending)
            if match is not None:
                self._pending = self._pending[match.end():]
                return True
            if self._eof:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._read_once(min(remaining, 0.2))

    def send_line(self, text: str = "") -> None:
        os.write(self.fd, (text + "\n").encode("utf-8"))

    def send_eof(self) -> None:
        try:
            os.write(self.fd, b"\x04")
        except OSError:
            pass

    def poll(self) -> int | None:
        if self._status is not None:
            return self._status
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self._status = -1
            return self._status
        if pid == 0:
            return None
        self._status = os.waitstatus_to_exitcode(status)
        return self._status

    def kill(self) -> None:
        if self.poll() is not None:
            return
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            _, status = os.waitpid(self.pid, 0)
        except ChildProcessError:
            return
        self._status = os.waitstatus_to_exitcode(status)

    def wait_exit(self, timeout: float = DEFAULT_TIMEOUT) -> int | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            code = self.poll()
            if code is not None:
                self._drain()
                return code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.kill()
                return self.poll()
            self._read_once(min(remaining, 0.1))

    def close(self) -> None:
        if self._started and self.poll() is None:
            self.kill()
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = -1


def session_env(spec: UxSpec, server: FakeServer | None, env: dict | None) -> dict[str, str]:
    merged = dict(os.environ)
    merged.update({str(key): str(value) for key, value in (env or {}).items()})
    meta = spec.meta or {}
    extra = meta.get("env")
    if isinstance(extra, dict):
        merged.update({str(key): str(value) for key, value in extra.items()})
    base = meta.get("base_url_env")
    if base and server is not None:
        merged[str(base)] = server.base_url
    return merged


def _exit_code(text: str) -> int:
    parts = text.split()
    if len(parts) == 2 and parts[0] == "exit":
        try:
            return int(parts[1])
        except ValueError:
            pass
    raise ValueError(f"ungültige Exit-Zeile: {text!r}")


def _run_session(
    spec: UxSpec,
    session: Session,
    server: FakeServer,
    env: dict | None,
    answer_override: str | None,
    run_label: str,
) -> SessionResult:
    merged = session_env(spec, server, env)
    cwd = merged.get("UX_REPO_DIR") or None
    fails: list[str] = []
    parts: list[str] = []
    confirm_time: float | None = None
    current: PtySession | None = None
    override_pending = False
    skip_expects = False

    def close_current(expected: int | None = None) -> int | None:
        nonlocal current
        if current is None:
            return None
        code = current.wait_exit(DEFAULT_TIMEOUT)
        parts.append(current.transcript)
        if code is None:
            fails.append("Befehl beendet sich nicht (Timeout)")
        elif expected is None:
            if code != 0:
                fails.append(f"unerwarteter Exit-Code {code} (erwartet 0)")
        elif code != expected:
            fails.append(f"Exit-Code {code}, erwartet {expected}")
        current.close()
        current = None
        return code

    def abort_current() -> None:
        nonlocal current
        if current is None:
            return
        current.kill()
        current._drain()
        parts.append(current.transcript)
        current.close()
        current = None

    for step in session.steps:
        if step.kind == "command":
            if INSTALL_RE.match(step.text.strip()):
                continue
            if current is not None:
                close_current(0)
            current = PtySession(["/bin/sh", "-c", step.text], env=merged, cwd=cwd)
            continue
        if step.kind == "input":
            if current is None:
                fails.append(f"Eingabe ohne laufenden Befehl: {step.text!r}")
                continue
            text = step.text
            if override_pending and answer_override is not None:
                text = answer_override
                override_pending = False
                skip_expects = True
            current.send_line(text)
            continue
        if step.kind in {"expect", "regex"}:
            if current is None:
                fails.append(f"Erwartung ohne laufenden Befehl: {step.text!r}")
                continue
            if skip_expects:
                continue
            is_confirm = "[j/N]" in step.text
            try:
                found = current.expect(
                    step.text, timeout=DEFAULT_TIMEOUT, regex=(step.kind == "regex")
                )
            except re.error as exc:
                fails.append(f"ungültiger Regex {step.text!r}: {exc}")
                found = False
            if not found:
                label = "Regex" if step.kind == "regex" else "Ausgabe"
                fails.append(f"erwartete {label} nicht gefunden: {step.text!r}")
                abort_current()
                break
            if is_confirm:
                confirm_time = server.mark("confirm")
                if answer_override is not None:
                    override_pending = True
            continue
        if step.kind == "exit":
            try:
                expected = _exit_code(step.text)
            except ValueError as exc:
                fails.append(str(exc))
                continue
            if current is None:
                fails.append(f"Exit-Prüfung ohne laufenden Befehl: {step.text!r}")
                continue
            close_current(expected)

    if current is not None:
        close_current(0)

    transcript = "".join(parts)
    if "Traceback (most recent call last)" in strip_ansi(transcript):
        fails.append("Traceback im Mitschnitt")
    return SessionResult(
        ok=not fails,
        fails=fails,
        transcript=transcript,
        confirm_time=confirm_time,
        title=session.title,
        run=run_label,
    )


def run_session(
    spec: UxSpec,
    session: Session,
    server: FakeServer,
    env: dict | None,
    answer_override: str | None = None,
    run_label: str = "",
) -> SessionResult:
    return _run_session(spec, session, server, env, answer_override, run_label)


CONFIRM_TEXT = "[j/N]"
LOGIN_OFFER_RE = re.compile(r"(?i)\[\s*(?:j|ja)\s*(?:/\s*(?:n|nein))?\s*\]")


def _login_offer(text: str):
    for match in LOGIN_OFFER_RE.finditer(text):
        context = text[max(0, match.start() - 200): match.end() + 200].lower()
        if "login" in context or "anmeld" in context:
            return match
    return None


def run_write_without_login(
    spec: UxSpec,
    session: Session,
    server: FakeServer,
    env: dict | None,
    tool: str,
) -> SessionResult:
    """Spielt eine schreibende Sitzung ohne Login und ohne credential_env."""
    merged = session_env(spec, server, env)
    cwd = merged.get("UX_REPO_DIR") or None
    fails: list[str] = []
    parts: list[str] = []
    current: PtySession | None = None

    for step in session.steps:
        if step.kind == "command":
            if INSTALL_RE.match(step.text.strip()):
                continue
            if current is not None:
                current.wait_exit(DEFAULT_TIMEOUT)
                parts.append(current.transcript)
                current.close()
                current = None
            current = PtySession(["/bin/sh", "-c", step.text], env=merged, cwd=cwd)
            continue
        if step.kind == "input":
            if current is None:
                continue
            try:
                current.send_line(step.text)
            except OSError:
                pass
            continue
        if step.kind in {"expect", "regex"} and CONFIRM_TEXT in step.text:
            break

    if current is None:
        fails.append("kein ausführbarer Befehl in der Sitzung")
    else:
        deadline = time.monotonic() + DEFAULT_TIMEOUT
        answered_login = False
        while current.poll() is None and time.monotonic() < deadline:
            current._read_once(min(0.2, max(0.0, deadline - time.monotonic())))
            pending = current._pending
            if CONFIRM_TEXT in pending:
                fails.append(
                    f"{CONFIRM_TEXT} ausgegeben, obwohl Login/Voraussetzungen fehlen"
                )
                if current.poll() is None:
                    current.kill()
                current._drain()
                break
            if not answered_login:
                match = _login_offer(pending)
                if match is not None:
                    try:
                        current.send_line("n")
                    except OSError:
                        pass
                    answered_login = True
                    current._pending = pending[match.end():]
        code = current.wait_exit(DEFAULT_TIMEOUT)
        parts.append(current.transcript)
        if code is None:
            fails.append("Befehl beendet sich nicht (Timeout)")
        elif code == 0:
            fails.append("Exit-Code 0, erwartet ≠ 0")
        current.close()

    transcript = "".join(parts)
    clean = strip_ansi(transcript)
    if "Traceback (most recent call last)" in clean:
        fails.append("Traceback im Mitschnitt")
    if f"{tool} login" not in clean:
        fails.append(f"Ausgabe nennt nicht den Befehl `{tool} login`")
    for step_id, _record in server.sent_formsteps():
        step = _step_by_id(spec, step_id)
        if step is not None and not step.before_confirm:
            fails.append(f"formstep '{step_id}' ohne before_confirm gesendet")
    return SessionResult(
        ok=not fails,
        fails=fails,
        transcript=transcript,
        title=session.title,
        run="UX09a",
    )


def _step_by_id(spec: UxSpec, step_id: str):
    for step in spec.formsteps:
        if step.id == step_id:
            return step
    return None


def check_write(spec: UxSpec, session: Session, server_factory, env: dict | None) -> CheckResult:
    runs: list[SessionResult] = []
    aggregate: list[str] = []

    with server_factory() as server:
        first = run_session(spec, session, server, env, answer_override="N", run_label="a (N)")
        for step_id, _record in server.sent_formsteps():
            step = _step_by_id(spec, step_id)
            if step is not None and not step.before_confirm:
                first.fails.append(
                    f"formstep '{step_id}' ohne before_confirm gesendet"
                )
        first.ok = not first.fails
        runs.append(first)
        aggregate.extend(f"Lauf (a): {fail}" for fail in first.fails)

    with server_factory() as server:
        second = run_session(spec, session, server, env, run_label="b (j)")
        sent_ids = [step_id for step_id, _record in server.sent_formsteps()]
        last_sent = sent_ids[-1] if sent_ids else None
        for step, reason in server.missing_formsteps():
            if reason == "nie gesendet":
                if last_sent is None:
                    text = (
                        f"formstep '{step.id}' nie gesendet – die Aktion endet "
                        "nach keinem Schritt"
                    )
                else:
                    text = (
                        f"formstep '{step.id}' nie gesendet – die Aktion endet "
                        f"nach Schritt '{last_sent}'"
                    )
                second.fails.append(text)
            elif reason.startswith("Felder fehlen"):
                second.fails.append(f"formstep '{step.id}': {reason}")
            else:
                second.fails.append(f"formstep '{step.id}': {reason}")
        expected_ids = [step.id for step in spec.formsteps]
        if not server.missing_formsteps() and sent_ids != expected_ids:
            second.fails.append(
                "formstep-Reihenfolge falsch: erwartet "
                f"{expected_ids}, gesendet {sent_ids}"
            )
        if second.confirm_time is not None:
            for step in server.formsteps_before(second.confirm_time):
                if not step.before_confirm:
                    second.fails.append(
                        f"formstep '{step.id}' vor der [j/N]-Frage gesendet"
                    )
        second.ok = not second.fails
        runs.append(second)
        aggregate.extend(f"Lauf (b): {fail}" for fail in second.fails)

    return CheckResult(ok=all(run.ok for run in runs), fails=aggregate, runs=runs)


def _tool_from_pyproject(repo_dir: Path) -> str | None:
    pyproject = repo_dir / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        import tomllib

        data = tomllib.loads(text)
        project = data.get("project", {})
        scripts = project.get("scripts", {})
        if isinstance(scripts, dict) and scripts:
            return str(next(iter(scripts)))
        if project.get("name"):
            return str(project["name"])
    except (ImportError, ValueError):
        pass
    match = re.search(r"^\[project\.scripts\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if match:
        for line in match.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                return line.split("=", 1)[0].strip()
    match = re.search(r'^name\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return match.group(1) if match else None


def install_fresh(repo_dir, venv_dir, tool: str | None = None) -> Path:
    repo = Path(repo_dir).resolve()
    venv = Path(venv_dir).resolve()
    if venv.is_symlink():
        venv.unlink()
    elif venv.exists():
        shutil.rmtree(venv)
    venv.parent.mkdir(parents=True, exist_ok=True)
    create = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        capture_output=True,
        text=True,
    )
    if create.returncode != 0:
        raise RuntimeError(f"venv-Anlage fehlgeschlagen: {create.stderr.strip()}")
    pip = venv / "bin" / "pip"
    env = dict(os.environ)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    install = subprocess.run(
        [str(pip), "install", "-q", str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )
    if install.returncode != 0:
        raise RuntimeError(
            "pip install fehlgeschlagen: "
            + (install.stderr.strip() or install.stdout.strip())
        )
    expected = tool or _tool_from_pyproject(repo)
    if expected:
        exe = venv / "bin" / expected
        if not exe.is_file():
            raise RuntimeError(
                f"Befehl '{expected}' nicht in {venv / 'bin'} nach Installation"
            )
    return venv / "bin"


def build_env(
    spec: UxSpec,
    server: FakeServer | None,
    home,
    bin_dir,
    repo_dir,
) -> dict[str, str]:
    home_path = Path(home)
    for relative in (".config", ".local/share", ".local/state", ".cache"):
        (home_path / relative).mkdir(parents=True, exist_ok=True)
    overrides = {
        "HOME": str(home_path),
        "XDG_CONFIG_HOME": str(home_path / ".config"),
        "XDG_DATA_HOME": str(home_path / ".local" / "share"),
        "XDG_STATE_HOME": str(home_path / ".local" / "state"),
        "XDG_CACHE_HOME": str(home_path / ".cache"),
        "PATH": f"{Path(bin_dir)}:/usr/bin:/bin",
        "PYTHONPATH": str(HARNESS_DIR),
        "PYTHONUNBUFFERED": "1",
        "TERM": "xterm",
        "LANG": "C.UTF-8",
        "ACCEPTANCE_SANDBOX": "1",
        "ACCEPTANCE_NET_LOG": str(home_path / "net.log"),
        "UX_REPO_DIR": str(Path(repo_dir).resolve()),
    }
    return session_env(spec, server, overrides)


def _tail(text: str, count: int = 40) -> str:
    lines = strip_ansi(text).splitlines()
    return "\n".join(lines[-count:]) if lines else "(kein Mitschnitt)"


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _format_report(spec: UxSpec, repo: Path, rows: list[dict]) -> str:
    tool = (spec.meta or {}).get("tool", "?")
    ok = all(row["ok"] for row in rows)
    lines = [
        "# UX-Gate Bericht",
        "",
        f"- Tool: `{tool}`",
        f"- Repo: `{repo}`",
        f"- Ergebnis: {'PASS' if ok else 'FAIL'}",
        "",
        "| Sitzung | Lauf | Ergebnis | Befund |",
        "|---|---|---|---|",
    ]
    for row in rows:
        result = "PASS" if row["ok"] else "FAIL"
        reason = "; ".join(row.get("fails") or []) or ("OK" if row["ok"] else "")
        lines.append(
            f"| {_cell(row['title'])} | {_cell(row['run'])} | {result} | {_cell(reason)} |"
        )
    for row in rows:
        if row["ok"]:
            continue
        lines.extend(
            [
                "",
                f"## FAIL: {row['title']} – {row['run']}",
                "",
                "```text",
                _tail(row.get("transcript", "")),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def _scratch_dir() -> Path:
    path = Path.cwd() / "scratch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_report(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UX-Sitzungen im PTY prüfen")
    parser.add_argument("repo_dir")
    parser.add_argument("--venv", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)

    repo = Path(args.repo_dir).resolve()
    spec = parse(repo / "docs" / "UX.md")

    if spec.errors:
        rows = [
            {
                "title": "UX01",
                "run": "-",
                "ok": False,
                "fails": list(spec.errors),
                "transcript": "",
            }
        ]
        report = _format_report(spec, repo, rows)
        print(report, end="")
        _write_report(args.report, report)
        return 1

    tool = str((spec.meta or {}).get("tool", "")).strip()
    if not tool:
        rows = [
            {
                "title": "UX01",
                "run": "-",
                "ok": False,
                "fails": ["ux-meta.tool fehlt"],
                "transcript": "",
            }
        ]
        report = _format_report(spec, repo, rows)
        print(report, end="")
        _write_report(args.report, report)
        return 1

    venv = Path(args.venv).resolve() if args.venv else repo / "scratch" / "ux-venv"
    try:
        bin_dir = install_fresh(repo, venv, tool=tool)
    except Exception as exc:  # noqa: BLE001 - Fehler soll im Bericht landen
        rows = [
            {
                "title": "Installation",
                "run": "-",
                "ok": False,
                "fails": [str(exc)],
                "transcript": "",
            }
        ]
        report = _format_report(spec, repo, rows)
        print(report, end="")
        _write_report(args.report, report)
        return 1

    search_path = f"{bin_dir}:/usr/bin:/bin"
    if shutil.which(tool, path=search_path) is None:
        rows = [
            {
                "title": "Installation",
                "run": "-",
                "ok": False,
                "fails": ["Befehl nicht im PATH nach Installation"],
                "transcript": "",
            }
        ]
        report = _format_report(spec, repo, rows)
        print(report, end="")
        _write_report(args.report, report)
        return 1

    home = tempfile.mkdtemp(prefix="ux-home-", dir=_scratch_dir())
    env = build_env(spec, None, home, bin_dir, repo)
    port = free_local_port()
    server_factory = lambda: FakeServer(spec, repo, port=port)
    rows: list[dict] = []

    for session in spec.sessions:
        try:
            if is_write_session(session):
                check = check_write(spec, session, server_factory, env)
                for run in check.runs:
                    rows.append(
                        {
                            "title": session.title,
                            "run": run.run,
                            "ok": run.ok,
                            "fails": run.fails,
                            "transcript": run.transcript,
                        }
                    )
            else:
                with server_factory() as server:
                    result = run_session(
                        spec, session, server, env, run_label="1"
                    )
                rows.append(
                    {
                        "title": session.title,
                        "run": result.run,
                        "ok": result.ok,
                        "fails": result.fails,
                        "transcript": result.transcript,
                    }
                )
        except Exception as exc:  # noqa: BLE001 - Sitzungsfehler im Bericht
            rows.append(
                {
                    "title": session.title,
                    "run": "-",
                    "ok": False,
                    "fails": [f"{type(exc).__name__}: {exc}"],
                    "transcript": "",
                }
            )

    report = _format_report(spec, repo, rows)
    print(report, end="")
    _write_report(args.report, report)
    return 0 if rows and all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
