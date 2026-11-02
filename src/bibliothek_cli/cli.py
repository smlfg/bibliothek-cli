"""CLI-Entry – argparse-Definition, Handler, JSON-Output zentral."""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import logging
import os
import re
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


def _format_status(status: str) -> str:
    return re.sub(
        r"\s+-\s+Fällig am:?\s*", " – fällig am ", status, flags=re.IGNORECASE
    ).strip()


def _render_show(data: dict[str, Any]) -> str:
    lines = []
    if data.get("title"):
        lines.append(f"Titel: {data['title']}")
    authors = data.get("authors") or []
    if authors:
        lines.append(f"Autor: {', '.join(authors)}")
    if data.get("year"):
        lines.append(f"Jahr: {data['year']}")
    copies = data.get("copies") or []
    first = copies[0] if copies else {}
    standort = ", ".join(
        part for part in (first.get("library"), first.get("location")) if part
    )
    if standort:
        lines.append(f"Standort: {standort}")
    if data.get("signature"):
        lines.append(f"Signatur: {data['signature']}")
    if first.get("status"):
        lines.append(f"Status: {_format_status(first['status'])}")
    if data.get("media_type"):
        lines.append(f"Medientyp: {data['media_type']}")
    if not copies:
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
    return f"Login erfolgreich als {data.get('user', '?')}{note}."


def _render_whoami(data: dict[str, Any]) -> str:
    note = " (Mock-Session)" if data.get("mock") else ""
    return f"Angemeldet als {data.get('user', '?')}{note}."


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


def _render_verlaengern(data: dict[str, Any]) -> str:
    lines = []
    if data.get("title"):
        lines.append(f"Titel: {data['title']}")
    lines.append("Verlängerung bestätigt.")
    lines.append(f"Neues Fälligkeitsdatum: {data.get('new_due', '?')}")
    return "\n".join(lines)


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

def _extract_record_id(rec: str) -> str:
    import re as _re
    match = _re.search(r"(AK[A-Z0-9]+)", rec)
    return match.group(1) if match else rec


def _show_from_hit(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record["id"],
        "title": record["title"],
        "authors": [record["author"]] if record["author"] else [],
        "year": record["year"],
        "signature": record["signature"],
        "media_type": record["media_type"],
        "locations": [],
    }


def handle_show(args: argparse.Namespace, as_json: bool) -> int:
    rec = (args.record or "").strip()
    if not rec:
        return fail(
            1,
            "Titel oder Datensatz-ID angeben, z. B. `bibliothek show AK63638611`.",
            as_json=as_json,
            kind="usage",
        )
    base_url = os.environ.get("BIBLIOTHEK_BASE_URL", http_mod.DEFAULT_BASE)
    looks_like_id = bool(_extract_record_id(rec).upper().startswith("AK"))
    search_term = _extract_record_id(rec) if (rec.startswith("http") or looks_like_id) else rec
    try:
        hits = http_mod.search(search_term, base_url=base_url, limit=20)
    except http_mod.HttpError as e:
        return fail(3, str(e), as_json=as_json, kind="network")
    except http_mod.ParseError as e:
        return fail(4, str(e), as_json=as_json, kind="parse")

    results = hits.get("results") or []
    if looks_like_id:
        record = next(
            (item for item in results if item["id"].upper() == search_term.upper()),
            None,
        )
        if record is None:
            return fail(
                4,
                f"Datensatz {search_term} nicht gefunden. Prüfe die ID oder "
                "nutze `bibliothek search SUCHBEGRIFF`.",
                as_json=as_json,
                kind="parse",
            )
        return emit(_show_from_hit(record), as_json=as_json, render=_render_show)

    if not results:
        return fail(
            4,
            f"Kein Treffer für „{rec}“. Prüfe den Suchbegriff mit "
            "`bibliothek search SUCHBEGRIFF`.",
            as_json=as_json,
            kind="parse",
        )
    exact = [item for item in results if item["title"].casefold() == rec.casefold()]
    if exact:
        chosen = exact[0]
    elif len(results) == 1:
        chosen = results[0]
    elif not _stdin_is_tty():
        lines = [
            f"[{index}] {item['title']} ({item.get('year') or '?'})"
            for index, item in enumerate(results, 1)
        ]
        return fail(
            1,
            "Mehrere Treffer, ohne Terminal keine Auswahl:\n"
            + "\n".join(lines)
            + "\nWähle eine ID und nutze `bibliothek show AK...`.",
            as_json=as_json,
            kind="usage",
        )
    else:
        for index, item in enumerate(results, 1):
            sys.stderr.write(
                f"[{index}] {item['title']} ({item.get('year') or '?'})\n"
            )
        try:
            answer = _ask(f"Auswahl [1-{len(results)}]: ").strip()
            choice = int(answer)
        except (EOFError, KeyboardInterrupt):
            return _cancelled(as_json)
        except ValueError:
            return fail(1, "Bitte eine Zahl aus der Liste eingeben.", as_json=as_json)
        if not 1 <= choice <= len(results):
            return fail(1, "Auswahl außerhalb der Liste.", as_json=as_json)
        chosen = results[choice - 1]

    try:
        detail = http_mod.detail(chosen["id"], base_url=base_url)
    except http_mod.HttpError as e:
        return fail(3, str(e), as_json=as_json, kind="network")
    except http_mod.ParseError as e:
        return fail(4, str(e), as_json=as_json, kind="parse")
    detail.setdefault("title", chosen["title"])
    detail.setdefault("year", chosen["year"])
    if chosen.get("author"):
        detail["authors"] = [chosen["author"]]
    elif not detail.get("authors"):
        detail["authors"] = []
    detail.setdefault("signature", chosen.get("signature", ""))
    detail.setdefault("media_type", chosen.get("media_type", ""))
    return emit(detail, as_json=as_json, render=_render_show)


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


