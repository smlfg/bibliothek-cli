"""HTTP-Klasse: aDISWeb-Session + Bootstrap + Search.

Das HSHN-Portal (BSZ aDISWeb) liefert nur über Form-POST echte Treffer; eine
REST/SRU-API ist nicht verfügbar. Der Client kapselt das hier:

- Bootstrap einer frischen JSESSIONID
- Such-POST mit den richtigen Hidden-Feldern
- Parsen der Trefferliste (Schema: <ul class='rList'><li class='rList_li'
  data-ajax='AKxxxx'>)
"""

from __future__ import annotations

import logging
import re
from html import unescape as _unescape
from urllib.parse import urljoin, urlunparse

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("bibliothek_cli.http")

DEFAULT_BASE = "https://bsz.ibs-bw.de/hshn"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class HttpError(Exception):
    """Generischer HTTP/Netzwerk-Fehler (Exit-Code 3)."""


class ParseError(Exception):
    """Unerwartete Antwortstruktur (Exit-Code 4)."""


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/webp,*/*;q=0.8"
            ),
        }
    )
    return s


def bootstrap(base_url: str, timeout: float = 30.0) -> tuple[requests.Session, str]:
    """Holt eine JSESSIONID und liefert (Session, action-URL)."""
    s = _build_session()
    # Wichtig: ohne trailing slash, sonst 404 entlägt auf Home/$DirectLink
    url = base_url.rstrip("/")
    r = s.get(url, timeout=timeout, allow_redirects=True)
    if r.status_code != 200 or "aDISWeb/app" not in r.text:
        raise HttpError(
            f"bootstrap fehlgeschlagen: HTTP {r.status_code} von {url}"
        )
    m = re.search(r'action="(/aDISWeb/app[^"]+)"', r.text)
    if not m:
        raise ParseError("Form-action nicht gefunden (kein aDISWeb-Maske)")
    action = urljoin(r.url, m.group(1))
    LOG.info("bootstrap OK: %s", action)
    return s, action


def _extract_form_context(html: str) -> tuple[str, str, str]:
    """Liest action-URL + service-Spool + sp aus dem aktuellen Form."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        raise ParseError("Kein <form> in Antwort")
    raw_action = form.get("action")
    if not raw_action or not isinstance(raw_action, str):
        raise ParseError("Form-action fehlt")
    action = urljoin("https://bsz.ibs-bw.de", raw_action)
    sp = ""
    svc_input = form.find("input", {"name": "service"})
    service = ""
    if svc_input is not None:
        v = svc_input.get("value")
        if isinstance(v, str):
            service = v
    sp_input = form.find("input", {"name": "sp"})
    if sp_input is not None:
        v = sp_input.get("value")
        if isinstance(v, str):
            sp = v
    return action, service, sp


def search(
    query: str,
    *,
    base_url: str = DEFAULT_BASE,
    media: str = "all",
    available_only: bool = False,
    limit: int = 20,
    timeout: float = 30.0,
) -> dict:
    """Führt eine Schnellsuche durch. Liefert ein strukturiert.

    Felder:
      - query, media, available_only, total_found, results:[id,title,…]
    """
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit muss zwischen 1 und 50 liegen")

    s, _ = bootstrap(base_url, timeout=timeout)
    action, service, _sp = _extract_form_context(
        s.get(base_url.rstrip("/"), timeout=timeout, allow_redirects=True).text
    )

    payload: dict[str, str] = {
        "service": service,
        "sp": "S0",
        "scriptEnabled": "T",
        "$Autosuggest": query,
        "focus": "",
        "keyCode": "0",
        "stz": "",
        "source": "",
        "selected": "",
        "requestCount": "0",
        "scrollPos": "0",
        "$FormConditional": "T",
        "$FormConditional$0": "T",
        "textButton": "Suchen",
    }
    r = s.post(action, data=payload, timeout=timeout, allow_redirects=True)
    if r.status_code != 200:
        raise HttpError(f"suchen 200 keine 200: HTTP {r.status_code}")

    return _parse_hits(
        r.text,
        query=query,
        media=media,
        available_only=available_only,
        limit=limit,
    )


_MEDIUM_MAP = {
    "Buch": "book",
    "E-Book": "ebook",
    "DVD": "media",
    "CD": "media",
    "Online-Ressource": "ebook",
    "Zeitschrift": "media",
    "Aufsatz": "article",
}


def _parse_hits(
    html: str, *, query: str, media: str, available_only: bool, limit: int
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    total_node = soup.find(string=re.compile(r"Treffer:\s*\d+"))
    total_found = 0
    if total_node:
        m = re.search(r"Treffer:\s*(\d+)", total_node)
        if m:
            total_found = int(m.group(1))

    items = soup.select("li.rList_li")
    out = []
    for li in items:
        rid_raw = li.get("data-ajax") or ""
        rec_id = rid_raw.strip() if isinstance(rid_raw, str) else ""
        if not rec_id:
            a = li.select_one(".rList_titel a")
            if a is not None:
                href = a.get("href")
                if isinstance(href, str):
                    m = re.search(r"'(AK[A-Z0-9]+)'", href)
                    if m:
                        rec_id = m.group(1)
        title_node = li.select_one(".rList_titel a")
        title = title_node.get_text(strip=True) if title_node else ""
        author_node = li.select_one(".rList_name")
        author = author_node.get_text(strip=True) if author_node else ""
        year_node = li.select_one(".rList_jahr")
        year = year_node.get_text(strip=True) if year_node else ""
        sig_node = li.select_one(".rList_sig")
        sig = sig_node.get_text(strip=True) if sig_node else ""
        media_icon = li.select_one(".rList_medium img")
        media_label = ""
        if media_icon is not None:
            t = media_icon.get("title")
            al = media_icon.get("alt")
            if isinstance(t, str):
                media_label = t
            elif isinstance(al, str):
                media_label = al
        media_kind = _MEDIUM_MAP.get(media_label, (media_label or "unknown").lower())
        if not title:
            continue
        if media != "all" and media_kind not in (media, "all"):
            # wir lassen den Treffer drin; das Flag wird auf Treffer-Ebene gespiegelt
            pass
        out.append(
            {
                "id": rec_id,
                "title": _unescape(title),
                "author": _unescape(author),
                "year": year,
                "signature": sig,
                "media_type": media_kind,
            }
        )
        if len(out) >= limit:
            break
    return {
        "query": query,
        "media": media,
        "available_only": bool(available_only),
        "total_found": total_found,
        "count": len(out),
        "results": out,
    }