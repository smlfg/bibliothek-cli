import argparse

from . import __version__
from . import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="goodtool", description="Kurskatalog")
    parser.add_argument("--version", action="version", version=f"goodtool {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Zugangsdaten speichern")
    login_parser.set_defaults(handler=lambda args: commands.login())

    logout_parser = subparsers.add_parser("logout", help="Zugangsdaten löschen")
    logout_parser.set_defaults(handler=lambda args: commands.logout())

    search_parser = subparsers.add_parser("search", help="Kurse suchen")
    search_parser.add_argument("name", help="Teilstring des Kursnamens")
    search_parser.add_argument("--json", action="store_true", help="JSON ausgeben")
    search_parser.set_defaults(
        handler=lambda args: commands.search(args.name, args.json)
    )

    book_parser = subparsers.add_parser("book", help="Kurs buchen")
    book_parser.add_argument("name", help="Teilstring des Kursnamens")
    book_parser.add_argument(
        "--yes", action="store_true", help="Rückfrage überspringen"
    )
    book_parser.set_defaults(
        handler=lambda args: commands.book(args.name, args.yes)
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
