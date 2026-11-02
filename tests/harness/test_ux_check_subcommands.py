import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ux_check import _subcommands  # noqa: E402

METAVAR_HELP = """usage: wggesucht [-h] [--version] SUBCOMMAND ...

positional arguments:
  SUBCOMMAND
    login       Anmelden
    search      Suchen
    messages    Nachrichten

options:
  -h, --help    show this help message and exit
"""


def test_argparse_metavar_subcommands():
    assert _subcommands(METAVAR_HELP) == ["login", "search", "messages"]


def test_argparse_brace_subcommands():
    help_text = "usage: t [-h] {login,book} ...\n\npositional arguments:\n  {login,book}\n"
    assert set(_subcommands(help_text)) == {"login", "book"}
