"""CLI-Entry – argparse-Definition, Handler, JSON-Output zentral."""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import logging
import os
import sys
import traceback
from typing import Any, Callable

from . import __version__
from . import http as http_mod

LOG = logging.getLogger("bibliothek_cli")


# ---------- Helpers ----------

def _stdout_is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def _human_output(as_json: bool) -> bool:
    """Menschen-Ausgabe nur im Terminal und ohne --json."""
    return not as_json and _stdout_is_tty()


def emit(
    data: dict[str, Any],
    as_json: bool,
    *,
    render: Callable[[dict[str, Any]], str] | None = None,
) -> int:
    """Zentrale Ausgabe: JSON bei Pipe/--json, Text im Terminal."""
    if _human_output(as_json) and render is not None:
        text = render(data)
        if text:
            sys.stdout.write(text + "\n")
        return 0
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return 0


def fail(code: int, msg: str, *, as_json: bool, kind: str = "error") -> int:
    """Saubere Fehlerausgabe: bei --json ein Error-Objekt."""
    payload = {"error": {"kind": kind, "code": code, "message": msg}}
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stderr.write(f"[{kind}] exit {code}: {msg}\n")
    return code


# ---------- Locations (statisch) ----------

_LOCATIONS = [
    {
        "code": "HN",
        "name": "Bibliothek Bildungscampus Heilbronn",
        "address": "Bildungscampus 1, 74076 Heilbronn",
        "url": "https://www.bib.hn",
    },
    {
        "code": "SN",
        "name": "Standort Sontheim",
        "address": "Lange Str. 11, 74081 Heilbronn-Sontheim",
        "url": "https://www.bib.hn",
    },
    {
        "code": "KU",
        "name": "Standort Künzelsau",
        "address": "Reinhold-Würth-Hochschule, 74653 Künzelsau",
        "url": "https://www.bib.hn",
    },
    {
        "code": "SHA",
        "name": "Standort Schwäbisch Hall",
        "address": "Hochschule Heilbronn, Campus Schwäbisch Hall",
        "url": "https://www.bib.hn",
    },
]


def _render_locations(data: dict[str, Any]) -> str:
    locations = data.get("locations") or []
    if not locations:
        return "Keine Standorte hinterlegt."
    lines = []
    for loc in locations:
        line = f"[{loc.get('code', '?')}] {loc.get('name', '')}".rstrip()
        if loc.get("address"):
            line += f" – {loc['address']}"
        if loc.get("url"):
            line += f" ({loc['url']})"
        lines.append(line)
    return "\n".join(lines)


def cmd_locations(args: argparse.Namespace, as_json: bool) -> int:
    return emit(
        {"locations": _LOCATIONS},
        as_json=as_json,
        render=_render_locations,
    )


# ---------- Human-readable renderers ----------

def _render_search(data: dict[str, Any]) -> str:
    results = data.get("results") or []
    query = data.get("query", "")
    if not results:
        return f"Keine Treffer für „{query}“."
    lines = [f"Treffer: {data.get('total_found', 0)} (angezeigt: {len(results)})"]
    for index, item in enumerate(results, 1):
        line = f"[{index}] {item.get('title') or '(ohne Titel)'}"
        if item.get("author"):
            line += f" – {item['author']}"
        if item.get("year"):
            line += f" ({item['year']})"
        location = item.get("location") or item.get("signature")
        if location:
            line += f" | {location}"
        if item.get("available") is True:
            line += " | verfügbar"
        elif item.get("available") is False:
            line += " | ausgeliehen"
        elif item.get("status"):
            line += f" | {item['status']}"
        if item.get("id"):
            line += f" | ID {item['id']}"
        lines.append(line)
    return "\n".join(lines)


def _render_show(data: dict[str, Any]) -> str:
    lines = []
    if data.get("title"):
        lines.append(f"Titel: {data['title']}")
    authors = data.get("authors") or []
    if authors:
        lines.append(f"Autor: {', '.join(authors)}")
    if data.get("year"):
        lines.append(f"Jahr: {data['year']}")
    if data.get("signature"):
        lines.append(f"Signatur: {data['signature']}")
    if data.get("media_type"):
        lines.append(f"Medientyp: {data['media_type']}")
    locations = data.get("locations") or []
    if locations:
        lines.append("Standorte:")
        for loc in locations:
            lines.append(f"  - {loc}")
    if data.get("id"):
        lines.append(f"ID: {data['id']}")
    if data.get("note"):
        lines.append(f"Hinweis: {data['note']}")
    return "\n".join(lines) or "Kein Datensatz gefunden."


