import getpass
import json
import sys

from .client import extract_fid, fetch_items, post_form
from .config import load_config, remove_config, save_config


def _aborted(message="Abgebrochen."):
    print("\n" + message)
    return 130


def login() -> int:
    try:
        email = input("E-Mail: ")
        password = getpass.getpass("Passwort: ")
        vorname = input("Vorname: ")
        nachname = input("Nachname: ")
    except (EOFError, KeyboardInterrupt):
        return _aborted()
    save_config(
        {
            "email": email,
            "password": password,
            "vorname": vorname,
            "nachname": nachname,
            "status": "",
        }
    )
    print("Gespeichert.")
    return 0


def logout() -> int:
    remove_config()
    print("Abgemeldet.")
    return 0


def search(name: str, as_json: bool) -> int:
    items = fetch_items(name)
    if as_json or not sys.stdout.isatty():
        print(json.dumps(items, ensure_ascii=False))
        return 0
    for item in items:
        print(f'{item["id"]}  {item["name"]}  {item["preis"]}')
    return 0


def _choose(items):
    if len(items) == 1:
        return items[0]
    for number, item in enumerate(items, start=1):
        print(f'{number}  {item["id"]}  {item["name"]}  {item["preis"]}')
    try:
        answer = input("Auswahl: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAbgebrochen, nichts gebucht.")
        return None
    try:
        index = int(answer)
    except ValueError:
        print("Ungültige Auswahl.")
        return None
    if not 1 <= index <= len(items):
        print("Ungültige Auswahl.")
        return None
    return items[index - 1]


def book(name: str, assume_yes: bool) -> int:
    config = load_config()
    items = fetch_items(name)
    if not items:
        print("Keine Treffer.")
        return 1
    item = _choose(items)
    if item is None:
        return 0

    post_form({"item": item["id"]})
    print(f'Kurs: {item["name"]} ({item["preis"]})')
    if config:
        print(f'Name: {config.get("vorname", "")} {config.get("nachname", "")}')
        print(f'Statusgruppe: {config.get("status", "")}')

    if not assume_yes:
        try:
            answer = input("Verbindlich buchen? [j/N] ")
        except (EOFError, KeyboardInterrupt):
            print("\nAbgebrochen, nichts gebucht.")
            return 0
        if answer.strip().lower() not in ("j", "ja"):
            print("Abgebrochen, nichts gebucht.")
            return 0

    if not config:
        print("Login fehlt – nochecktool login ausführen")
        return 2

    overview = post_form(
        {
            "item": item["id"],
            "vorname": config.get("vorname", ""),
            "name": config.get("nachname", ""),
            "status": config.get("status", ""),
        }
    )
    fid = extract_fid(overview)
    if not fid:
        print("Bestätigungscode fehlt.")
        return 1
    post_form({"fid": fid})
    print("Gebucht.")
    return 0
