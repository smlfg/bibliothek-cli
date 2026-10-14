"""Tests für cli.py – ohne Netz, mit Tempdir."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest


def _exec(args, env=None):
    """bibliothek-cli als Subprozess, damit das --json-Flagging real geprüft wird."""
    base = [sys.executable, "-c", "import sys; from bibliothek_cli.cli import main; sys.exit(main(sys.argv[1:]))"]
    e = os.environ.copy()
    e["BIBLIOTHEK_CONFIG"] = "/tmp/bib-test-cli"
    if env:
        e.update(env)
    p = subprocess.run(base + args, capture_output=True, text=True, env=e)
    return p


def test_version():
    p = _exec(["--version"])
    assert p.returncode == 0
    assert p.stdout.strip().startswith("bibliothek ")


def test_help():
    p = _exec(["--help"])
    assert p.returncode == 0
    assert "Suche" in p.stdout or "search" in p.stdout


def test_locations_json():
    p = _exec(["locations", "--json"])
    assert p.returncode == 0
    data = json.loads(p.stdout)
    assert "locations" in data
    assert any(loc["code"] == "HN" for loc in data["locations"])


def test_watch_roundtrip(tmp_path=None):
    base = "/tmp/bib-test-cli-watch"
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    p = _exec(["watch", "add", "Deep Learning", "--limit", "5"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    data = json.loads(p.stdout)
    assert data["query"] == "Deep Learning"
    assert data["limit"] == 5
    wid = data["id"]

    p = _exec(["watch", "list", "--json"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    assert wid in p.stdout

    p = _exec(["watch", "remove", wid, "--json"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    assert json.loads(p.stdout)["removed"] is True

    # idempotent
    p = _exec(["watch", "remove", wid, "--json"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    assert json.loads(p.stdout)["noop"] is True


def test_renew_without_confirm_exits_5():
    p = _exec(["loans", "renew", "ABC123"])
    assert p.returncode == 5
    assert p.stdout == ""  # no commit
    # json mode still
    p = _exec(["loans", "renew", "ABC123", "--json"])
    assert p.returncode == 5
    data = json.loads(p.stdout)
    assert data["error"]["code"] == 5
    assert data["error"]["kind"] == "confirm_required"


def test_search_empty_query_exits_1():
    """Leere/whitespace-only Query ist Usage-Fehler, kein 200-OK mit leeren Treffern."""
    p = _exec(["search", "", "--json"])
    assert p.returncode == 1
    data = json.loads(p.stdout)
    assert data["error"]["code"] == 1
    assert data["error"]["kind"] == "usage"
    p = _exec(["search", "   ", "--json"])
    assert p.returncode == 1


def test_search_limit_range_exits_1():
    p = _exec(["search", "x", "--limit", "0", "--json"])
    assert p.returncode == 1
    assert json.loads(p.stdout)["error"]["kind"] == "usage"
    p = _exec(["search", "x", "--limit", "51", "--json"])
    assert p.returncode == 1


def test_login_missing_env_exits_2():
    p = _exec(["login"], env={"BIBLIOTHEK_USER": "", "BIBLIOTHEK_PASSWORD": ""})
    assert p.returncode == 2


def test_logout_idempotent():
    base = "/tmp/bib-test-cli-logout"
    import shutil

    shutil.rmtree(base, ignore_errors=True)
    p = _exec(["logout", "--json"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    assert json.loads(p.stdout)["existed"] is False
    p = _exec(["logout", "--json"], env={"BIBLIOTHEK_CONFIG": base})
    assert p.returncode == 0
    assert json.loads(p.stdout)["existed"] is False