def _render_watch(data: dict[str, Any]) -> str:
    if "items" in data:
        items = data.get("items") or []
        if not items:
            return "Keine Watch-Einträge."
        lines = []
        for index, item in enumerate(items, 1):
            line = f"[{index}] {item.get('query', '?')} (Limit {item.get('limit', '?')})"
            if item.get("id"):
                line += f" | ID {item['id']}"
            lines.append(line)
        return "\n".join(lines)
    if data.get("removed"):
        return f"Watch {data.get('id', '?')} entfernt."
    if data.get("noop"):
        return f"Watch {data.get('id', '?')} war nicht vorhanden."
    if data.get("query"):
        return f"Watch angelegt: {data['query']} | ID {data.get('id', '?')}"
    return data.get("hint", "")


def _render_login(data: dict[str, Any]) -> str:
    note = " (Mock-Session)" if data.get("mock") else ""
    return f"Login ok als {data.get('user', '?')}{note}."


def _render_logout(data: dict[str, Any]) -> str:
    return "Session gelöscht." if data.get("existed") else "Keine Session vorhanden."


def _render_loans(data: dict[str, Any]) -> str:
    loans = data.get("loans") or []
    if not loans:
        return "Keine Ausleihen."
    lines = []
    for index, loan in enumerate(loans, 1):
        line = f"[{index}] {loan.get('title') or '(ohne Titel)'}"
        if loan.get("id"):
            line += f" | ID {loan['id']}"
        if loan.get("due"):
            line += f" | fällig {loan['due']}"
        if loan.get("renewals") is not None:
            line += f" | {loan['renewals']} Verlängerungen"
        if loan.get("can_renew") is True:
            line += " | verlängerbar"
        elif loan.get("can_renew") is False:
            line += " | nicht verlängerbar"
        lines.append(line)
    return "\n".join(lines)


def _render_renew(data: dict[str, Any]) -> str:
    return (
        f"Verlängert: {data.get('id', '?')} – "
        f"neues Fälligkeitsdatum {data.get('new_due', '?')}."
    )


# ---------- Search ----------

def handle_search(args: argparse.Namespace, as_json: bool) -> int:
    query = (args.query or "").strip()
    if not query:
        return fail(
            1,
            "Suchbegriff darf nicht leer sein.",
            as_json=as_json,
            kind="usage",
        )
    try:
        result = http_mod.search(
            query,
            base_url=os.environ.get("BIBLIOTHEK_BASE_URL", http_mod.DEFAULT_BASE),
            media=args.media,
            available_only=args.available,
            limit=args.limit,
        )
    except ValueError as e:
        return fail(1, str(e), as_json=as_json, kind="usage")
    except http_mod.ParseError as e:
        return fail(4, str(e), as_json=as_json, kind="parse")
    except http_mod.HttpError as e:
        return fail(3, str(e), as_json=as_json, kind="network")
    return emit(result, as_json=as_json, render=_render_search)


# ---------- Show ----------

