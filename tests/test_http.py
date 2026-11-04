"""Tests für die HTML-Parser – ohne Netz."""

from __future__ import annotations

from pathlib import Path

import pytest

from bibliothek_cli import http

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_parse_hits_extracts_results():
    html = _read("search_hits.html")
    out = http._parse_hits(
        html, query="python", media="all", available_only=False, limit=10
    )
    assert out["count"] >= 10
    assert out["query"] == "python"
    assert out["total_found"] >= 0
    sample = out["results"][0]
    assert set(sample.keys()) >= {
        "id",
        "title",
        "author",
        "year",
        "signature",
        "media_type",
    }
    assert sample["id"].startswith("AK")


def test_parse_hits_limit():
    html = _read("search_hits.html")
    out = http._parse_hits(
        html, query="python", media="all", available_only=False, limit=3
    )
    assert out["count"] == 3


def test_parse_hits_filters_by_media_ebook():
    """--media ebook muss Treffer auf den Medientyp einschränken."""
    html = _read("search_hits.html")
    out = http._parse_hits(
        html, query="python", media="ebook", available_only=False, limit=10
    )
    assert out["count"] >= 1
    for r in out["results"]:
        assert r["media_type"] == "ebook"


def test_parse_hits_filters_by_media_book_excludes_ebooks():
    """--media book darf keine ebook-Treffer enthalten."""
    html = _read("search_hits.html")
    out = http._parse_hits(
        html, query="python", media="book", available_only=False, limit=10
    )
    for r in out["results"]:
        assert r["media_type"] != "ebook"

def test_parse_hits_no_results():
    out = http._parse_hits(
        _read("search_empty.html"),
        query="asdfqwer",
        media="all",
        available_only=False,
        limit=10,
    )
    assert out["count"] == 0
    assert out["results"] == []
    assert out["total_found"] == 0


def test_extract_form_context_parses_input():
    html = (
        '<html><body><form action="/aDISWeb/app;jsessionid=ABC">'
        '<input type="hidden" name="service" value="direct/x/$Form.form"/>'
        '<input type="hidden" name="sp" value="S0"/>'
        "</form></body></html>"
    )
    action, service, sp = http._extract_form_context(html)
    assert action.endswith("/aDISWeb/app;jsessionid=ABC")
    assert service == "direct/x/$Form.form"
    assert sp == "S0"


def test_extract_form_context_missing_form():
    with pytest.raises(http.ParseError):
        http._extract_form_context("<html></html>")


def test_search_limit_validation():
    import pytest as _p

    with _p.raises(ValueError):
        http.search("x", limit=0)
    with _p.raises(ValueError):
        http.search("x", limit=51)

class _FakeResponse:
    def __init__(self, text: str, url: str, status_code: int = 200):
        self.text = text
        self.url = url
        self.status_code = status_code

    def json(self):
        import json

        return json.loads(self.text)


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict]] = []
        self.cookies = []

    def get(self, url, **kwargs):
        self.gets.append(url)
        return self.responses.pop(0)

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, dict(data or {})))
        return self.responses.pop(0)


def test_open_catalog_keeps_base_without_trailing_slash(monkeypatch):
    session = _FakeSession(
        [_FakeResponse(_read("ux/home.html"), "https://example.invalid/aDISWeb/app")]
    )
    monkeypatch.setattr(http, "_build_session", lambda: session)

    _session, details = http._open_catalog("https://example.invalid/hshn/")

    assert session.gets == ["https://example.invalid/hshn"]
    assert details["service"] == "search"


