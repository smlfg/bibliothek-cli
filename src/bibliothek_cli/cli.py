"""CLI-Entry – argparse-Definition, Handler, JSON-Output zentral."""

from __future__ import annotations

import argparse
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

def emit(data: dict[str, Any], as_json: bool) -> int:
    """Zentrale Ausgabe: bei --json ein JSON-Objekt auf stdout."""
    if as_json:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    else:
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


def cmd_locations(args: argparse.Namespace, as_json: bool) -> int:
    return emit({"locations": _LOCATIONS}, as_json=as_json)


# ---------- Search ----------

def handle_search(args: argparse.Namespace, as_json: bool) -> int:
    try:
        result = http_mod.search(
            args.query,
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
    return emit(result, as_json=as_json)


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
        )
    if sub == "list":
        return emit({"items": list(items.values())}, as_json=as_json)
    if sub == "remove":
        if args.id not in items:
            return emit({"noop": True, "id": args.id}, as_json=as_json)
        del items[args.id]
        _save_watch(items)
        return emit({"removed": True, "id": args.id}, as_json=as_json)
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
        return emit(items[wid], as_json=as_json)
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


def cmd_login(args: argparse.Namespace, as_json: bool) -> int:
    """Login mit BIBLIOTHEK_USER + BIBLIOTHEK_PASSWORD.

    Bei fehlenden Credentials: Exit 2. Bei korrekten Credentials wird eine
    Session in session.json (Mode 0600) gespeichert. Echter End-to-end-Login
    (Cookie-POST + Mein-Konto-Beweis) benötigt eine JS-gesteuerte Maske und ist
    derzeit als Mock implementiert. Siehe docs/QA.md.
    """
    user = os.environ.get("BIBLIOTHEK_USER")
    pw = os.environ.get("BIBLIOTHEK_PASSWORD")
    if not user or not pw:
        return fail(
            2,
            "BIBLIOTHEK_USER und/oder BIBLIOTHEK_PASSWORD nicht gesetzt.",
            as_json=as_json,
            kind="auth",
        )
    # Mock: ohne JS/Login-Backend können wir keine echte Session aufbauen.
    # Wir speichern nur, dass Login „versucht" wurde. Live-Erfolg hängt an
    # einer Folge-Iteration mit Playwright.
    sess = {
        "user": user,
        "cookies": {},  # OPAC-Cookies (Origin = bsz.ibs-bw.de)
        "established_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "mock": True,
    }
    path = _session_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return emit(
        {"login": "ok", "user": user, "mock": True, "note": "Mock-Session; ohne Live-Backend."},
        as_json=as_json,
    )


def cmd_logout(args: argparse.Namespace, as_json: bool) -> int:
    path = _session_path()
    removed = False
    if os.path.exists(path):
        os.remove(path)
        removed = True
    return emit({"removed": True, "existed": removed}, as_json=as_json)


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

    sub_p = parser.add_subparsers(dest="cmd", required=False)

    # search
    p_search = sub_p.add_parser("search", help="Katalog durchsuchen")
    p_search.add_argument("query", help="Suchbegriff")
    p_search.add_argument("--media", choices=["book", "ebook", "all"], default="all")
    p_search.add_argument("--available", action="store_true")
    p_search.add_argument("--limit", type=int, default=20)

    # show
    p_show = sub_p.add_parser("show", help="Titeldetails / Verfügbarkeit")
    p_show.add_argument("record", help="Record-ID oder Detail-URL")

    # locations
    sub_p.add_parser("locations", help="Bekannte Standorte")

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
    sub_p.add_parser("login", help="Bibliothekskonto-Session aufbauen")
    p_loans = sub_p.add_parser("loans", help="Ausleihen")
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("BIBLIOTHEK_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # `--json` darf überall stehen. Wir ziehen es aus dem argv,
    # bevor argparse es als Unbekannt abweisen würde.
    raw = list(argv if argv is not None else sys.argv[1:])
    as_json = False
    filtered: list[str] = []
    for tok in raw:
        if tok == "--json":
            as_json = True
        elif tok.startswith("--json="):
            as_json = True
        else:
            filtered.append(tok)
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
    if args.cmd is None:
        parser.print_help()
        return 0
    handler = HANDLERS.get(args.cmd)
    if handler is None:
        return fail(1, f"unbekannter Befehl: {args.cmd}", as_json=as_json)
    try:
        return handler(args, as_json=as_json)
    except Exception as e:
        LOG.error("unhandled exception: %s", e)
        LOG.debug(traceback.format_exc())
        return fail(5, f"interner Fehler: {e}", as_json=as_json)