def _read_session() -> dict[str, Any] | None:
    path = _session_path()
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(open(path, encoding="utf-8").read() or "{}")
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_session(sess: dict[str, Any]) -> None:
    path = _session_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _base_url() -> str:
    return os.environ.get("BIBLIOTHEK_BASE_URL", http_mod.DEFAULT_BASE)


def _fail_http(exc: Exception, as_json: bool) -> int:
    if isinstance(exc, http_mod.AuthError):
        return fail(2, str(exc), as_json=as_json, kind="auth")
    if isinstance(exc, http_mod.ParseError):
        return fail(4, str(exc), as_json=as_json, kind="parse")
    if isinstance(exc, http_mod.HttpError):
        return fail(3, str(exc), as_json=as_json, kind="network")
    return fail(5, f"Unerwarteter Fehler: {exc}", as_json=as_json)


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
                user = _ask("Ausweisnummer: ").strip()
            if not pw:
                pw = getpass.getpass("Passwort: ")
        except (EOFError, KeyboardInterrupt):
            return _cancelled(as_json)
    if not user or not pw:
        return fail(
            2,
            "Login unvollständig: Ausweisnummer und Passwort erforderlich. "
            "Starte `bibliothek login` erneut.",
            as_json=as_json,
            kind="auth",
        )
    try:
        auth = http_mod.login_session(user, pw, base_url=_base_url())
    except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
        return _fail_http(e, as_json)
    sess = {
        "user": user,
        "cookies": auth.get("cookies", {}),
        "established_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mock": bool(auth.get("mock", False)),
    }
    _write_session(sess)
    data: dict[str, Any] = {
        "login": "ok",
        "user": user,
        "mock": sess["mock"],
    }
    if sess["mock"]:
        data["note"] = "Mock-Session; ohne Live-Backend."
    return emit(data, as_json=as_json, render=_render_login)


