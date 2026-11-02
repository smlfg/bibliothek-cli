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


def login_session(
    user: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = 30.0,
) -> dict:
    """Baut eine echte aDISWeb-Session über das Login-Formular auf."""
    s = _build_session()
    root = _root(base_url)
    try:
        home = s.get(root + "/", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Login: {exc}. Prüfe die Verbindung und "
            "BIBLIOTHEK_BASE_URL."
        ) from exc
    if home.status_code != 200:
        raise HttpError(
            f"Login-Formular nicht erreichbar: HTTP {home.status_code}. "
            "Prüfe BIBLIOTHEK_BASE_URL."
        )

    login_page = s.get(
        _app_url(home.url) + "?service=loginform",
        timeout=timeout,
        allow_redirects=True,
    )
    if login_page.status_code != 200:
        raise HttpError(
            f"Anmeldemaske nicht erreichbar: HTTP {login_page.status_code}. "
            "Prüfe BIBLIOTHEK_BASE_URL."
        )
    try:
        details = _form_details(login_page.text, login_page.url)
    except ParseError as exc:
        raise ParseError(
            "Anmeldemaske ohne Formular. Prüfe BIBLIOTHEK_BASE_URL."
        ) from exc

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


def bootstrap(base_url: str, timeout: float = 30.0) -> tuple[requests.Session, str]:
    """Holt eine JSESSIONID und liefert (Session, action-URL)."""
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
            f"bootstrap fehlgeschlagen: HTTP {r.status_code} von {url}. "
            "Prüfe BIBLIOTHEK_BASE_URL."
        )
    try:
        action, _service, _sp = _extract_form_context(r.text, r.url)
    except ParseError as exc:
        raise ParseError(
            "Form-action nicht gefunden (kein aDISWeb-Formular). "
            "Prüfe BIBLIOTHEK_BASE_URL."
        ) from exc
    LOG.info("bootstrap OK: %s", action)
    return s, action


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

    s, _action = bootstrap(base_url, timeout=timeout)
    root = _root(base_url)
    try:
        page = s.get(root + "/", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden der Suchmaske: {exc}. Prüfe die "
            "Verbindung."
        ) from exc
    action, service, sp = _extract_form_context(page.text, page.url)

    payload: dict[str, str] = {
        "service": service,
        "sp": sp or "S0",
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
    try:
        r = s.post(action, data=payload, timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler bei der Suche: {exc}. Prüfe die Verbindung."
        ) from exc
    if r.status_code != 200:
        raise HttpError(
            f"Suche fehlgeschlagen: HTTP {r.status_code}. Versuche es später "
            "erneut."
        )

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


def _parse_detail(html: str, record_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    heading = soup.find("h1")
    if heading is not None:
        title = heading.get_text(" ", strip=True)
    authors: list[str] = []
    if " / " in title:
        title, rest = title.split(" / ", 1)
        authors = [part.strip() for part in rest.split(";") if part.strip()]

    meta: dict[str, str] = {}
    for dl in soup.find_all("dl"):
        terms = dl.find_all("dt")
        values = dl.find_all("dd")
        for term, value in zip(terms, values):
            meta[term.get_text(" ", strip=True).casefold()] = value.get_text(
                " ", strip=True
            )

    body_text = soup.get_text(" ", strip=True)
    year = ""
    match = re.search(r",\s*(\d{4})\b", body_text)
    if match:
        year = match.group(1)

    isbn = meta.get("isbn", "")
    subjects = [
        part.strip()
        for part in re.split(r"[,;]", meta.get("schlagwörter", ""))
        if part.strip()
    ]
    media_type = meta.get("medienart", "").strip("[] ")

    locations: list[dict[str, str]] = []
    for row in soup.select("table tbody tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all("td")]
        if len(cells) < 3:
            continue
        locations.append(
            {
                "library": cells[0],
                "location": cells[1],
                "signature": cells[2],
                "status": cells[-1],
            }
        )
    signature = locations[0]["signature"] if locations else ""
    location_lines = []
    for loc in locations:
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
        "publisher": _publisher_line(soup),
        "year": year,
        "isbn": isbn,
        "subjects": subjects,
        "media_type": media_type,
        "signature": signature,
        "locations": location_lines,
    }


def _publisher_line(soup) -> str:
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if " : " in text and re.search(r"\b(19|20)\d{2}\b", text):
            return text
    return ""


def detail(
    record_id: str,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = 30.0,
) -> dict:
    """Lädt die Vollanzeige zu einer Datensatz-ID."""
    s, _action = bootstrap(base_url, timeout=timeout)
    root = _root(base_url)
    try:
        page = s.get(root + "/", timeout=timeout, allow_redirects=True)
    except requests.RequestException as exc:
        raise HttpError(
            f"Netzwerkfehler beim Laden der Vollanzeige: {exc}. Prüfe die "
            "Verbindung."
        ) from exc
    details = _form_details(page.text, page.url)
    payload = dict(details["hidden"])
    payload["service"] = "detail"
    payload["sp"] = details["sp"] or "S0"
    payload["selected"] = record_id
    payload.setdefault("keyCode", "0")
    payload["scriptEnabled"] = "T"
    action = _app_url(page.url) + "?service=detail"
    try:
        r = s.post(action, data=payload, timeout=timeout, allow_redirects=True)
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
    return _parse_detail(r.text, record_id)


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
        home = s.get(root + "/", timeout=timeout, allow_redirects=True)
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
