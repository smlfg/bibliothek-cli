"""CLI-Entry-Bibliothek-cli – argparse-Definition, –vorgaben für –json."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    """Baut den ArgumentParser mit Subcommands."""
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


def emit(data: dict[str, Any], as_json: bool) -> int:
    """Zentrale Ausgabe: bei --json ein JSON-Objekt auf stdout."""
    if as_json:
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    else:
        # kompakte, menschenlesbare Default-Darstellung
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Top-Level Entry-Point."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse exit codes: 2 für Usage-Fehler; für --json in ein Objekt wrappen.
        if hasattr(e, "code") and e.code == 2:
            sys.stderr.write(str(e))
        raise

    if args.cmd is None:
        parser.print_help()
        return 0

    # Delegation an Subcommand-Handler (in der nächsten Iteration ergänzt)
    data = {"status": "not-implemented", "cmd": args.cmd, "args": vars(args)}
    return emit(data, as_json=bool(getattr(args, "json", False)))