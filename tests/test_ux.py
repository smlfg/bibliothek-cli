"""UX-Tests: Terminal-Ausgabe, interaktiver Login, Log-Default."""

from __future__ import annotations

import json

import pytest

from bibliothek_cli import cli


SEARCH_RESULT = {
    "query": "python",
    "media": "all",
    "available_only": False,
    "total_found": 1,
    "count": 1,
    "results": [
        {
            "id": "AK63608656",
            "title": "Python für Einsteiger",
            "author": "Ada Beispiel",
            "year": "2026",
            "signature": "HN PY 1",
            "location": "Bildungscampus Heilbronn",
            "available": True,
            "media_type": "book",
        }
    ],
}


def _fake_search(*args, **kwargs):
    return SEARCH_RESULT


def test_search_human_output_in_terminal(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(cli.http_mod, "search", _fake_search)
    rc = cli.main(["search", "python"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[1] Python für Einsteiger – Ada Beispiel (2026)" in out
    assert "Bildungscampus Heilbronn" in out
    assert "verfügbar" in out
    assert "ID AK63608656" in out
    assert not out.lstrip().startswith("{")


def test_search_pipe_without_json_stays_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    monkeypatch.setattr(cli.http_mod, "search", _fake_search)
    rc = cli.main(["search", "python"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["results"][0]["id"] == "AK63608656"


def test_search_json_wins_over_tty(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(cli.http_mod, "search", _fake_search)
    rc = cli.main(["search", "python", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["query"] == "python"


def test_locations_human_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
    rc = cli.main(["locations"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[HN] Bibliothek Bildungscampus Heilbronn" in out
    assert not out.lstrip().startswith("{")


def test_show_human_output(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(cli.http_mod, "search", _fake_search)
    rc = cli.main(["show", "AK63608656"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Titel: Python für Einsteiger" in out
    assert "Autor: Ada Beispiel" in out
    assert "ID: AK63608656" in out


def test_loans_human_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BIBLIOTHEK_CONFIG", str(tmp_path))
    (tmp_path / "session.json").write_text('{"mock": true}', encoding="utf-8")
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)
    rc = cli.main(["loans"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[1] Beispiel-Ausleihe (Mock)" in out
    assert "ID MOCK-1" in out
    assert "verlängerbar" in out


def test_login_prompts_and_mocks_http(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BIBLIOTHEK_USER", raising=False)
    monkeypatch.delenv("BIBLIOTHEK_PASSWORD", raising=False)
    monkeypatch.setenv("BIBLIOTHEK_CONFIG", str(tmp_path))
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    prompts = []

    def fake_input(prompt=""):
        prompts.append(("input", prompt))
        return "12345"

    def fake_getpass(prompt=""):
        prompts.append(("getpass", prompt))
        return "geheim"

    captured = {}

    def fake_login_session(user, password, *, base_url=None, timeout=30.0):
        captured["user"] = user
        captured["password"] = password
        return {"cookies": {"SID": "x"}, "mock": True}

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
    monkeypatch.setattr(cli.http_mod, "login_session", fake_login_session)

    rc = cli.main(["login", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["user"] == "12345"
    assert captured == {"user": "12345", "password": "geheim"}
    assert [kind for kind, _ in prompts] == ["input", "getpass"]
    session = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert session["user"] == "12345"
    assert session["cookies"] == {"SID": "x"}


def test_login_env_has_precedence(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BIBLIOTHEK_USER", "env-user")
    monkeypatch.setenv("BIBLIOTHEK_PASSWORD", "env-pw")
    monkeypatch.setenv("BIBLIOTHEK_CONFIG", str(tmp_path))
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)

    def must_not_prompt(*args, **kwargs):
        raise AssertionError("Prompt trotz gesetzter Env-Variablen")

    captured = {}

    def fake_login_session(user, password, *, base_url=None, timeout=30.0):
        captured["user"] = user
        captured["password"] = password
        return {"cookies": {}, "mock": True}

    monkeypatch.setattr("builtins.input", must_not_prompt)
    monkeypatch.setattr(cli.getpass, "getpass", must_not_prompt)
    monkeypatch.setattr(cli.http_mod, "login_session", fake_login_session)

    rc = cli.main(["login", "--json"])
    assert rc == 0
    assert captured == {"user": "env-user", "password": "env-pw"}


def test_login_without_tty_and_env_has_next_step(monkeypatch, capsys):
    monkeypatch.delenv("BIBLIOTHEK_USER", raising=False)
    monkeypatch.delenv("BIBLIOTHEK_PASSWORD", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    rc = cli.main(["login"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "Login fehlt: `bibliothek login` im Terminal ausführen" in err
    assert "BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD setzen" in err
    assert "Traceback" not in err


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_login_cancel_is_one_line(monkeypatch, capsys, exc):
    monkeypatch.delenv("BIBLIOTHEK_USER", raising=False)
    monkeypatch.delenv("BIBLIOTHEK_PASSWORD", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)

    def cancel(prompt=""):
        raise exc()

    monkeypatch.setattr("builtins.input", cancel)
    rc = cli.main(["login"])
    err = capsys.readouterr().err
    assert rc == 1
    assert err.strip() == "Abgebrochen."
    assert "Traceback" not in err


def test_logging_defaults_to_warning(monkeypatch, capsys):
    monkeypatch.delenv("BIBLIOTHEK_LOG", raising=False)
    cli._configure_logging(False)
    cli.LOG.info("bootstrap OK: default")
    assert "bootstrap OK" not in capsys.readouterr().err

    cli._configure_logging(True)
    cli.LOG.info("bootstrap OK: verbose")
    assert "bootstrap OK: verbose" in capsys.readouterr().err


def test_verbose_flag_enables_info_logs(monkeypatch, capsys):
    monkeypatch.delenv("BIBLIOTHEK_LOG", raising=False)

    def logging_search(*args, **kwargs):
        cli.LOG.info("bootstrap OK: fake")
        return SEARCH_RESULT

    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    monkeypatch.setattr(cli.http_mod, "search", logging_search)

    assert cli.main(["search", "python"]) == 0
    assert "bootstrap OK" not in capsys.readouterr().err

    assert cli.main(["search", "python", "-v"]) == 0
    assert "bootstrap OK" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["search", "show", "loans", "locations", "login"])
def test_changed_commands_have_help(capsys, command):
    with pytest.raises(SystemExit) as exc:
        cli.main([command, "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out


def test_login_help_explains_env_and_prompt(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["login", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "BIBLIOTHEK_USER" in out
    assert "BIBLIOTHEK_PASSWORD" in out
    assert "interaktiv" in out
    assert "Passwort" in out
