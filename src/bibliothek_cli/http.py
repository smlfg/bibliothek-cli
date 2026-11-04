"""HTTP-Klasse: aDISWeb-Session + Bootstrap + Search.

Das HSHN-Portal (BSZ aDISWeb) liefert nur über Form-POST echte Treffer; eine
REST/SRU-API ist nicht verfügbar. Der Client kapselt hier:

- Bootstrap einer frischen JSESSIONID
- Such-POST mit den richtigen Hidden-Feldern
- Parsen von Trefferliste, Vollanzeige und Konto/Ausleihen
"""

from __future__ import annotations

import logging
import re
from html import unescape as _unescape
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("bibliothek_cli.http")

DEFAULT_BASE = "https://bsz.ibs-bw.de/hshn"
APP_PATH = "/aDISWeb/app"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class HttpError(Exception):
    """Generischer HTTP/Netzwerk-Fehler (Exit-Code 3)."""


class ParseError(Exception):
    """Unerwartete Antwortstruktur (Exit-Code 4)."""


class AuthError(Exception):
    """Login/Session fehlt, ist ungültig oder abgelaufen (Exit-Code 2)."""


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


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _app_url(url: str) -> str:
    return _origin(url) + APP_PATH


def _session_from_cookies(
    cookies: dict[str, str] | None, base_url: str
) -> requests.Session:
    s = _build_session()
    host = urlsplit(base_url).hostname or ""
    for name, value in (cookies or {}).items():
        if not name:
            continue
        try:
            s.cookies.set(str(name), str(value), domain=host or None, path="/")
        except Exception:  # noqa: BLE001 - defekte Cookies ignorieren
            continue
    return s


def _form_details(html: str, base_url: str = DEFAULT_BASE) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if form is None:
        raise ParseError("Kein Formular in der Antwort gefunden.")
    raw_action = form.get("action")
    if not raw_action or not isinstance(raw_action, str):
        raise ParseError("Formular ohne action-URL in der Antwort.")
    hidden: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        kind = str(inp.get("type") or "text").lower()
        if kind in {"hidden", "submit"}:
            value = inp.get("value")
            hidden[str(name)] = str(value) if value is not None else ""
    service = hidden.get("service", "")
    sp = hidden.get("sp", "")
    return {
        "action": urljoin(base_url, raw_action),
        "service": service,
        "sp": sp,
        "hidden": hidden,
        "form": form,
    }


def _extract_form_context(
    html: str, base_url: str = DEFAULT_BASE
) -> tuple[str, str, str]:
    """Liest action-URL + service-Spool + sp aus dem aktuellen Form."""
    details = _form_details(html, base_url)
    return details["action"], details["service"], details["sp"]


def _is_konto_page(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string)
    for node in soup.find_all(["h1", "h2", "h3"]):
        parts.append(node.get_text(" ", strip=True))
    text = " ".join(parts).casefold()
    if "ausleihen" in text or "mein konto" in text:
        return True
    if "konto" in text and "anmelden" not in text:
        return True
    return False


def _login_field_names(form) -> tuple[str, str]:
    user = ""
    password = ""
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        kind = str(inp.get("type") or "text").lower()
        if kind == "password" and not password:
            password = str(name)
        elif kind in {"text", "search", "email", "tel"} and not user:
            user = str(name)
        elif inp.get("autocomplete") == "username" and not user:
            user = str(name)
    return user or "$Textfield", password or "$Textfield$0"


def _has_password_field(form) -> bool:
    for inp in form.find_all("input"):
        if str(inp.get("type") or "").lower() == "password":
            return True
    return False


def _login_form(html: str, url: str) -> dict | None:
    try:
        details = _form_details(html, url)
    except ParseError:
        return None
    return details if _has_password_field(details["form"]) else None


