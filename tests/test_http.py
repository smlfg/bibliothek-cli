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