def handle_show(args: argparse.Namespace, as_json: bool) -> int:
    """Liefert den Detaildatensatz.

    aDISWeb stellt eine echte Detailseite nur über JS bereit (submitLink). Aus
    der Trefferliste haben wir den Datensatz bereits geparst. Hier machen wir
    eine zweite Suche mit exakter ID, was aktuell die Trefferliste zurückliefert.
    In einer zukünftigen Version kann die Vollanzeige (mit Standort/
    Verfügbarkeit) per Playwright nachgeladen werden.
    """
    rec = args.record.strip()
    if rec.startswith("http"):
        # ID aus URL extrahieren
        import re as _re
        m = _re.search(r"(AK[A-Z0-9]+)", rec)
        rec_id = m.group(1) if m else rec
    else:
        rec_id = rec
    try:
        # Wir laden einmal die Suche mit limit = 5 und markieren, wenn der Datensatz
        # dabei ist. Für die Vollanzeige reicht das hier aus.
        hits = http_mod.search(
            rec_id,
            limit=5,
        )
    except http_mod.HttpError as e:
        return fail(3, str(e), as_json=as_json, kind="network")
    except http_mod.ParseError as e:
        return fail(4, str(e), as_json=as_json, kind="parse")

    record = None
    for r in hits["results"]:
        if r["id"].upper() == rec_id.upper():
            record = r
            break
    if record is None:
        return fail(
            4,
            f"Datensatz {rec_id} nicht in erster Anzeige; Vollanzeite via "
            "Playwright in einer Folgeversion.",
            as_json=as_json,
            kind="parse",
        )
    return emit(
        {
            "id": record["id"],
            "title": record["title"],
            "authors": [record["author"]] if record["author"] else [],
            "year": record["year"],
            "signature": record["signature"],
            "media_type": record["media_type"],
            "locations": [],  # Vollanzeite benötigt Playwright
            "note": (
                "Vollanzeite mit Standortdetails benötigt eine "
                "JS-gesteuerte Detailansicht. Diese Version liefert die "
                "Metadaten aus der Trefferliste."
            ),
        },
        as_json=as_json,
        render=_render_show,
    )


# ---------- Watch ----------

def _watch_path() -> str:
    base = os.environ.get(
        "BIBLIOTHEK_CONFIG",
        os.path.join(
            os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
            "bibliothek-cli",
        ),
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "watch.json")


def _load_watch() -> dict[str, dict]:
    path = _watch_path()
    if not os.path.exists(path):
        return {}
    try:
        return json.loads(open(path, encoding="utf-8").read() or "{}")
    except json.JSONDecodeError:
        return {}


def _save_watch(data: dict[str, dict]) -> None:
    path = _watch_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cmd_watch(args: argparse.Namespace, as_json: bool) -> int:
    sub = getattr(args, "watch_cmd", None)
    items = _load_watch()
    if sub is None:
        return emit(
            {
                "hint": "watch add QUERY [--limit N] | watch list | watch remove ID",
                "items": list(items.values()),
            },
            as_json=as_json,
            render=_render_watch,
        )
    if sub == "list":
        return emit(
            {"items": list(items.values())},
            as_json=as_json,
            render=_render_watch,
        )
    if sub == "remove":
        if args.id not in items:
            return emit(
                {"noop": True, "id": args.id},
                as_json=as_json,
                render=_render_watch,
            )
        del items[args.id]
        _save_watch(items)
        return emit(
            {"removed": True, "id": args.id},
            as_json=as_json,
            render=_render_watch,
        )
    if sub == "add":
        import hashlib as _hl
        import datetime as _dt

        key = args.query + str(args.limit)
        wid = _hl.sha1(key.encode()).hexdigest()[:8]
        items[wid] = {
            "id": wid,
            "query": args.query,
            "limit": args.limit,
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }
        _save_watch(items)
        return emit(items[wid], as_json=as_json, render=_render_watch)
    return fail(1, f"unknown watch subcommand: {sub}", as_json=as_json)


# ---------- Auth / Loans ----------

def _session_path() -> str:
    base = os.environ.get(
        "BIBLIOTHEK_CONFIG",
        os.path.join(
            os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
            "bibliothek-cli",
        ),
    )
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "session.json")


_LOGIN_MISSING = (
    "Login fehlt: `bibliothek login` im Terminal ausführen oder "
    "BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD setzen"
)


def _cancelled(as_json: bool) -> int:
    if as_json:
        return fail(1, "Abgebrochen.", as_json=True, kind="cancelled")
    sys.stderr.write("Abgebrochen.\n")
    return 1


def _ask(prompt: str) -> str:
    """Liest eine Eingabe, gibt den Prompt aber auf stderr aus."""
    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        return input(prompt)
    finally:
        sys.stdout = out


