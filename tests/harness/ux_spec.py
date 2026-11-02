"""Parser für maschinenlesbare docs/UX.md-Dateien (nur Standardbibliothek)."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Step:
    kind: str
    text: str
    lineno: int


@dataclass
class Session:
    title: str
    steps: list[Step] = field(default_factory=list)


@dataclass
class FormStep:
    id: str
    method: str
    path: str
    sends: list[str] = field(default_factory=list)
    response: str = ""
    before_confirm: bool = False
    final: bool = False
    live: str = ""


@dataclass
class Route:
    method: str
    path: str
    response: str = ""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    query_contains: str | None = None


@dataclass
class UxSpec:
    meta: dict
    sessions: list[Session] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    formsteps: list[FormStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


FENCE_RE = re.compile(r"^\s*```\s*([^\s`]*)\s*$")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
INSTALL_RE = re.compile(r"^(?:pipx|pip)\s+install(?:\s|$)")
KNOWN_FENCES = {"ux-meta", "ux-session", "ux-routes", "ux-formsteps"}


def is_write_session(session: Session) -> bool:
    """True, wenn die Sitzung eine Bestätigungsfrage mit [j/N] enthält."""
    return any(
        step.kind in {"expect", "regex"} and "[j/N]" in step.text
        for step in session.steps
    )


def install_command(session: Session) -> str | None:
    """Erster Installationsbefehl (``$ pipx install …`` / ``$ pip install …``)."""
    for step in session.steps:
        if step.kind == "command" and INSTALL_RE.match(step.text.strip()):
            return step.text
    return None


def commands(session: Session) -> list[str]:
    """Alle ``$``-Befehle außer Installationsbefehlen, in Reihenfolge."""
    return [
        step.text
        for step in session.steps
        if step.kind == "command" and not INSTALL_RE.match(step.text.strip())
    ]


def field_matches(sends_entry: str, fieldnames: object) -> bool:
    """Prüft einen ``sends``-Eintrag; ein abschließendes ``*`` ist Präfix-Match."""
    names = {str(name) for name in fieldnames}  # type: ignore[union-attr]
    if sends_entry.endswith("*"):
        prefix = sends_entry[:-1]
        return any(name.startswith(prefix) for name in names)
    return sends_entry in names


def _blocks(lines: list[str]) -> list[tuple[str, int, list[tuple[int, str]], str]]:
    """Liefert (info, startzeile, [(zeilennr, text)], letzte_ueberschrift)."""
    result = []
    in_fence = False
    info = ""
    start = 0
    body: list[tuple[int, str]] = []
    heading = ""
    for lineno, line in enumerate(lines, start=1):
        if not in_fence:
            match = FENCE_RE.match(line)
            if match:
                in_fence = True
                info = match.group(1).strip()
                start = lineno
                body = []
                continue
            hmatch = HEADING_RE.match(line)
            if hmatch:
                heading = hmatch.group(2).strip()
            continue
        if FENCE_RE.match(line) and not line.strip().strip("`").strip():
            result.append((info, start, body, heading))
            in_fence = False
            info = ""
            body = []
            continue
        body.append((lineno, line))
    if in_fence:
        result.append((info, start, body, heading))
    return result


def _json_block(info: str, start: int, body: list[tuple[int, str]], errors: list[str]):
    raw = "\n".join(text for _, text in body)
    try:
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError as exc:
        errors.append(
            f"Zeile {start + exc.lineno}: kaputtes JSON in {info}: {exc.msg}"
        )
        return None


def _session_block(
    start: int, body: list[tuple[int, str]], title: str, errors: list[str]
) -> Session:
    session = Session(title=title)
    seen_command = False
    for lineno, line in body:
        if line.strip() == "":
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            errors.append(
                f"Zeile {lineno}: '#'-Zeile in ux-session ist nicht erlaubt"
            )
            continue
        if line.startswith("$ "):
            kind, text = "command", line[2:]
            seen_command = True
        elif line.startswith("> "):
            kind, text = "input", line[2:]
        elif line.startswith(">") and line.strip() == ">":
            kind, text = "input", ""
        elif line.startswith("<~ "):
            kind, text = "regex", line[3:]
        elif line.startswith("< "):
            kind, text = "expect", line[2:]
        elif line.startswith("! "):
            kind, text = "exit", line[2:]
        else:
            errors.append(f"Zeile {lineno}: unbekanntes Präfix: {stripped!r}")
            continue
        if kind == "input" and not seen_command:
            errors.append(
                f"Zeile {lineno}: Eingabe ohne vorherigen \"$\"-Befehl"
            )
        session.steps.append(Step(kind=kind, text=text, lineno=lineno))
    for index, step in enumerate(session.steps):
        if step.kind == "expect" and "[j/N]" in step.text:
            nxt = session.steps[index + 1] if index + 1 < len(session.steps) else None
            if nxt is None or nxt.kind != "input":
                errors.append(
                    f"Zeile {step.lineno}: nach \"[j/N]\" fehlt die direkt folgende Eingabe"
                )
    return session


def _parse_routes(data: object, start: int, repo_dir: Path, errors: list[str]) -> list[Route]:
    routes: list[Route] = []
    if not isinstance(data, list):
        errors.append(f"Zeile {start}: ux-routes muss eine JSON-Liste sein")
        return routes
    for item in data:
        if not isinstance(item, dict):
            errors.append(f"Zeile {start}: ux-routes-Eintrag ist kein Objekt")
            continue
        route = Route(
            method=str(item.get("method", "GET")),
            path=str(item.get("path", "")),
            response=str(item.get("response", "")),
            status=int(item.get("status", 200)),
            content_type=str(item.get("content_type", "text/html; charset=utf-8")),
            query_contains=item.get("query_contains"),
        )
        if route.response and not (repo_dir / route.response).is_file():
            errors.append(
                f"Zeile {start}: Response-Datei fehlt: {route.response} "
                f"(relativ zu {repo_dir})"
            )
        routes.append(route)
    return routes


def _parse_formsteps(
    data: object, start: int, repo_dir: Path, errors: list[str]
) -> list[FormStep]:
    formsteps: list[FormStep] = []
    if not isinstance(data, list):
        errors.append(f"Zeile {start}: ux-formsteps muss eine JSON-Liste sein")
        return formsteps
    for item in data:
        if not isinstance(item, dict):
            errors.append(f"Zeile {start}: ux-formsteps-Eintrag ist kein Objekt")
            continue
        step = FormStep(
            id=str(item.get("id", "")),
            method=str(item.get("method", "POST")),
            path=str(item.get("path", "")),
            sends=[str(name) for name in item.get("sends", [])],
            response=str(item.get("response", "")),
            before_confirm=bool(item.get("before_confirm", False)),
            final=bool(item.get("final", False)),
            live=str(item.get("live", "")),
        )
        if step.response and not (repo_dir / step.response).is_file():
            errors.append(
                f"Zeile {start}: Response-Datei fehlt: {step.response} "
                f"(relativ zu {repo_dir})"
            )
        formsteps.append(step)
    return formsteps


def parse(path: str | Path) -> UxSpec:
    """Liest eine UX.md und validiert sie. Fehler landen in ``spec.errors``."""
    ux_path = Path(path)
    errors: list[str] = []
    try:
        lines = ux_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return UxSpec(meta={}, errors=[f"Zeile 0: UX.md nicht lesbar: {exc}"])

    repo_dir = ux_path.resolve().parent.parent
    spec = UxSpec(meta={}, errors=errors)
    meta_seen = False
    meta_block_seen = False

    for info, start, body, heading in _blocks(lines):
        if info == "ux-meta":
            meta_block_seen = True
            data = _json_block(info, start, body, errors)
            if data is None:
                continue
            if not isinstance(data, dict):
                errors.append(f"Zeile {start}: ux-meta muss ein JSON-Objekt sein")
                continue
            spec.meta = data
            meta_seen = True
        elif info == "ux-session":
            spec.sessions.append(_session_block(start, body, heading, errors))
        elif info == "ux-routes":
            data = _json_block(info, start, body, errors)
            if data is not None:
                spec.routes.extend(_parse_routes(data, start, repo_dir, errors))
        elif info == "ux-formsteps":
            data = _json_block(info, start, body, errors)
            if data is not None:
                spec.formsteps.extend(_parse_formsteps(data, start, repo_dir, errors))

    if not meta_seen and not meta_block_seen:
        errors.append("Zeile 0: ux-meta fehlt")
    if spec.formsteps and not spec.meta.get("base_url_env"):
        errors.append(
            "Zeile 0: ux-formsteps vorhanden, aber ux-meta.base_url_env fehlt"
        )
    return spec


def summary(spec: UxSpec) -> str:
    tool = spec.meta.get("tool", "?") if spec.meta else "?"
    write = sum(1 for session in spec.sessions if is_write_session(session))
    lines = [
        f"tool: {tool}",
        f"sessions: {len(spec.sessions)} ({write} schreibend)",
        f"routes: {len(spec.routes)}",
        f"formsteps: {len(spec.formsteps)}",
        f"errors: {len(spec.errors)}",
    ]
    lines.extend(f"  - {error}" for error in spec.errors)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("Usage: python ux_spec.py <UX.md>", file=sys.stderr)
        return 2
    spec = parse(args[0])
    print(summary(spec))
    return 1 if spec.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
