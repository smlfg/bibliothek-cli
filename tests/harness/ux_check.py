#!/usr/bin/env python3
"""Maschinelles UX-Gate für CLIs (Prüfungen UX00–UX09 nach docs/FORMAT.md)."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    from fake_server import FakeServer
    from ux_session import (
        DEFAULT_TIMEOUT,
        PtySession,
        build_env,
        check_previous_form_fields,
        check_write,
        free_local_port,
        install_fresh,
        run_session,
        run_write_without_login,
        strip_ansi,
    )
    from ux_spec import (
        INSTALL_RE,
        UxSpec,
        commands,
        is_write_session,
        parse,
    )
except ImportError:  # pragma: no cover - Paketimport
    from .fake_server import FakeServer
    from .ux_session import (
        DEFAULT_TIMEOUT,
        PtySession,
        build_env,
        check_previous_form_fields,
        check_write,
        free_local_port,
        install_fresh,
        run_session,
        run_write_without_login,
        strip_ansi,
    )
    from .ux_spec import (
        INSTALL_RE,
        UxSpec,
        commands,
        is_write_session,
        parse,
    )

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
CRED_RE = re.compile(r"(PASS|PASSWORD|PASSWORT|TOKEN|SECRET|USER|LOGIN|EMAIL|MAIL)", re.I)
ENV_LITERAL_RE = re.compile(r'["\']([A-Z][A-Z0-9_]{2,})["\']')
TOOL_CALL_RE = re.compile(r'os\.environ\.get\(\s*["\']([^"\']+)["\']|os\.getenv\(\s*["\']([^"\']+)["\']|os\.environ\[\s*["\']([^"\']+)["\']\s*\]')
CHECK_IDS = ["UX00", "UX01", "UX02", "UX03", "UX04", "UX05", "UX06", "UX07", "UX08", "UX09"]


@dataclass
class CheckRow:
    id: str
    result: str
    befund: str
    details: str = ""


@dataclass
class Context:
    repo: Path
    spec: UxSpec
    tool: str
    bin_dir: Path | None = None
    env: dict[str, str] | None = None
    help_text: str = ""
    help_ok: bool = False
    help_error: str = ""
    subcommands: list[str] = field(default_factory=list)
    sub_help: dict[str, str] = field(default_factory=dict)
    servers: list = field(default_factory=list)
    ux05_transcripts: dict[str, str] = field(default_factory=dict)
    port: int = 0


def _row(rows: dict[str, CheckRow], cid: str, ok: bool, befund: str, details: str = "") -> None:
    rows[cid] = CheckRow(cid, PASS if ok else FAIL, befund or ("OK" if ok else "FAIL"), details)


def _skip(rows: dict[str, CheckRow], cid: str, befund: str) -> None:
    rows[cid] = CheckRow(cid, SKIP, befund)


def _run(cmd: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            env=env,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(cmd, 124, str(exc.stdout or "") + "\nTimeout nach 20 s")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, f"{type(exc).__name__}: {exc}")


def _usage_line(help_text: str) -> str:
    match = re.search(r"(?m)^\s*[Uu]sage:\s*(.*(?:\n[ \t]+.*)*)", help_text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _subcommands(help_text: str) -> list[str]:
    names: list[str] = []
    usage = _usage_line(help_text)
    tokens = usage.split()
    for index, token in enumerate(tokens):
        match = re.fullmatch(r"\{([^{}]+)\}", token.strip("[]"))
        if not match:
            continue
        previous = tokens[index - 1] if index else ""
        if previous.startswith("--") and not previous.endswith("]"):
            continue
        for part in match.group(1).split(","):
            part = part.strip()
            if re.fullmatch(r"[A-Za-z][\w-]*", part) and part not in names:
                names.append(part)
    positional = False
    metavar_header = False
    for line in help_text.splitlines():
        if re.match(r"^\s*(positional arguments|Positional Arguments)\s*:\s*$", line):
            positional = True
            metavar_header = False
            continue
        if not positional:
            continue
        match = re.match(r"^\s*\{([^{}]+)\}\s*$", line)
        if match:
            metavar_header = False
            for part in match.group(1).split(","):
                part = part.strip()
                if re.fullmatch(r"[A-Za-z][\w-]*", part) and part not in names:
                    names.append(part)
        elif re.match(r"^\s{2,}[A-Z][A-Z0-9_-]*\s*$", line):
            # argparse mit eigenem metavar ("SUBCOMMAND"/"ACTION"), darunter
            # eingerückte Unterkommandos mit Beschreibung (wg-gesucht-cli).
            metavar_header = True
        elif metavar_header:
            match = re.match(r"^\s{4,}([A-Za-z][\w-]*)\s{2,}\S", line)
            if match:
                if match.group(1) not in names:
                    names.append(match.group(1))
            elif re.match(r"^\S", line):
                positional = False
                metavar_header = False
        elif re.match(r"^\S", line):
            positional = False
    section = False
    for line in help_text.splitlines():
        if re.match(r"^\s*(Commands|Befehle)\s*:\s*$", line, re.I):
            section = True
            continue
        if not section:
            continue
        if not line.strip():
            if names:
                break
            continue
        match = re.match(r"^\s+([A-Za-z][\w-]*)\s{2,}\S", line)
        if match:
            if match.group(1) not in names:
                names.append(match.group(1))
        elif re.match(r"^\S", line):
            break
    return names


def _required_options(help_text: str) -> list[tuple[str, str]]:
    usage = _usage_line(help_text)
    stripped = re.sub(r"\[[^\[\]]*\]", " ", usage)
    stripped = re.sub(r"\[[^\[\]]*\]", " ", stripped)
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"(--[A-Za-z0-9][\w-]*)(?:[ =]([A-Z][A-Z0-9_-]*))?", stripped):
        option, value = match.group(1), match.group(2)
        if option not in [item[0] for item in found]:
            found.append((option, f"{option} {value}".strip()))
    for match in re.finditer(r"(--[A-Za-z0-9][\w-]*)[^\n]*\[required\]", help_text):
        if match.group(1) not in [item[0] for item in found]:
            found.append((match.group(1), match.group(1)))
    return found


def _source_env_names(repo: Path) -> set[str]:
    names: set[str] = set()
    src = repo / "src"
    if not src.is_dir():
        return names
    for path in sorted(src.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in TOOL_CALL_RE.finditer(text):
            value = next(group for group in match.groups() if group)
            names.add(value)
        if "os.environ" not in text and "getenv" not in text:
            continue
        for match in ENV_LITERAL_RE.finditer(text):
            literal = match.group(1)
            if CRED_RE.search(literal):
                names.add(literal)
    return names


def _check_ux01(rows: dict[str, CheckRow], spec: UxSpec) -> None:
    ux_path = Path("docs/UX.md")
    if spec.errors:
        _row(rows, "UX01", False, "; ".join(spec.errors))
        return
    if not spec.meta:
        _row(rows, "UX01", False, f"{ux_path} enthält keinen ux-meta-Block")
        return
    if len(spec.sessions) < 3:
        _row(rows, "UX01", False, f"nur {len(spec.sessions)} ux-session(s), mindestens 3 nötig")
        return
    write_sessions = [session for session in spec.sessions if is_write_session(session)]
    if write_sessions and not spec.formsteps:
        _row(rows, "UX01", False, "schreibende Sitzung mit [j/N], aber kein ux-formsteps")
        return
    if spec.formsteps and not write_sessions:
        _row(rows, "UX01", False, "ux-formsteps vorhanden, aber keine Sitzung mit [j/N]")
        return
    _row(rows, "UX01", True, f"{ux_path}: {len(spec.sessions)} Sitzungen, {len(spec.formsteps)} formsteps")


def _check_ux02(rows: dict[str, CheckRow], ctx: Context) -> None:
    source_names = _source_env_names(ctx.repo)
    cred_source = sorted(name for name in source_names if CRED_RE.search(name))
    meta_cred = [str(name) for name in (ctx.spec.meta or {}).get("credential_env", [])]
    if not cred_source and not meta_cred:
        _row(rows, "UX02", True, "keine Credential-Env-Variablen gefunden")
        return
    variables = sorted(set(cred_source) | set(meta_cred))
    if not ctx.help_ok:
        _row(rows, "UX02", False, f"Credential-Env {variables}, aber <tool> --help schlägt fehl")
        return
    if "login" not in ctx.subcommands:
        _row(
            rows,
            "UX02",
            False,
            f"Credential-Env {', '.join(variables)} vorhanden, aber `{ctx.tool} --help` "
            "listet kein Unterkommando `login`",
        )
        return
    _row(rows, "UX02", True, f"Credential-Env {', '.join(variables)} über `login`")


def _check_ux03_04(rows: dict[str, CheckRow], ctx: Context) -> None:
    if not ctx.help_ok:
        _row(rows, "UX03", False, f"`{ctx.tool} --help` Exit ≠ 0: {ctx.help_error}")
        _row(rows, "UX04", False, "Subkommando-Hilfe ohne funktionierende `--help` nicht prüfbar")
        return
    failures = []
    version = _run([ctx.tool, "--version"], ctx.env or {})
    if version.returncode != 0:
        failures.append(f"`{ctx.tool} --version` Exit {version.returncode}")
    for sub in ctx.subcommands:
        result = _run([ctx.tool, sub, "--help"], ctx.env or {})
        if result.returncode != 0:
            failures.append(f"`{ctx.tool} {sub} --help` Exit {result.returncode}")
    if failures:
        _row(rows, "UX03", False, "; ".join(failures))
    else:
        _row(rows, "UX03", True, f"--help, --version und {len(ctx.subcommands)} Unterkommandos mit Exit 0")

    allowed = {str(item) for item in (ctx.spec.meta or {}).get("required_options_ok", [])}
    problems = []
    for sub in ctx.subcommands:
        text = ctx.sub_help.get(sub, "")
        for option, display in _required_options(text):
            if option in allowed:
                continue
            usage = _usage_line(text)
            problems.append(
                f"`{ctx.tool} {sub}`: Pflicht-Option `{display}` außerhalb [...] "
                f"in `{usage}`; nicht in required_options_ok"
            )
    if problems:
        _row(rows, "UX04", False, "; ".join(problems))
    else:
        _row(rows, "UX04", True, f"{len(ctx.subcommands)} Unterkommandos ohne Pflicht-Option statt positional")


def _readme_quickstart(repo: Path) -> tuple[list[str], list[str]]:
    path = repo / "README.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], []
    heading_index = None
    level = 0
    for index, line in enumerate(lines[:40]):
        match = re.match(r"^\s{0,3}(#{2,3})\s+Schnellstart\b", line, re.I)
        if match:
            heading_index = index
            level = len(match.group(1))
            break
    if heading_index is None:
        return [], []
    blocks: list[str] = []
    block: list[str] | None = None
    for line in lines[heading_index + 1:]:
        if block is None:
            hmatch = re.match(r"^\s{0,3}(#{1,6})\s+", line)
            if hmatch and len(hmatch.group(1)) <= level:
                break
            if line.strip().startswith("```"):
                block = []
            continue
        if line.strip().startswith("```"):
            blocks.extend(block)
            block = None
            continue
        block.append(line)
    if block is not None:
        blocks.extend(block)
    return blocks, lines


def _check_ux06(rows: dict[str, CheckRow], ctx: Context) -> None:
    repo = ctx.repo
    readme = repo / "README.md"
    if not readme.is_file():
        _row(rows, "UX06", False, "README.md fehlt")
        return
    blocks, lines = _readme_quickstart(repo)
    if not blocks:
        _row(rows, "UX06", False, "README.md hat keine Überschrift „Schnellstart“ (##/###) in den ersten 40 Zeilen oder keinen Code-Block")
        return
    tool = ctx.tool
    install = str((ctx.spec.meta or {}).get("install", "")).strip()
    session_commands = []
    for session in ctx.spec.sessions:
        session_commands.extend(value.strip() for value in commands(session))
    normalized_sessions = {re.sub(r"\s+", " ", value).strip() for value in session_commands}
    problems = []
    install_lines = []
    tool_calls = []
    for raw in blocks:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            problems.append(f"Code-Zeile beginnt mit '#': {line!r}")
            continue
        if line.startswith("$ "):
            problems.append(f"Code-Zeile beginnt mit '$ ': {line!r}")
            continue
        if re.search(r"<[^>]+>", line):
            problems.append(f"Platzhalter in spitzen Klammern: {line!r}")
        first = line.split(None, 1)[0]
        if INSTALL_RE.match(line):
            install_lines.append(re.sub(r"\s+", " ", line).strip())
        elif first in {"pipx", "pip", "export", tool}:
            if first == tool:
                tool_calls.append(re.sub(r"\s+", " ", line).strip())
        else:
            problems.append(f"Code-Zeile beginnt nicht mit pipx/pip/{tool}/export: {line!r}")
    if not install_lines:
        problems.append("keine pipx/pip-Installationszeile im Schnellstart")
    normalized_install = re.sub(r"\s+", " ", install).strip()
    for line in install_lines:
        if not normalized_install or line != normalized_install:
            problems.append(f"Installationszeile {line!r} passt nicht zu ux-meta.install {install!r}")
    for line in tool_calls:
        if line not in normalized_sessions:
            problems.append(f"Tool-Befehl {line!r} fehlt als \"$ \"-Zeile in einer ux-session")
    if problems:
        _row(rows, "UX06", False, "; ".join(problems))
        return
    _row(rows, "UX06", True, f"Schnellstart: {len(tool_calls)} Tool-Befehle, Installation passt")


def _new_server(ctx: Context) -> FakeServer:
    server = FakeServer(ctx.spec, ctx.repo, port=ctx.port)
    ctx.servers.append(server)
    return server


def _json_or_traceback(text: str) -> list[str]:
    problems = []
    clean = strip_ansi(text)
    if "Traceback (most recent call last)" in clean:
        problems.append("Traceback (most recent call last) im Terminal")
    for number, line in enumerate(clean.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("{") or stripped.startswith("[{"):
            problems.append(f"Zeile {number}: JSON im Terminal: {stripped[:120]}")
            break
    return problems


def _check_ux05(rows: dict[str, CheckRow], ctx: Context) -> None:
    problems = []
    transcripts = []
    for session in ctx.spec.sessions:
        with _new_server(ctx) as server:
            result = run_session(ctx.spec, session, server, ctx.env or {}, run_label="UX05")
        ctx.ux05_transcripts[session.title] = result.transcript
        command = next(iter(commands(session)), "(mehrere Befehle)")
        for problem in _json_or_traceback(result.transcript):
            problems.append(f"`{command}` (Sitzung {session.title!r}): {problem}")
        transcripts.append(f"## {session.title}\n" + _tail(result.transcript, 30))
    if ctx.help_ok and "login" in ctx.subcommands:
        with _new_server(ctx) as server:
            login_env = dict(ctx.env or {})
            base = (ctx.spec.meta or {}).get("base_url_env")
            if base:
                login_env[str(base)] = server.base_url
            proc = PtySession(["/bin/sh", "-c", f"{ctx.tool} login"], env=login_env, cwd=ctx.repo)
            proc.send_eof()
            proc.wait_exit(DEFAULT_TIMEOUT)
            login_text = proc.transcript
            proc.close()
        for problem in _json_or_traceback(login_text):
            if "Traceback" in problem:
                problems.append(f"`{ctx.tool} login` + strg+D: {problem}")
        transcripts.append("## login + strg+D\n" + _tail(login_text, 20))
    if problems:
        _row(rows, "UX05", False, "; ".join(problems), "\n\n".join(transcripts))
    else:
        _row(rows, "UX05", True, f"{len(ctx.spec.sessions)} Sitzungen ohne JSON/Traceback im TTY")


def _check_ux07_08(rows: dict[str, CheckRow], ctx: Context) -> None:
    write_sessions = [session for session in ctx.spec.sessions if is_write_session(session)]
    if not ctx.spec.formsteps:
        _row(rows, "UX07", True, "keine ux-formsteps, keine schreibende Aktion")
        _row(rows, "UX08", True, "keine ux-formsteps, keine schreibende Aktion")
        return
    if not write_sessions:
        _row(rows, "UX07", False, "ux-formsteps vorhanden, aber keine Sitzung enthält „< [j/N]“")
        _row(rows, "UX08", False, "keine schreibende Sitzung zum Ausführen der formsteps")
        return

    ux07_problems = []
    ux08_problems = []
    details = []
    for session in write_sessions:
        transcript = strip_ansi(ctx.ux05_transcripts.get(session.title, ""))
        if transcript and "[j/N]" not in transcript:
            command = next(iter(commands(session)), "(Befehl)")
            ux07_problems.append(
                f"`{command}` (Sitzung {session.title!r}): [j/N] wurde im TTY nicht ausgegeben "
                "(CLI verlangt offenbar eine andere Bestätigung, z. B. --confirm)"
            )
        check = check_write(ctx.spec, session, lambda: _new_server(ctx), ctx.env or {})
        for failure in check.runs[0].fails:
            if "ohne before_confirm gesendet" in failure:
                ux07_problems.append(f"Sitzung {session.title!r} (Lauf N): {failure}")
        for failure in check.runs[1].fails:
            if "vor der [j/N]-Frage gesendet" in failure:
                ux07_problems.append(f"Sitzung {session.title!r} (Lauf j): {failure}")
            else:
                ux08_problems.append(f"Sitzung {session.title!r} (Lauf j): {failure}")
        details.append(
            f"## {session.title}\n"
            + "\n".join(f"- {failure}" for failure in check.fails)
        )

    if ux07_problems:
        _row(rows, "UX07", False, "; ".join(ux07_problems), "\n\n".join(details))
    else:
        _row(rows, "UX07", True, f"{len(write_sessions)} schreibende Sitzung(en) mit [j/N]")
    if ux08_problems:
        _row(rows, "UX08", False, "; ".join(ux08_problems), "\n\n".join(details))
    else:
        _row(rows, "UX08", True, "alle formsteps in Reihenfolge und mit allen Feldern gesendet")


def _env_without_credentials(spec: UxSpec, env: dict[str, str] | None) -> dict[str, str]:
    cleaned = dict(env or {})
    for name in (spec.meta or {}).get("credential_env", []):
        cleaned.pop(str(name), None)
    return cleaned


def _fresh_env(ctx: Context) -> dict[str, str]:
    home = tempfile.mkdtemp(prefix="ux09-home-", dir=_scratch_tmp())
    env = build_env(ctx.spec, None, home, ctx.bin_dir, ctx.repo)
    return _env_without_credentials(ctx.spec, env)


def _login_session(ctx: Context):
    pattern = re.compile(rf"^\s*{re.escape(ctx.tool)}\s+login\s*$")
    for session in ctx.spec.sessions:
        if any(pattern.match(command.strip()) for command in commands(session)):
            return session
    return None


def _check_ux09(rows: dict[str, CheckRow], ctx: Context) -> None:
    write_sessions = [
        session for session in ctx.spec.sessions if is_write_session(session)
    ]
    if not write_sessions:
        _skip(rows, "UX09", "keine schreibende Sitzung")
        return

    problems: list[str] = []
    details: list[str] = []
    login_session = _login_session(ctx)
    for session in write_sessions:
        env_a = _fresh_env(ctx)
        with _new_server(ctx) as server:
            fresh = run_write_without_login(
                ctx.spec, session, server, env_a, ctx.tool
            )
        problems.extend(
            f"(a) Sitzung {session.title!r}: {failure}"
            for failure in fresh.fails
        )
        details.append(
            f"## {session.title} – UX09a\n"
            + "\n".join(f"- {failure}" for failure in fresh.fails)
            + "\n\n```text\n"
            + _tail(fresh.transcript, 20)
            + "\n```"
        )

        env_b = _fresh_env(ctx)
        if login_session is not None:
            with _new_server(ctx) as server:
                run_session(
                    ctx.spec, login_session, server, env_b, run_label="UX09b-login"
                )
        with _new_server(ctx) as server:
            run_session(ctx.spec, session, server, env_b, run_label="UX09b")
            form_fails = check_previous_form_fields(
                ctx.spec, ctx.repo, server.sent_formsteps()
            )
        problems.extend(
            f"(b) Sitzung {session.title!r}: {failure}"
            for failure in form_fails
        )
        details.append(
            f"## {session.title} – UX09b\n"
            + ("\n".join(f"- {failure}" for failure in form_fails) or "- OK")
        )

    if problems:
        _row(rows, "UX09", False, "; ".join(problems), "\n\n".join(details))
    else:
        _row(
            rows,
            "UX09",
            True,
            f"{len(write_sessions)} schreibende Sitzung(en): Voraussetzungen vor "
            "[j/N] und Login-Felder vollständig",
        )


def _check_ux00(rows: dict[str, CheckRow], ctx: Context) -> None:
    if not ctx.spec.routes and not ctx.spec.formsteps:
        _row(rows, "UX00", True, "keine ux-routes/ux-formsteps, kein Fake-Server nötig")
        return
    requests = sum(len(server.requests) for server in ctx.servers)
    log_path = Path((ctx.env or {}).get("ACCEPTANCE_NET_LOG", ""))
    foreign = []
    if log_path.is_file():
        try:
            foreign = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            foreign = []
    if foreign:
        _row(
            rows,
            "UX00",
            False,
            "Sandbox protokolliert Verbindungsversuch zu fremdem Host: " + "; ".join(foreign[:5]),
        )
        return
    if requests == 0:
        _row(
            rows,
            "UX00",
            False,
            "base_url_env wirkt nicht – Tool ist gegen den Fake-Server nicht testbar "
            "(kein Request während aller Sitzungen)",
        )
        return
    _row(rows, "UX00", True, f"{requests} Request(s) am Fake-Server, keine Fremdverbindung")


def _tail(text: str, count: int = 40) -> str:
    lines = strip_ansi(text).splitlines()
    return "\n".join(lines[-count:]) if lines else "(kein Mitschnitt)"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _format_report(rows: dict[str, CheckRow], ctx: Context, mode: str) -> str:
    ordered = [rows[cid] for cid in CHECK_IDS if cid in rows]
    failed = any(row.result == FAIL for row in ordered)
    lines = [
        "# UX-Gate Bericht",
        "",
        f"- Repo: `{ctx.repo}`",
        f"- Tool: `{ctx.tool or '?'}`",
        f"- Modus: {mode}",
        f"- Ergebnis: {FAIL if failed else PASS}",
        "",
        "| ID | Ergebnis | Befund |",
        "|---|---|---|",
    ]
    for row in ordered:
        lines.append(f"| {row.id} | {row.result} | {_cell(row.befund)} |")
    details = [row for row in ordered if row.details and row.result == FAIL]
    if details:
        lines.extend(["", "## Details"])
        for row in details:
            lines.extend(["", f"### {row.id} – {row.result}", "", f"{row.befund}", "", "```text", _tail(row.details, 60), "```"])
    return "\n".join(lines) + "\n"


def _scratch_tmp() -> Path:
    path = Path.cwd() / "scratch" / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _spec_only(rows: dict[str, CheckRow], ctx: Context) -> None:
    _check_ux01(rows, ctx.spec)
    if ctx.tool:
        _check_ux06(rows, ctx)
    else:
        _skip(rows, "UX06", "kein ux-meta.tool, README-Schnellstart nicht prüfbar")
    if ctx.spec.formsteps:
        write_sessions = [session for session in ctx.spec.sessions if is_write_session(session)]
        if write_sessions:
            _row(rows, "UX07", True, f"{len(write_sessions)} schreibende Sitzung(en) mit [j/N]")
        else:
            _row(rows, "UX07", False, "ux-formsteps vorhanden, aber keine Sitzung enthält „< [j/N]“")
    else:
        _row(rows, "UX07", True, "keine ux-formsteps, keine schreibende Aktion")
    for cid in ("UX00", "UX02", "UX03", "UX04", "UX05", "UX08", "UX09"):
        _skip(rows, cid, "übersprungen wegen --spec-only")


def main(argv: list[str] | None = None) -> int:
    usx = argparse.ArgumentParser(description="UX-Gate für CLIs")
    usx.add_argument("repo_dir")
    usx.add_argument("--venv", default=None)
    usx.add_argument("--report", default=None)
    usx.add_argument("--spec-only", action="store_true")
    args = usx.parse_args(argv)

    repo = Path(args.repo_dir).resolve()
    spec = parse(repo / "docs" / "UX.md")
    tool = str((spec.meta or {}).get("tool", "")).strip()
    ctx = Context(repo=repo, spec=spec, tool=tool)
    rows: dict[str, CheckRow] = {}

    if args.spec_only:
        _spec_only(rows, ctx)
        report = _format_report(rows, ctx, "spec-only")
        print(report, end="")
        if args.report:
            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report, encoding="utf-8")
        return 0 if not any(row.result == FAIL for row in rows.values()) else 1

    _check_ux01(rows, spec)
    if spec.errors or not spec.meta or not tool:
        for cid in CHECK_IDS:
            if cid not in rows:
                _skip(rows, cid, "UX01 fehlgeschlagen, Prüfung nicht möglich")
        report = _format_report(rows, ctx, "voll")
        print(report, end="")
        if args.report:
            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report, encoding="utf-8")
        return 1

    venv = Path(args.venv).resolve() if args.venv else repo / "scratch" / "ux-venv"
    try:
        bin_dir = install_fresh(repo, venv, tool=tool)
    except Exception as exc:  # noqa: BLE001 - Fehler landet im Bericht
        _row(rows, "UX02", False, f"Installation fehlgeschlagen: {exc}")
        for cid in CHECK_IDS:
            if cid not in rows:
                _skip(rows, cid, "Installation fehlgeschlagen")
        report = _format_report(rows, ctx, "voll")
        print(report, end="")
        if args.report:
            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(report, encoding="utf-8")
        return 1

    home = tempfile.mkdtemp(prefix="ux-check-home-", dir=_scratch_tmp())
    ctx.port = free_local_port()
    ctx.bin_dir = bin_dir
    ctx.env = build_env(spec, None, home, bin_dir, repo)
    help_result = _run([tool, "--help"], ctx.env, cwd=repo)
    ctx.help_text = help_result.stdout or ""
    ctx.help_ok = help_result.returncode == 0
    ctx.help_error = _tail(help_result.stdout or "", 10)
    ctx.subcommands = _subcommands(ctx.help_text) if ctx.help_ok else []
    for sub in ctx.subcommands:
        ctx.sub_help[sub] = _run([tool, sub, "--help"], ctx.env, cwd=repo).stdout or ""

    _check_ux02(rows, ctx)
    _check_ux03_04(rows, ctx)
    _check_ux05(rows, ctx)
    _check_ux06(rows, ctx)
    _check_ux07_08(rows, ctx)
    _check_ux09(rows, ctx)
    _check_ux00(rows, ctx)

    ux00 = rows.get("UX00")
    if ux00 is not None and ux00.result == FAIL:
        for cid in ("UX05", "UX08"):
            row = rows.get(cid)
            if row is None:
                continue
            if row.result == PASS:
                row.result = FAIL
                row.befund = "Folgefehler von UX00: keine Sitzung hat den Fake-Server erreicht"
            elif row.result == FAIL:
                row.befund = "Folgefehler von UX00: " + row.befund

    report = _format_report(rows, ctx, "voll")
    print(report, end="")
    if args.report:
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
    return 0 if not any(row.result == FAIL for row in rows.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