def login_session(
    user: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = 30.0,
) -> dict:
    """Baut eine echte aDISWeb-Session über das Login-Formular auf."""
    s, home = _open_catalog(base_url, timeout=timeout)

    account_payload = _hidden_inputs(home["form"])
    account_payload["selected"] = "ZTEXT       *SBK"
    account_payload["keyCode"] = "0"
    account_payload["scriptEnabled"] = "T"
    account_payload["scrollPos"] = "0"
    try:
        login_page = s.post(
            home["action"], data=account_payload, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Login: {exc}. Prüfe die Verbindung und "
            "BIBLIOTHEK_BASE_URL."
        ) from exc
    if login_page.status_code != 200:
        raise HttpError(
            f"Login-Formular nicht erreichbar: HTTP {login_page.status_code}. "
            "Prüfe BIBLIOTHEK_BASE_URL."
        )
    details = _login_form(login_page.text, login_page.url)

    if details is None:
        # Ältere aDISWeb-Installationen und der Fake-Server liefern die Maske
        # direkt über service=loginform.
        try:
            login_page = s.get(
                _app_url(home["action"]) + "?service=loginform",
                timeout=timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise HttpError(
                f"Netzwerkfehler beim Login: {exc}. Prüfe die Verbindung."
            ) from exc
        if login_page.status_code != 200:
            raise HttpError(
                f"Anmeldemaske nicht erreichbar: HTTP {login_page.status_code}. "
                "Prüfe BIBLIOTHEK_BASE_URL."
            )
        details = _login_form(login_page.text, login_page.url)
    if details is None:
        raise ParseError(
            "Anmeldemaske ohne Formular. Prüfe BIBLIOTHEK_BASE_URL."
        )

    payload = dict(details["hidden"])
    user_field, password_field = _login_field_names(details["form"])
    payload[user_field] = user
    payload[password_field] = password
    payload.setdefault("scriptEnabled", "T")
    payload["textButton"] = "Anmelden"

    try:
        response = s.post(
            details["action"],
            data=payload,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Login: {exc}. Prüfe die Verbindung."
        ) from exc
    if response.status_code != 200:
        raise HttpError(
            f"Login fehlgeschlagen: HTTP {response.status_code}. "
            "Prüfe BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD."
        )
    if not _is_konto_page(response.text):
        raise AuthError(
            "Login nicht bestätigt: Kontoseite nicht sichtbar. Prüfe "
            "Ausweisnummer und Passwort und starte `bibliothek login` erneut."
        )
    cookies = {cookie.name: cookie.value for cookie in s.cookies}
    LOG.info("login OK für %s", user)
    return {"cookies": cookies, "mock": False}


def _open_catalog(
    base_url: str, timeout: float = 30.0
) -> tuple[requests.Session, dict]:
    """Lädt die Startseite ohne erzwingenden Schrägstrich am Ende.

    ``https://bsz.ibs-bw.de/hshn/`` antwortet inzwischen mit HTTP 404, während
    ``/hshn`` per 301 auf die eigentliche aDISWeb-Startseite umleitet.
    """
    s = _build_session()
    url = _root(base_url)
    try:
        r = s.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden des Katalogs: {exc}. Prüfe die "
            "Verbindung und BIBLIOTHEK_BASE_URL."
        ) from exc
    if r.status_code != 200 or "aDISWeb/app" not in r.text:
        raise HttpError(
            f"Katalog nicht erreichbar: HTTP {r.status_code} von {url}. "
            "Prüfe BIBLIOTHEK_BASE_URL."
        )
    try:
        details = _form_details(r.text, r.url)
    except ParseError as exc:
        raise ParseError(
            "Form-action nicht gefunden (kein aDISWeb-Formular). "
            "Prüfe BIBLIOTHEK_BASE_URL."
        ) from exc
    return s, details


def bootstrap(base_url: str, timeout: float = 30.0) -> tuple[requests.Session, str]:
    """Holt eine JSESSIONID und liefert (Session, action-URL)."""
    s, details = _open_catalog(base_url, timeout=timeout)
    LOG.info("bootstrap OK: %s", details["action"])
    return s, details["action"]