def test_detail_uses_result_form_action_and_zttext(monkeypatch):
    session = _FakeSession(
        [
            _FakeResponse(_read("ux/home.html"), "http://x/aDISWeb/app?service=home"),
            _FakeResponse(
                _read("ux/treffer.html"), "http://x/aDISWeb/app?service=search"
            ),
            _FakeResponse(
                _read("ux/detail.html"), "http://x/aDISWeb/app?service=detail"
            ),
        ]
    )
    monkeypatch.setattr(http, "_build_session", lambda: session)

    out = http.detail("AK63638611", base_url="http://x")

    assert session.gets == ["http://x"]
    assert len(session.posts) == 2
    url, payload = session.posts[1]
    assert "service=detail" in url
    assert payload["selected"] == "ZTEXT       AK63638611"
    assert out["title"] == "Grundlagen der Hydraulik"
    assert out["authors"] == ["Grollius, Horst-W."]
    assert out["signature"] == "ZL 4650 G875 (2026)"
    assert out["copies"][0]["status"] == "Ausgeliehen - Fällig am: 16.11.2026"
    assert out["copies"][0]["due"] == "16.11.2026"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Horst-W. Grollius. - 10. Auflage. - Hanser", "Grollius, Horst-W."),
        ("Holger Watter. - 7. Auflage. - Springer Vieweg", "Watter, Holger"),
        ("Grollius, Horst-W.", "Grollius, Horst-W."),
    ],
)
def test_clean_author_removes_edition_and_publisher(raw, expected):
    assert http._clean_author(raw) == expected


def test_parse_hits_ranks_available_first():
    html = """
    <html><body><p>Treffer: 3</p><ul>
      <li class="rList_li" data-ajax="AK1">
        <div class="rList_titel"><a>Ausgeliehen</a></div>
        <div class="rList_availability"><img alt="Ausgeliehen"></div>
        <div class="rList_medium"><img alt="Buch"></div>
      </li>
      <li class="rList_li" data-ajax="AK2">
        <div class="rList_titel"><a>Verfügbar</a></div>
        <div class="rList_availability"><img alt="Verfügbar"></div>
        <div class="rList_medium"><img alt="Buch"></div>
      </li>
      <li class="rList_li" data-ajax="AK3">
        <div class="rList_titel"><a>Unbekannt</a></div>
        <div class="rList_availability"><img alt="siehe Vollanzeige"></div>
        <div class="rList_medium"><img alt="Buch"></div>
      </li>
    </ul></body></html>
    """
    out = http._parse_hits(
        html, query="x", media="all", available_only=True, limit=2
    )
    assert [item["id"] for item in out["results"]] == ["AK2", "AK3"]


def test_enrich_hits_fills_signature_from_standort_ajax():
    html = (
        '<script>aDISAjax.URL = '
        '"/aDISWeb/app;jsessionid=X?service=aDISAjax/Y/$AjaxScript";</script>'
    )
    response = _FakeResponse(
        '{"aDISFields":{"HTMINC":[null,'
        '"<span class=\\"so-signatur\\">ZL 1</span>'
        '<span class=\\"so-verfuegbarkeit\\">Verfügbar</span>"]}}',
        "https://example.invalid/aDISWeb/app",
    )
    session = _FakeSession([response])
    results = [
        {"id": "AK1", "signature": "", "media_type": "book", "available": None}
    ]

    http._enrich_hits(
        session, html, results, base_url="https://example.invalid/hshn", timeout=1
    )

    assert results[0]["signature"] == "ZL 1"
    assert results[0]["available"] is True


def test_login_session_opens_login_form_via_account_link(monkeypatch):
    session = _FakeSession(
        [
            _FakeResponse(_read("ux/home.html"), "http://x/aDISWeb/app?service=home"),
            _FakeResponse(
                _read("ux/login_synthetisch.html"),
                "http://x/aDISWeb/app?service=loginform",
            ),
            _FakeResponse(
                _read("ux/konto_synthetisch.html"),
                "http://x/aDISWeb/app?service=konto",
            ),
        ]
    )
    monkeypatch.setattr(http, "_build_session", lambda: session)

    result = http.login_session("123456789", "geheim", base_url="http://x")

    assert result["mock"] is False
    assert session.gets == ["http://x"]
    assert len(session.posts) == 2
    _url, account_payload = session.posts[0]
    assert account_payload["selected"] == "ZTEXT       *SBK"
    _url, login_payload = session.posts[1]
    assert login_payload["$Textfield"] == "123456789"
    assert login_payload["$Textfield$0"] == "geheim"
