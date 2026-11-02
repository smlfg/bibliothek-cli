# INTERFACE – bibliothek-cli

CLI: `bibliothek` (Paket `bibliothek-cli`, v0.1.0).

## Allgemein

- `--help` / `--version` (gedruckt auf stdout, exit 0).
- Globale Optionen: `--json` (genau ein JSON-Objekt auf stdout, Logs auf stderr),
  `-v`/`--verbose` (INFO-Logs auf stderr; Default ist WARNING).
- Ausgabe: Ist stdout ein Terminal und `--json` nicht gesetzt, erscheint eine
  lesbare Textausgabe. Bei Pipe/Agent (stdout kein Terminal) bleibt die
  JSON-Ausgabe ohne `--json` unverändert.
- Interaktive Prompts nur, wenn stdin ein Terminal ist; sonst klare
  Fehlermeldung mit nächstem Schritt. Prompts gehen auf stderr.
- Ausgaben-Sprache: Deutsch (Texte für Menschen), JSON-Felder englisch.

## Exit-Codes

| Code | Bedeutung |
| ---- | --------- |
| 0    | OK |
| 1    | Usage / Validierung (Args, Config, Env) oder vom Nutzer abgebrochen |
| 2    | Auth / Session (Login fehlt/ungültig/abgelaufen) |
| 3    | Netzwerk / HTTP (Timeout, 5xx, Verbindungsfehler) |
| 4    | Parse / unerwartete Antwort |
| 5    | Forbidden / schreibende Aktion ohne `--confirm`/`--yes` |

## Befehle

### `bibliothek search QUERY [--media book|ebook|all] [--available] [--limit N] [--json]`

- Live gegen den OPAC (Default `https://bsz.ibs-bw.de/hshn`), keine Anmeldung.
- `QUERY` ist positional; ein Suchbegriff mit Leerzeichen wird in Anführungs-
  zeichen übergeben (z. B. `bibliothek search "Grundlagen der Hydraulik"`).
- `--media` filtert Medientyp; default `all`.
- `--available`: bevorzugt Treffer mit verfügbarem Exemplar (Tippfehler: wird im
  Ranking berücksichtigt, nicht hart gefiltert).
- `--limit N`: 1 ≤ N ≤ 50, default 20. Ungültig → Exit 1.
- `--json`: ein Objekt `{"query", "media", "available_only", "count", "results": [...]}`.

### `bibliothek show TITEL|NR [--json]`

- Akzeptiert denselben Titel/Suchbegriff wie `search` oder eine Datensatz-ID
  (`AK…`, z. B. `record/AK63638611`, bzw. eine Detail-URL).
- Bei einem Titel wird zuerst gesucht. Mehrere Treffer werden im Terminal
  nummeriert zur Auswahl gestellt; ohne TTY und ohne eindeutigen Treffer endet
  der Befehl mit Exit 1 und nennt die Kandidaten.
- Felder: `id`, `title`, `authors`, `publisher`, `year`, `isbn`, `subjects`,
  `media_type`, `locations[]` mit `signature`, `call_no`, `status`, `due`.
- Ein Treffer, der nicht in der Anzeige liegt, ist Exit 4 mit nächstem Schritt.

### `bibliothek locations [--json]`

- Statische Liste der bekannten Standorte (Bildungscampus Heilbronn,
  Sontheim, Künzelsau, Schwäbisch Hall) inkl. Öffnungszeiten-URL.
- `--json` liefert das Objekt `{"locations": [...]}`.

### `bibliothek watch add QUERY [--limit N]`

- Fügt einen Suchauftrag in `$XDG_CONFIG_HOME/bibliothek-cli/watch.json` ein.
- `id` ist sha1(query+limit)[:8].
- Ausgabe: `{"id", "query", "limit", "created_at"}`.

### `bibliothek watch list`

- Liste aller Watch-Einträge als Tabelle oder unter `--json` `{"items": [...]}`.

### `bibliothek watch remove ID`

- Entfernt Eintrag; idempotent (unbekannte ID → exit 0, Meldung „noop“).

### `bibliothek login`

- Baut eine echte aDISWeb-Session über das Login-Formular des OPAC auf.
- `BIBLIOTHEK_USER` und `BIBLIOTHEK_PASSWORD` aus der Umgebung haben Vorrang und
  sind nur für Agenten gedacht; sie werden nie als CLI-Args angenommen.
- Fehlen Werte und ist stdin ein Terminal, werden Ausweisnummer (`input`) und
  Passwort (`getpass`, verdeckt) interaktiv abgefragt. Das Passwort wird weder
  angezeigt noch gespeichert noch geloggt.
- Erfolg gilt erst, wenn die Kontoseite sichtbar ist (nicht schon bei einem
  Cookie). Ausgabe im Terminal: `Login erfolgreich als <Ausweisnummer>`.
- Ohne Terminal und ohne Env: Exit 2 mit
  „Login fehlt: `bibliothek login` im Terminal ausführen oder
  BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD setzen“.