def cmd_whoami(args: argparse.Namespace, as_json: bool) -> int:
    sess = _read_session()
    if not sess or not sess.get("user"):
        return fail(
            2,
            "Keine Session. Führe `bibliothek login` aus.",
            as_json=as_json,
            kind="auth",
        )
    return emit(
        {
            "user": sess.get("user"),
            "established_at": sess.get("established_at", ""),
            "mock": bool(sess.get("mock", False)),
        },
        as_json=as_json,
        render=_render_whoami,
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


_MOCK_LOANS = [
    {
        "id": "MOCK-1",
        "title": "Beispiel-Ausleihe (Mock)",
        "due": "2026-11-01",
        "renewals": 0,
        "can_renew": True,
    }
]


def _load_konto_or_fail(sess: dict[str, Any]) -> dict[str, Any]:
    return http_mod.load_konto(sess.get("cookies", {}), base_url=_base_url())


def cmd_loans(args: argparse.Namespace, as_json: bool) -> int:
    sub = getattr(args, "loans_cmd", None)
    if sub == "renew":
        if not args.confirm:
            return fail(
                5,
                "Verlängerung verlangt --confirm; keine Aktion ausgeführt. "
                "Starte `bibliothek verlaengern TITEL` im Terminal oder nutze "
                "--confirm.",
                as_json=as_json,
                kind="confirm_required",
            )
        sess = _read_session()
        if sess is None:
            return fail(2, _LOGIN_MISSING, as_json=as_json, kind="auth")
        if sess.get("mock"):
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
        try:
            konto = _load_konto_or_fail(sess)
        except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
            return _fail_http(e, as_json)
        loan = next(
            (item for item in konto["loans"] if item["id"] == args.loan_id), None
        )
        if loan is None:
            return fail(
                4,
                f"Ausleihe {args.loan_id} nicht im Konto gefunden. "
                "`bibliothek loans` zeigt alle Ausleihen.",
                as_json=as_json,
                kind="parse",
            )
        try:
            result = http_mod.renew_loan(konto, loan)
        except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
            return _fail_http(e, as_json)
        return emit(result, as_json=as_json, render=_render_renew)

    if sub not in (None, "list"):
        return fail(1, f"unknown loans subcommand: {sub}", as_json=as_json)

    sess = _read_session()
    if sess is None:
        return fail(2, _LOGIN_MISSING, as_json=as_json, kind="auth")
    if sess.get("mock"):
        return emit(
            {"loans": _MOCK_LOANS, "mock": True},
            as_json=as_json,
            render=_render_loans,
        )
    try:
        konto = _load_konto_or_fail(sess)
    except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
        return _fail_http(e, as_json)
    return emit(
        {"loans": konto["loans"]},
        as_json=as_json,
        render=_render_loans,
    )


def _choose_loan(
    loans: list[dict[str, Any]], title: str, *, interactive: bool, as_json: bool
) -> tuple[dict[str, Any] | None, int | None]:
    query = title.casefold()
    matches = [loan for loan in loans if query in (loan.get("title") or "").casefold()]
    if not matches:
        return None, fail(
            4,
            f"Keine Ausleihe zu „{title}“ gefunden. `bibliothek loans` zeigt "
            "alle Ausleihen.",
            as_json=as_json,
            kind="parse",
        )
    if len(matches) == 1:
        return matches[0], None
    if not interactive:
        lines = [
            f"[{index}] {loan.get('title')} | fällig {loan.get('due') or '?'}"
            for index, loan in enumerate(matches, 1)
        ]
        return None, fail(
            2,
            "Mehrere Ausleihen passen, ohne Terminal keine Auswahl:\n"
            + "\n".join(lines)
            + "\nNutze im Terminal `bibliothek verlaengern TITEL` oder eine ID "
            "mit `bibliothek loans renew ID --confirm`.",
            as_json=as_json,
            kind="auth",
        )
    for index, loan in enumerate(matches, 1):
        sys.stderr.write(
            f"{index}) {loan.get('title')} | fällig {loan.get('due') or '?'}\n"
        )
    try:
        answer = _ask(f"Auswahl [1-{len(matches)}]: ").strip()
        choice = int(answer)
    except (EOFError, KeyboardInterrupt):
        return None, _cancelled(as_json)
    except ValueError:
        return None, fail(
            1, "Bitte eine Zahl aus der Liste eingeben.", as_json=as_json
        )
    if not 1 <= choice <= len(matches):
        return None, fail(1, "Auswahl außerhalb der Liste.", as_json=as_json)
    return matches[choice - 1], None


def cmd_verlaengern(args: argparse.Namespace, as_json: bool) -> int:
    title = (args.title or "").strip()
    if not title:
        return fail(
            1,
            "Titel der Ausleihe angeben, z. B. "
            "`bibliothek verlaengern \"Grundlagen der Hydraulik\"`.",
            as_json=as_json,
            kind="usage",
        )
    interactive = _stdin_is_tty()
    confirmed = bool(args.confirm or args.yes)
    if not confirmed and not interactive:
        return fail(
            5,
            "Verlängerung nicht bestätigt: ohne Terminal keine Aktion. Führe "
            "`bibliothek verlaengern TITEL` im Terminal aus oder nutze "
            "--confirm nach `bibliothek login`.",
            as_json=as_json,
            kind="confirm_required",
        )

    sess = _read_session()
    if sess is None:
        return fail(2, _LOGIN_MISSING, as_json=as_json, kind="auth")
    if sess.get("mock"):
        loan = next(
            (item for item in _MOCK_LOANS if title.casefold() in item["title"].casefold()),
            None,
        )
        if loan is None:
            return fail(
                4,
                f"Keine Ausleihe zu „{title}“ gefunden. `bibliothek loans` "
                "zeigt alle Ausleihen.",
                as_json=as_json,
                kind="parse",
            )
        result = {
            "id": loan["id"],
            "title": loan["title"],
            "renewed": True,
            "new_due": "2026-11-15",
            "mock": True,
        }
        return emit(result, as_json=as_json, render=_render_verlaengern)

    try:
        konto = _load_konto_or_fail(sess)
    except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
        return _fail_http(e, as_json)

    loan, error = _choose_loan(
        konto["loans"], title, interactive=interactive, as_json=as_json
    )
    if error is not None:
        return error

    if not confirmed:
        sys.stderr.write(
            f"Titel: {loan.get('title')}\nFrist: {loan.get('due') or '?'}\n"
        )
        try:
            answer = _ask("Verlängerung verbindlich? [j/N] ")
        except (EOFError, KeyboardInterrupt):
            return _cancelled(as_json)
        if answer.strip().casefold() not in {"j", "ja", "y", "yes"}:
            if as_json:
                return emit({"cancelled": True, "renewed": False}, as_json=True)
            sys.stderr.write("Abgebrochen.\n")
            return 0

    try:
        result = http_mod.renew_loan(konto, loan)
    except (http_mod.HttpError, http_mod.ParseError, http_mod.AuthError) as e:
        return _fail_http(e, as_json)
    return emit(result, as_json=as_json, render=_render_verlaengern)


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
    p_show.add_argument(
        "record", help="Titel/Suchbegriff, Datensatz-ID (AK…) oder Detail-URL"
    )

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
            "Terminal interaktiv abgefragt (Ausweisnummer und Passwort). "
            "Ohne Terminal müssen beide Env-Variablen gesetzt sein."
        ),
        epilog=(
            "Beispiel: bibliothek login  |  "
            "BIBLIOTHEK_USER=123 BIBLIOTHEK_PASSWORD=geheim bibliothek login"
        ),
    )
    sub_p.add_parser(
        "whoami",
        help="Angemeldete Ausweisnummer anzeigen",
        description=(
            "Zeigt die gespeicherte Ausweisnummer ohne Passwort oder Cookies. "
            "Ohne Session: Exit 2 mit Verweis auf `bibliothek login`."
        ),
    )
    p_ver = sub_p.add_parser(
        "verlaengern",
        help="Ausleihe per Titel verlängern",
        description=(
            "Wählt die Ausleihe über den Titel, zeigt Titel und Frist und fragt "
            "im Terminal `Verlängerung verbindlich? [j/N]` (Default Nein). "
            "Erst nach j werden alle Formularschritte gesendet. "
            "--confirm/--yes sind nur für Agenten; ohne Terminal und ohne Flag "
            "bricht der Befehl vor jedem Request ab."
        ),
        epilog=(
            "Beispiel: bibliothek verlaengern \"Grundlagen der Hydraulik\"  |  "
            "bibliothek verlaengern TITEL --confirm"
        ),
    )
    p_ver.add_argument("title", help="Titel oder Teil des Titels der Ausleihe")
    p_ver.add_argument(
        "--confirm", action="store_true", help="Ohne [j/N]-Frage (nur Agenten)"
    )
    p_ver.add_argument(
        "--yes", action="store_true", help="Alias für --confirm (nur Agenten)"
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
    p_renew = loans_sub.add_parser("renew", help="Ausleihe per ID verlängern")
    p_renew.add_argument("loan_id")
    p_renew.add_argument("--confirm", action="store_true")
    p_renew.add_argument("--yes", action="store_true", help="Alias für --confirm")
    sub_p.add_parser("logout", help="Session löschen (idempotent)")

    return parser


HANDLERS: dict[str, Callable[[argparse.Namespace, bool], int]] = {
    "search": handle_search,
    "show": handle_show,
    "watch": cmd_watch,
    "locations": cmd_locations,
    "login": cmd_login,
    "whoami": cmd_whoami,
    "logout": cmd_logout,
    "loans": cmd_loans,
    "verlaengern": cmd_verlaengern,
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
