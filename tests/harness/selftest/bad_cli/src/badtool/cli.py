import argparse
import json

from . import __version__
from .client import fetch_items, post_form
from .credentials import load_credentials


def search(query: str) -> int:
    items = fetch_items(query)
    print(json.dumps(items, ensure_ascii=False))
    return 0


def book(item_id: str, confirm: bool) -> int:
    load_credentials()
    if not confirm:
        print(json.dumps({"id": item_id, "dry_run": True}, ensure_ascii=False))
        return 0
    post_form({"item": item_id})
    print(json.dumps({"submitted": True}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="badtool", description="Kurskatalog")
    parser.add_argument("--version", action="version", version=f"badtool {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search", help="Kurse suchen")
    search_parser.add_argument("--query", required=True, help="Suchbegriff")
    search_parser.set_defaults(handler=lambda args: search(args.query))

    book_parser = subparsers.add_parser("book", help="Kurs buchen")
    book_parser.add_argument("id", help="Kurs-ID")
    book_parser.add_argument(
        "--confirm", action="store_true", help="Buchung absenden"
    )
    book_parser.set_defaults(
        handler=lambda args: book(args.id, args.confirm)
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