- EOF/Strg+C beim Prompt: „Abgebrochen.“ ohne Traceback, Exit 1.
- Session-Cookies in `$XDG_CONFIG_HOME/bibliothek-cli/session.json`,
  Mode 0600. Nur OPAC-Cookies (Origin-Check); keine Cookies fremder Hosts.
- Abgelaufene Session wird erkannt und gemeldet; kein automatischer Re-Login.

### `bibliothek whoami [--json]`

- Liest die gespeicherte Session und gibt die angemeldete Ausweisnummer aus.
- `--json`: `{"user": "...", "established_at": "...", "mock": false}`.
- Keine Session: Exit 2 mit Verweis auf `bibliothek login`.
- Gibt niemals Passwort oder Session-Cookies aus.

### `bibliothek logout`

- Löscht `session.json`. Idempotent: keine Session → exit 0.

### `bibliothek loans [list] [--json]`

- Liest die Ausleihen aus dem echten Konto über die gespeicherte Session.
- `loans` und `loans list` sind gleichwertig. Ohne Session: Exit 2.
- `--json`: `{"loans": [{"id", "title", "due", "renewals", "can_renew"}]}`.
- Abgelaufene Session: Exit 2 mit Verweis auf `bibliothek login`.

### `bibliothek verlaengern TITEL [--confirm|--yes] [--json]`

- Wählt die Ausleihe über den Titel aus den Konto-Ausleihen, nicht über eine ID.
- Bei mehreren passenden Ausleihen erscheint im TTY eine nummerierte Auswahl
  (`Auswahl [1-N]:`). Ohne TTY und ohne `--confirm`/`--yes`: Exit 5, **kein**
  Server-Request; die Meldung nennt `bibliothek login` bzw. `--confirm`.
- Vor der Bestätigung wird nur der lesende Konto-Abruf (`konto_laden`) gesendet.
  Danach folgen Titel und Frist als Zusammenfassung sowie auf stderr die Frage
  `Verlängerung verbindlich? [j/N]` (Default Nein).
- Erst nach `j` werden alle aDISWeb-Formularschritte gesendet:
  `konto_laden` → `verlaengern_absenden` → `verlaengern_bestaetigen`.
  Erfolg gilt erst nach der Bestätigungsseite mit neuem Fälligkeitsdatum, nicht
  bei HTTP 200 allein.
- `N` (oder Enter) bricht nach `konto_laden` ab: Exit 0, „Abgebrochen.“, keine
  schreibenden Schritte (Abbruch durch den Nutzer ist kein Fehler).
- `--confirm`/`--yes` sind nur für Agenten: keine `[j/N]`-Frage, aber dieselben
  Formularschritte; `--yes` ist ein Alias für `--confirm`.
- Ausgabe im Terminal u. a. `Verlängerung bestätigt.` und
  `Neues Fälligkeitsdatum: …`; `--json`:
  `{"id", "title", "renewed", "new_due"}`.

### `bibliothek loans renew LOAN_ID --confirm`

- Alias für Agenten, die noch mit IDs arbeiten. Bleibt erhalten.
- Ohne `--confirm`: Exit 5, **kein** Server-Request.
- Mit `--confirm`: dieselben Verlängerungsschritte wie `verlaengern`; Erfolg
  erst nach Bestätigung im Response-Body, nicht nur HTTP 200.
- Output: `{"id", "renewed", "new_due"}` oder Fehler-Exit 2/3/4.

### `bibliothek vormerken TITEL` (optional)

- Optionaler Ausbau nach demselben Muster wie `verlaengern` (Titel statt ID,
  nummerierte Auswahl, `[j/N]`, `--confirm` nur für Agenten).
- Die Live-Erkundung endet beim „Bestellen/Vormerken“-Einstieg an der
  Anmeldemaske. Ohne eingeloggtes Konto ist der Befehl nicht zugesagt; bis zur
  vollständigen Erkundung des Konto-Formulars bleibt er außen vor.

## Konfiguration / Pfade

- `BIBLIOTHEK_USER`, `BIBLIOTHEK_PASSWORD`: nur Env, nie CLI-Args.
- `BIBLIOTHEK_BASE_URL` (optional, default `https://bsz.ibs-bw.de/hshn`).
  Überschreibt die Basis-URL für Tests gegen einen Fake-Server.
- `BIBLIOTHEK_LOG` (optional, default `WARNING`; `-v` zeigt INFO-Logs).
- `BIBLIOTHEK_CONFIG` (optional, default
  `$XDG_CONFIG_HOME/bibliothek-cli`). Watch + Session landen hier.
- Session-Datei: `${BIBLIOTHEK_CONFIG:-$XDG_CONFIG_HOME/bibliothek-cli}/session.json`
  mit Mode 0600; nur OPAC-Cookies.

## Terminal vs. Agent

- Terminal (stdin/stdout TTY): lesbare Ausgabe, interaktive Auswahl und
  `[j/N]`-Bestätigung.
- Pipe/Agent (kein TTY): JSON-Ausgabe, keine Prompts. Schreibende Aktionen
  verlangen `--confirm`/`--yes` und brechen sonst vor jedem Request mit Exit 5 ab.
- Mit `--json` steht auf stdout genau ein JSON-Objekt; alle Prompts und Logs
  gehen auf stderr.