def _search_payload(details: dict, query: str) -> dict[str, str]:
    return {
        "service": details["service"],
        "sp": details["sp"] or "S0",
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


def _post_search(
    session: requests.Session, details: dict, query: str, timeout: float
) -> requests.Response:
    try:
        return session.post(
            details["action"],
            data=_search_payload(details, query),
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler bei der Suche: {exc}. Prüfe die Verbindung."
        ) from exc


def search(
    query: str,
    *,
    base_url: str = DEFAULT_BASE,
    media: str = "all",
    available_only: bool = False,
    limit: int = 20,
    timeout: float = 30.0,
) -> dict:
    """Führt eine Schnellsuche durch und liefert strukturierte Treffer."""
    if not 1 <= int(limit) <= 50:
        raise ValueError("limit muss zwischen 1 und 50 liegen")

    s, details = _open_catalog(base_url, timeout=timeout)
    r = _post_search(s, details, query, timeout)
    if r.status_code != 200:
        raise HttpError(
            f"Suche fehlgeschlagen: HTTP {r.status_code}. Versuche es später "
            "erneut."
        )

    result = _parse_hits(
        r.text,
        query=query,
        media=media,
        available_only=available_only,
        limit=limit,
    )
    _enrich_hits(
        s, r.text, result["results"], base_url=base_url, timeout=timeout
    )
    return result


_MEDIUM_MAP = {
    "Buch": "book",
    "E-Book": "ebook",
    "DVD": "media",
    "CD": "media",
    "Online-Ressource": "ebook",
    "Zeitschrift": "media",
    "Aufsatz": "article",
}


def _clean_author(text: str) -> str:
    """Entfernt Auflage/Verlag aus dem Listenfeld und dreht Name, Vorname.

    aDISWeb schreibt in ``.rList_name`` oft
    ``Vorname Nachname. - Auflage. - Verlag``. Für die UX-Spec zählt nur der
    Verfassername, bei einer einzelnen Person in der Form ``Nachname, Vorname``.
    """
    value = _unescape(text).strip()
    if not value:
        return ""
    value = re.sub(r"^(?:von|by)\s+", "", value, flags=re.IGNORECASE)
    value = re.split(r"\.\s+-\s+", value, maxsplit=1)[0]
    value = re.sub(r"\s*\[[^\]]*\]\s*$", "", value)
    value = re.sub(r"\s*\((?:Hrsg|Hg)\.?\)\s*$", "", value, flags=re.IGNORECASE)
    value = value.strip()
    if "," not in value and ";" not in value:
        parts = value.split()
        if len(parts) >= 2:
            value = f"{parts[-1]}, {' '.join(parts[:-1])}"
    return value


def _availability(li) -> bool | None:
    """Liest die Verfügbarkeit aus dem Icon der Trefferliste."""
    node = li.select_one(".rList_availability img")
    if node is None:
        return None
    label = ""
    for attr in ("alt", "title"):
        value = node.get(attr)
        if isinstance(value, str) and value.strip():
            label = value.strip().casefold()
            break
    if "verfügbar" in label and "nicht" not in label:
        return True
    if "ausgeliehen" in label or "nicht verfügbar" in label:
        return False
    return None


def _parse_hits(
    html: str, *, query: str, media: str, available_only: bool, limit: int
) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    total_node = soup.find(string=re.compile(r"Treffer:\s*\d+"))
    total_found = 0
    if total_node:
        m = re.search(r"Treffer:\s*(\d+)", str(total_node))
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
        if sig in {"\xa0", "&nbsp;"}:
            sig = ""
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
        if media != "all" and media_kind != media:
            continue
        out.append(
            {
                "id": rec_id,
                "title": _unescape(title),
                "author": _clean_author(author),
                "year": year,
                "signature": sig,
                "media_type": media_kind,
                "available": _availability(li),
            }
        )

    if available_only:
        out.sort(key=lambda item: {True: 0, None: 1, False: 2}[item["available"]])
    out = out[:limit]
    return {
        "query": query,
        "media": media,
        "available_only": bool(available_only),
        "total_found": total_found,
        "count": len(out),
        "results": out,
    }


def _standort_info(
    session: requests.Session, ajax_url: str, record_id: str, timeout: float
) -> dict:
    """Holt Signatur/Verfügbarkeit eines Treffers über den Standort-AJAX."""
    try:
        response = session.get(
            ajax_url,
            params={
                "aDISContext": "ID    BM3600",
                "aDISTimeout": "5000",
                "ID": record_id,
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=timeout,
        )
    except requests.RequestException:
        return {}
    if response.status_code != 200:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {}
    fields = payload.get("aDISFields") or {}
    raw = fields.get("HTMINC") or []
    html = raw[1] if len(raw) > 1 and raw[1] else ""
    if not html:
        return {}
    soup = BeautifulSoup(str(html), "html.parser")
    result: dict = {}
    sig = soup.select_one(".so-signatur")
    if sig is not None:
        result["signature"] = sig.get_text(" ", strip=True)
    avail = soup.select_one(".so-verfuegbarkeit")
    if avail is not None:
        label = avail.get_text(" ", strip=True).casefold()
        if "verfügbar" in label and "nicht" not in label:
            result["available"] = True
        elif "ausgeliehen" in label or "nicht verfügbar" in label:
            result["available"] = False
    return result


def _enrich_hits(
    session: requests.Session,
    html: str,
    results: list[dict],
    *,
    base_url: str,
    timeout: float,
) -> None:
    """Ergänzt fehlende Signaturen aus dem Standort-Panel (nur lesend)."""
    match = re.search(r'aDISAjax\.URL\s*=\s*"([^"]+)"', html)
    if not match:
        return
    from urllib.parse import urljoin

    ajax_url = urljoin(base_url, match.group(1))
    for item in results:
        if item.get("signature") or item.get("media_type") == "ebook":
            continue
        rid = item.get("id") or ""
        if not rid:
            continue
        info = _standort_info(session, ajax_url, rid, timeout)
        if info.get("signature") and not item.get("signature"):
            item["signature"] = info["signature"]
        if item.get("available") is None and "available" in info:
            item["available"] = info["available"]


def _detail_meta(soup) -> dict[str, str]:
    """Sammelt Metadaten aus Definitionslisten und aDISWeb-Wertetabellen."""
    meta: dict[str, str] = {}
    for dl in soup.find_all("dl"):
        terms = dl.find_all("dt")
        values = dl.find_all("dd")
        for term, value in zip(terms, values):
            meta[term.get_text(" ", strip=True).casefold()] = value.get_text(
                " ", strip=True
            )
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            terms = row.find_all("th")
            values = row.find_all("td")
            if len(terms) != 1 or len(values) != 1:
                continue
            key = terms[0].get_text(" ", strip=True).casefold()
            if key:
                meta.setdefault(key, values[0].get_text(" ", strip=True))
    return meta


def _clean_person(text: str) -> str:
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip(" ;")


def _parse_detail(html: str, record_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = _detail_meta(soup)

    title = meta.get("titel", "")
    if not title:
        heading = soup.find("h1")
        if heading is not None:
            text = heading.get_text(" ", strip=True)
            if not text.casefold().startswith("aktuelle seite"):
                title = text
    if not title:
        for heading in soup.find_all("h2"):
            text = heading.get_text(" ", strip=True)
            if text.casefold().startswith("aktuelle seite:"):
                title = text.split(":", 1)[1].strip()
                break

    authors: list[str] = []
    if " / " in title:
        title, rest = title.split(" / ", 1)
        authors = [
            _clean_author(part)
            for part in re.split(r"\s*;\s*", rest)
            if part.strip()
        ]

    person = meta.get("person") or meta.get("personen") or ""
    if person:
        authors = [
            _clean_person(part)
            for part in re.split(r"\s*;\s*", person)
            if _clean_person(part)
        ]

    publication = meta.get("veröffentlichung") or meta.get("erscheinungsjahr") or ""
    body_text = soup.get_text(" ", strip=True)
    year = ""
    match = re.search(r"\b(19|20)\d{2}\b", publication or body_text)
    if match:
        year = match.group(0)

    isbn = meta.get("isbn", "")
    subjects = [
        part.strip()
        for part in re.split(r"[,;]", meta.get("schlagwörter", ""))
        if part.strip()
    ]
    media_type = meta.get("medienart", "").strip("[] ")

    copies: list[dict[str, str]] = []
    for row in soup.select("table tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 3 or cells[0].casefold() == "bibliothek":
            continue
        status = cells[-1]
        due_match = re.search(
            r"fällig am:?\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            status,
            flags=re.IGNORECASE,
        )
        copies.append(
            {
                "library": cells[0],
                "location": cells[1],
                "signature": cells[2],
                "status": status,
                "due": due_match.group(1) if due_match else "",
            }
        )
    signature = copies[0]["signature"] if copies else ""
    location_lines = []
    for loc in copies:
        line = ", ".join(
            part for part in (loc.get("library"), loc.get("location")) if part
        )
        if loc.get("signature"):
            line += f" | Signatur {loc['signature']}"
        if loc.get("status"):
            line += f" | {loc['status']}"
        location_lines.append(line)

    hidden_id = ""
    form = soup.find("form")
    if form is not None:
        selected = form.find("input", {"name": "selected"})
        if selected is not None:
            value = selected.get("value")
            if isinstance(value, str):
                hidden_id = value.strip()
    return {
        "id": hidden_id or record_id,
        "title": _unescape(title),
        "authors": authors,
        "publisher": publication or _publisher_line(soup),
        "year": year,
        "isbn": isbn,
        "subjects": subjects,
        "media_type": media_type,
        "signature": signature,
        "locations": location_lines,
        "copies": copies,
    }


def _publisher_line(soup) -> str:
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if " : " in text and re.search(r"\b(19|20)\d{2}\b", text):
            return text
    return ""


def _hidden_inputs(form) -> dict[str, str]:
    payload: dict[str, str] = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        kind = str(inp.get("type") or "text").lower()
        if kind != "hidden":
            continue
        value = inp.get("value")
        payload[str(name)] = str(value) if value is not None else ""
    return payload


def _is_session_end(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    nodes = [soup.title, *soup.find_all(["h1", "h2", "h3"])]
    for node in nodes:
        if node is None:
            continue
        text = node.get_text(" ", strip=True).casefold()
        if "ende der sitzung" in text or "sitzung beendet" in text:
            return True
    return False


def detail(
    record_id: str,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = 30.0,
) -> dict:
    """Lädt die Vollanzeige zu einer Datensatz-ID.

    aDISWeb öffnet Details per Formular-Submit aus der Trefferliste: Das Feld
    ``selected`` enthält ``"ZTEXT       <ID>"``. Die action-URL inklusive
    ``;jsessionid=…`` muss dabei unverändert bleiben.
    """
    s, details = _open_catalog(base_url, timeout=timeout)
    search_response = _post_search(s, details, record_id, timeout)
    if search_response.status_code != 200:
        raise HttpError(
            f"Trefferliste für {record_id} nicht erreichbar: HTTP "
            f"{search_response.status_code}. Versuche es später erneut."
        )
    try:
        page_details = _form_details(search_response.text, search_response.url)
    except ParseError as exc:
        raise ParseError(
            "Trefferliste ohne Formular; die Vollanzeige ist nicht erreichbar. "
            "Prüfe die ID oder nutze `bibliothek search SUCHBEGRIFF`."
        ) from exc

    payload = _hidden_inputs(page_details["form"])
    payload["selected"] = f"ZTEXT       {record_id}"
    payload["keyCode"] = "0"
    payload["scriptEnabled"] = "T"
    payload["scrollPos"] = "0"
    try:
        r = s.post(
            page_details["action"],
            data=payload,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden der Vollanzeige: {exc}. Prüfe die "
            "Verbindung."
        ) from exc
    if r.status_code != 200:
        raise HttpError(
            f"Vollanzeige fehlgeschlagen: HTTP {r.status_code}. Versuche es "
            "später erneut."
        )
    if _is_session_end(r.text):
        raise ParseError(
            "Vollanzeige lieferte „Ende der Sitzung“ statt eines Datensatzes. "
            "Starte `bibliothek show` erneut."
        )
    parsed = _parse_detail(r.text, record_id)
    if not parsed.get("title"):
        raise ParseError(
            "Vollanzeige ohne Titel erkannt. Prüfe die ID oder nutze "
            "`bibliothek search SUCHBEGRIFF`."
        )
    return parsed


def _parse_loans(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    loans: list[dict] = []
    for index, box in enumerate(
        soup.find_all("input", attrs={"name": re.compile(r"cellCheck\$")})
    ):
        name = str(box.get("name") or f"cellCheck${index}")
        value = str(box.get("value") or "").strip()
        row = box.find_parent("tr")
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")] if row else []
        title = cells[1] if len(cells) > 1 else ""
        due = cells[2] if len(cells) > 2 else ""
        renewals = 0
        if len(cells) > 3:
            match = re.search(r"\d+", cells[3])
            if match:
                renewals = int(match.group(0))
        loans.append(
            {
                "id": value or name,
                "title": title,
                "due": due,
                "renewals": renewals,
                "can_renew": True,
                "checkbox": name,
            }
        )
    return loans


def load_konto(
    cookies: dict[str, str] | None,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = 30.0,
) -> dict:
    """Lädt die Kontoseite und parst die Ausleihen."""
    s = _session_from_cookies(cookies, base_url)
    root = _root(base_url)
    try:
        home = s.get(root, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden des Kontos: {exc}. Prüfe die "
            "Verbindung."
        ) from exc
    if home.status_code != 200:
        raise HttpError(
            f"Konto nicht erreichbar: HTTP {home.status_code}. Versuche es "
            "später erneut."
        )
    try:
        details = _form_details(home.text, home.url)
    except ParseError as exc:
        raise ParseError(
            "Kontoseite ohne Formular. Prüfe BIBLIOTHEK_BASE_URL."
        ) from exc
    payload = dict(details["hidden"])
    payload["service"] = details["service"] or "renew"
    payload["sp"] = details["sp"] or "S0"
    payload["selected"] = ""
    action = _app_url(home.url)
    try:
        response = s.post(action, data=payload, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden der Ausleihen: {exc}. Prüfe die "
            "Verbindung."
        ) from exc
    if response.status_code != 200:
        raise HttpError(
            f"Ausleihen nicht abrufbar: HTTP {response.status_code}. "
            "Versuche es später erneut."
        )
    if not _is_konto_page(response.text):
        raise AuthError(
            "Session ungültig oder abgelaufen. Führe `bibliothek login` erneut "
            "aus."
        )
    try:
        form = _form_details(response.text, response.url)
    except ParseError as exc:
        raise ParseError(
            "Kontoantwort ohne Verlängerungsformular. Versuche es später erneut."
        ) from exc
    return {"loans": _parse_loans(response.text), "form": form, "session": s}


def _extract_new_due(html: str) -> str:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    for pattern in (
        r"Neues Fälligkeitsdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
        r"Neue Frist:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
        r"Fällig am:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def renew_loan(konto: dict, loan: dict, *, timeout: float = 30.0) -> dict:
    """Sendet alle Formularschritte der Verlängerung bis zur Bestätigung."""
    session: requests.Session = konto["session"]
    form: dict = konto["form"]

    payload = dict(form["hidden"])
    payload["service"] = form["service"] or "renew"
    payload["sp"] = form["sp"] or "S0"
    payload["selected"] = loan["id"]
    checkbox = loan.get("checkbox") or "cellCheck$0"
    payload[checkbox] = loan["id"]
    payload["textButton$1"] = "Verlängern"

    try:
        response = session.post(
            form["action"], data=payload, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Verlängern: {exc}. Prüfe die Verbindung."
        ) from exc
    if response.status_code != 200:
        raise HttpError(
            f"Verlängern fehlgeschlagen: HTTP {response.status_code}. Versuche "
            "es später erneut."
        )
    try:
        confirm_form = _form_details(response.text, response.url)
    except ParseError as exc:
        raise ParseError(
            "Bestätigungsseite der Verlängerung nicht erkannt. Versuche es "
            "später erneut."
        ) from exc

    payload2 = dict(confirm_form["hidden"])
    payload2["service"] = confirm_form["service"] or payload["service"]
    payload2["sp"] = confirm_form["sp"] or payload["sp"]
    payload2.setdefault("bestaetigungstoken", "")
    payload2["textButton"] = "Verlängern"
    try:
        final = session.post(
            confirm_form["action"],
            data=payload2,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler bei der Bestätigung: {exc}. Prüfe die Verbindung."
        ) from exc
    if final.status_code != 200:
        raise HttpError(
            f"Bestätigung fehlgeschlagen: HTTP {final.status_code}. Versuche "
            "es später erneut."
        )
    new_due = _extract_new_due(final.text)
    if not new_due:
        raise ParseError(
            "Verlängerung nicht bestätigt: kein neues Fälligkeitsdatum in der "
            "Antwort. Prüfe `bibliothek loans`."
        )
    return {
        "id": loan["id"],
        "title": loan.get("title", ""),
        "renewed": True,
        "new_due": new_due,
    }
