# Anforderungen – bibliothek-cli

Zielgruppe: Menschen im Terminal und KI-Agenten, die mit dem
LIV-Bibliothekskatalog (OPAC HHN/DHBW Heilbronn, BSZ/aDISWeb) interagieren,
ohne einen Browser zu öffnen.

## Nachfrage

- GO laut `LOG.md` vom 2026-10-14 (Eigenbedarf HHN).
- Es gibt kein CLI/MCP für aDISWeb; der OPAC ist nur browser-/formbasiert
  bedienbar.
- Quelle: Tool-Brief `bibliothek-cli` (Repo `smlfg/bibliothek-cli`, Typ `cli`,
  Login nötig, Nachrüstung eines bestehenden Tools).

## Funktionale Anforderungen

- Katalog-Suche gegen den öffentlichen OPAC (kein Login), Suchbegriff positional.
- Detail-Datensatz per Titel oder ID (Titel, Autor, Verlag, ISBN, Schlagworte,
  Standort, Signatur, Verfügbarkeit/Frist).
- Lokaler Keyword-Watch (Datei-basiert, `$XDG_CONFIG_HOME/bibliothek-cli`).
- `login` am Bibliothekskonto:
  - interaktiv im Terminal (Ausweisnummer, Passwort verdeckt per `getpass`);
  - für Agenten über `BIBLIOTHEK_USER` und `BIBLIOTHEK_PASSWORD` (nie
    CLI-Args, nie Anzeige, nie Logs);
  - echtes aDISWeb-Login-Formular; Erfolg erst bei sichtbarer Kontoseite;
  - Session-Cookies nur für die OPAC-Origin, persistent in
    `$XDG_CONFIG_HOME/bibliothek-cli/session.json` (Mode 0600).
- `whoami` zeigt die angemeldete Ausweisnummer ohne Passwort oder Cookies.
- `logout` löscht die Session idempotent.
- Ausleihen echt aus dem Konto lesen (`loans`, Alias `loans list`).
- Verlängern über den Titel, nicht über eine ID:
  - mehrere passende Ausleihen → nummerierte Auswahl im TTY;
  - Zusammenfassung mit Titel und Frist, dann
    `Verlängerung verbindlich? [j/N]` (Default Nein);
  - erst nach `j` werden alle aDISWeb-Formularschritte bis zur endgültigen
    Bestätigung gesendet;
  - `--confirm`/`--yes` nur für Agenten; `loans renew ID --confirm` bleibt als
    Alias erhalten;
  - ohne TTY und ohne Flag Abbruch vor jedem Request (Exit 5).
- Optional `vormerken` nach demselben Muster, sobald das Konto-Formular live
  erkundet ist; der derzeitige Live-Einstieg endet an der Anmeldemaske.
- `--help`/`--version` Standard mit Exit 0; Fehler nennen den nächsten Schritt,
  keine Tracebacks (auch nicht bei Strg+C/EOF).

## Sicherheit und Datenschutz

- Keine Zugangsdaten im Repo, in Fixtures oder Logs; Fixtures anonymisieren
  (Namen/Mails → `example.invalid`) und Konto-/Verlängerungsseiten als
  `SYNTHETISCH` kennzeichnen.
- Keine echten Schreibaktionen, Logins auf echten Konten oder
  Verlängerungen/Vormerkungen in Tests. Live nur lesende GET-/Form-Requests
  auf öffentliche OPAC-Seiten bis zur Login-Abfrage.
- Tests dürfen nie echte Server erreichen; die Basis-URL ist über
  `BIBLIOTHEK_BASE_URL` auf einen Fake-Server umstellbar.
- Keine erfundenen Personendaten, Lizenz MIT (Copyright smlfg).

## Nicht-funktionale Anforderungen

- Python >= 3.10, nur `argparse` + `httpx`/`requests` (+ `beautifulsoup4`).
- Konsistente Exit-Codes (0/1/2/3/4/5, siehe INTERFACE.md).
- `--json` produziert genau ein JSON-Objekt auf stdout, Logs/Prompts auf stderr.
- Kein Netzwerk in Unit-Tests; HTML-Fixtures decken den Parser ab.
- Akzeptanztests in `tests/acceptance/` spielen jede UX-Sitzung aus
  `docs/UX.md` gegen `tests/harness/fake_server.py` durch.