def cmd_login(args: argparse.Namespace, as_json: bool) -> int:
    """Login per Env oder interaktiv im Terminal.

    BIBLIOTHEK_USER und BIBLIOTHEK_PASSWORD haben Vorrang. Fehlende Werte
    werden nur dann interaktiv abgefragt, wenn stdin ein Terminal ist.
    """
    user = os.environ.get("BIBLIOTHEK_USER")
    pw = os.environ.get("BIBLIOTHEK_PASSWORD")
    if not user or not pw:
        if not _stdin_is_tty():
            return fail(2, _LOGIN_MISSING, as_json=as_json, kind="auth")
        try:
            if not user:
                user = _ask("Benutzernummer: ").strip()
            if not pw:
                pw = getpass.getpass("Passwort: ")
        except (EOFError, KeyboardInterrupt):
            return _cancelled(as_json)
    if not user or not pw:
        return fail(
            2,
            "Login unvollständig: Benutzernummer und Passwort erforderlich.",
            as_json=as_json,
            kind="auth",
        )
    try:
        auth = http_mod.login_session(
            user,
            pw,
            base_url=os.environ.get("BIBLIOTHEK_BASE_URL", http_mod.DEFAULT_BASE),
        )
    except http_mod.HttpError as e:
        return fail(3, str(e), as_json=as_json, kind="network")
    sess = {
        "user": user,
        "cookies": auth.get("cookies", {}),
        "established_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mock": bool(auth.get("mock", False)),
    }
    path = _session_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return emit(
        {
            "login": "ok",
            "user": user,
            "mock": sess["mock"],
            "note": "Mock-Session; ohne Live-Backend.",
        },
        as_json=as_json,
        render=_render_login,
    )


def cmd_logout(args: argparse.Namespace, as_json: bool) -> int:
    path = _session_path()
    removed = False
    if os.path.exists(path):
        os.remove(path)
        removed = True
    return emit(
        {"removed": True, "existed": removed},
        as_json=as_json,
        render=_render_logout,
    )


def cmd_loans(args: argparse.Namespace, as_json: bool) -> int:
    sub = getattr(args, "loans_cmd", None)
    if sub is None or sub == "list":
        path = _session_path()
        if not os.path.exists(path):
            return fail(
                2,
                "Keine Session. Erst `bibliothek login` mit gültigen "
                "BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD ausführen.",
                as_json=as_json,
                kind="auth",
            )
        sess = json.loads(open(path, encoding="utf-8").read() or "{}")
        if sess.get("mock"):
            # Mock-Ausleihen
            return emit(
                {
                    "loans": [
                        {
                            "id": "MOCK-1",
                            "title": "Beispiel-Ausleihe (Mock)",
                            "due": "2026-11-01",
                            "renewals": 0,
                            "can_renew": True,
                        }
                    ],
                    "mock": True,
                },
                as_json=as_json,
                render=_render_loans,
            )
        return fail(
            4,
            "Live-Session, aber kein Backend-Parser vorhanden.",
            as_json=as_json,
            kind="parse",
        )
    if sub == "renew":
        if not args.confirm:
            return fail(
                5,
                "Verlängerung verlangt --confirm; keine Aktion ausgeführt.",
                as_json=as_json,
                kind="confirm_required",
            )
        if not os.path.exists(_session_path()):
            return fail(2, "Keine Session.", as_json=as_json, kind="auth")
        # Mock: ohne echtes Backend keine echte Verlängerung
        return emit(
            {
                "id": args.loan_id,
                "renewed": True,
                "new_due": "2026-11-15",
                "mock": True,
            },
            as_json=as_json,
            render=_render_renew,
        )
    return fail(1, f"unknown loans subcommand: {sub}", as_json=as_json)


