import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))

from fake_server import FakeServer  # noqa: E402
from ux_spec import (  # noqa: E402
    commands,
    field_matches,
    install_command,
    is_write_session,
    parse,
)

SAMPLE = HARNESS / "selftest" / "sample"
UX = SAMPLE / "docs" / "UX.md"
FORM_PATH = "/cgi/anmeldung.fcgi"


def post(server, data: bytes, content_type: str | None = None, path: str = FORM_PATH):
    request = urllib.request.Request(server.base_url + path, data=data, method="POST")
    if content_type:
        request.add_header("Content-Type", content_type)
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read()


def test_valid_spec_parses_without_errors():
    spec = parse(UX)
    assert spec.errors == []
    assert spec.meta["tool"] == "demo"
    assert [session.title for session in spec.sessions] == [
        "Angebote ansehen",
        "Kurs buchen",
    ]
    assert not is_write_session(spec.sessions[0])
    assert is_write_session(spec.sessions[1])
    assert install_command(spec.sessions[0]) == "pipx install demo"
    assert commands(spec.sessions[0]) == ["demo list"]
    assert commands(spec.sessions[1]) == ["demo book 1"]
    assert len(spec.routes) == 1
    assert [step.id for step in spec.formsteps] == [
        "kurs_waehlen",
        "daten",
        "verbindlich",
    ]
    assert field_matches("BS_Kursid_*", {"BS_Kursid_32304"})
    assert not field_matches("vorname", {"name"})


def test_broken_json_is_error():
    spec = parse(SAMPLE / "docs" / "UX_broken_json.md")
    assert spec.errors
    assert any("kaputtes JSON" in error for error in spec.errors)


def test_hash_line_is_error():
    spec = parse(SAMPLE / "docs" / "UX_hash.md")
    assert any("'#'-Zeile" in error for error in spec.errors)


def test_missing_response_file_is_error():
    spec = parse(SAMPLE / "docs" / "UX_missing_response.md")
    assert any("Response-Datei fehlt" in error for error in spec.errors)


def test_get_route_serves_fixture_and_records_query():
    spec = parse(UX)
    with FakeServer(spec, SAMPLE) as server:
        with urllib.request.urlopen(
            server.base_url + "/angebote?q=1", timeout=5
        ) as response:
            assert response.status == 200
            assert b"Angebote" in response.read()
        recorded = server.requests[-1]
        assert recorded.method == "GET"
        assert recorded.path == "/angebote"
        assert recorded.query == "q=1"
        assert "q" in recorded.fields


def test_three_posts_map_to_three_formsteps():
    spec = parse(UX)
    bodies = [
        urllib.parse.urlencode({"BS_Kursid_32304": "32304"}).encode(),
        urllib.parse.urlencode({"vorname": "Max", "name": "Muster"}).encode(),
        urllib.parse.urlencode({"fid": "4711"}).encode(),
    ]
    with FakeServer(spec, SAMPLE) as server:
        responses = [
            post(server, body, "application/x-www-form-urlencoded") for body in bodies
        ]
        assert [status for status, _ in responses] == [200, 200, 200]
        assert b"Schritt 1" in responses[0][1]
        assert b"Schritt 2" in responses[1][1]
        assert b"Schritt 3" in responses[2][1]
        assert [step_id for step_id, _ in server.sent_formsteps()] == [
            "kurs_waehlen",
            "daten",
            "verbindlich",
        ]
        assert server.missing_formsteps() == []


def test_only_one_post_reports_two_missing():
    spec = parse(UX)
    with FakeServer(spec, SAMPLE) as server:
        post(
            server,
            urllib.parse.urlencode({"BS_Kursid_32304": "32304"}).encode(),
            "application/x-www-form-urlencoded",
        )
        reasons = {step.id: reason for step, reason in server.missing_formsteps()}
        assert reasons == {
            "daten": "nie gesendet",
            "verbindlich": "nie gesendet",
        }


def test_missing_field_is_reported():
    spec = parse(UX)
    with FakeServer(spec, SAMPLE) as server:
        post(
            server,
            urllib.parse.urlencode({"BS_Kursid_32304": "32304"}).encode(),
            "application/x-www-form-urlencoded",
        )
        post(
            server,
            urllib.parse.urlencode({"vorname": "Max"}).encode(),
            "application/x-www-form-urlencoded",
        )
        reasons = {step.id: reason for step, reason in server.missing_formsteps()}
        assert reasons["daten"].startswith("Felder fehlen:")
        assert "name" in reasons["daten"]
        assert reasons["verbindlich"] == "nie gesendet"


def test_multipart_and_json_bodies_are_parsed():
    spec = parse(UX)
    boundary = "----ux-test-boundary"
    multipart = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="vorname"\r\n\r\nMax\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="name"\r\n\r\nMuster\r\n'
        f"--{boundary}--\r\n"
    ).encode()
    with FakeServer(spec, SAMPLE) as server:
        post(server, multipart, f"multipart/form-data; boundary={boundary}")
        assert {"vorname", "name"} <= server.requests[-1].fields
        post(server, json.dumps({"fid": "4711", "extra": "x"}).encode(), "application/json")
        assert {"fid", "extra"} <= server.requests[-1].fields


def test_other_methods_are_accepted_and_logged():
    spec = parse(UX)
    with FakeServer(spec, SAMPLE) as server:
        for method in ("HEAD", "PUT", "PATCH", "DELETE"):
            request = urllib.request.Request(
                server.base_url + "/unbekannt", data=b"a=1", method=method
            )
            try:
                urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                assert error.code == 404
            assert server.requests[-1].method == method
            assert "a" in server.requests[-1].fields


def test_mark_and_formsteps_before():
    spec = parse(UX)
    with FakeServer(spec, SAMPLE) as server:
        stamp = server.mark("bestaetigung")
        assert server.formsteps_before(stamp) == []
        post(
            server,
            urllib.parse.urlencode({"BS_Kursid_32304": "32304"}).encode(),
            "application/x-www-form-urlencoded",
        )
        assert [step.id for step in server.formsteps_before(server.mark("danach"))] == [
            "kurs_waehlen"
        ]