# ---------- Parser ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibliothek",
        description=(
            "bibliothek – CLI für den LIV-Bibliothekskatalog "
            "(BSZ aDISWeb). Suche, Details, Watch, Login, Ausleihen."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Genau ein JSON-Objekt auf stdout; Logs/Prompts auf stderr.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="INFO-Logs auf stderr anzeigen (Default: nur Warnungen).",
    )

    sub_p = parser.add_subparsers(dest="cmd", required=False)

    # search
    p_search = sub_p.add_parser(
        "search",
        help="Katalog durchsuchen",
        description=(
            "Katalog durchsuchen. Im Terminal lesbare Trefferliste, "
            "bei Pipe oder --json JSON."
        ),
    )
    p_search.add_argument("query", help="Suchbegriff")
    p_search.add_argument("--media", choices=["book", "ebook", "all"], default="all")
    p_search.add_argument("--available", action="store_true")
    p_search.add_argument("--limit", type=int, default=20)

    # show
    p_show = sub_p.add_parser(
        "show",
        help="Titeldetails / Verfügbarkeit",
        description=(
            "Titeldetails anzeigen. Im Terminal lesbare Felder, "
            "bei Pipe oder --json JSON."
        ),
    )
    p_show.add_argument("record", help="Record-ID oder Detail-URL")

    # locations
    sub_p.add_parser(
        "locations",
        help="Bekannte Standorte",
        description=(
            "Bekannte Standorte auflisten. Im Terminal lesbar, "
            "bei Pipe oder --json JSON."
        ),
    )

    # watch
    p_watch = sub_p.add_parser("watch", help="Lokaler Keyword-Watch")
    watch_sub = p_watch.add_subparsers(dest="watch_cmd", required=False)
    p_watch_add = watch_sub.add_parser("add", help="Watch hinzufügen")
    p_watch_add.add_argument("query")
    p_watch_add.add_argument("--limit", type=int, default=10)
    watch_sub.add_parser("list", help="Watch-Liste")
    p_watch_rm = watch_sub.add_parser("remove", help="Watch entfernen")
    p_watch_rm.add_argument("id")

    # login / loans / logout
    sub_p.add_parser(
        "login",
        help="Bibliothekskonto-Session aufbauen",
        description=(
            "Bibliothekskonto-Session aufbauen. BIBLIOTHEK_USER und "
            "BIBLIOTHEK_PASSWORD haben Vorrang; fehlende Werte werden im "
            "Terminal interaktiv abgefragt (Benutzernummer und Passwort). "
            "Ohne Terminal müssen beide Env-Variablen gesetzt sein."
        ),
        epilog=(
            "Beispiel: bibliothek login  |  "
            "BIBLIOTHEK_USER=123 BIBLIOTHEK_PASSWORD=geheim bibliothek login"
        ),
    )
    p_loans = sub_p.add_parser(
        "loans",
        help="Ausleihen",
        description=(
            "Ausleihen anzeigen. Im Terminal lesbare Liste, "
            "bei Pipe oder --json JSON."
        ),
    )
    loans_sub = p_loans.add_subparsers(dest="loans_cmd", required=False)
    loans_sub.add_parser("list", help="Ausleihen auflisten")
    p_renew = loans_sub.add_parser("renew", help="Ausleihe verlängern")
    p_renew.add_argument("loan_id")
    p_renew.add_argument("--confirm", action="store_true")
    sub_p.add_parser("logout", help="Session löschen (idempotent)")

    return parser


HANDLERS: dict[str, Callable[[argparse.Namespace, bool], int]] = {
    "search": handle_search,
    "show": handle_show,
    "watch": cmd_watch,
    "locations": cmd_locations,
    "login": cmd_login,
    "logout": cmd_logout,
    "loans": cmd_loans,
}


def _configure_logging(verbose: bool) -> None:
    env_level = os.environ.get("BIBLIOTHEK_LOG")
    if verbose:
        level: int | str = logging.INFO
    elif env_level:
        level = env_level
    else:
        level = logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    # `--json` und `-v/--verbose` dürfen überall stehen. Wir ziehen sie aus
    # dem argv, bevor argparse sie als Unbekannt abweisen würde.
    raw = list(argv if argv is not None else sys.argv[1:])
    as_json = False
    verbose = False
    filtered: list[str] = []
    for tok in raw:
        if tok == "--json" or tok.startswith("--json="):
            as_json = True
        elif tok in ("-v", "--verbose"):
            verbose = True
        else:
            filtered.append(tok)
    _configure_logging(verbose)
    parser = build_parser()
    try:
        args = parser.parse_args(filtered)
    except SystemExit:
        if as_json:
            sys.stdout.write(
                json.dumps(
                    {"error": {"kind": "usage", "code": 1, "message": "invalid arguments"}},
                    ensure_ascii=False,
                )
                + "\n"
            )
            return 1
        raise
    args.verbose = verbose
    if args.cmd is None:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        return fail(1, f"unbekannter Befehl: {args.cmd}", as_json=as_json)
    try:
        return handler(args, as_json=as_json)
    except KeyboardInterrupt:
        return _cancelled(as_json)
    except Exception as e:
        LOG.error("unhandled exception: %s", e)
        LOG.debug(traceback.format_exc())
        return fail(5, f"interner Fehler: {e}", as_json=as_json)
