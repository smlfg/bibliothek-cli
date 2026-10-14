# INTERFACE – bibliothek-cli

CLI: `bibliothek` (Paket `bibliothek-cli`, v0.1.0).

## Allgemein

- `--help` / `--version` (gedruckt auf stdout, exit 0).
- Globale Optionen: `--json` (genau ein JSON-Objekt auf stdout, Logs auf stderr).
- Ausgaben-Sprache: Deutsch (Texte für Menschen), JSON-Felder englisch.

## Exit-Codes

| Code | Bedeutung |
| ---- | -------- |
| 0    | OK |
| 1    | Usage / Validierung (Args, Config, Env) |
| 2    | Auth / Session (Login fehlt/ungültig/abgelaufen) |
| 3    | Netzwerk / HTTP (Timeout, 5xx, Verbindungsfehler) |
| 4    | Parse / unerwartete Antwort |
| 5    | Forbidden / Aktion ohne `--confirm` |

## Befehle

### `bibliothek search QUERY [--media book|ebook|all] [--available] [--limit N] [--json]`

- Live gegen `https://bsz.ibs-bw.de/hshn` (aDISWeb/BSZ OPAC04), keine Anmeldung.
- `--media` filtert Medientyp; default `all`.
- `--available`: bevorzugt Treffer mit verfügbarem Exemplar (Tippfehler: wird im
  Ranking berücksichtigt, nicht hart gefiltert).
- `--limit N`: 1 ≤ N ≤ 50, default 20. Ungültig → Exit 1.
- `--json`: ein Objekt `{"query", "media", "available_only", "count", "results": [...]}`.

### `bibliothek show RECORD_ID_OR_URL [--json]`

- Detail-Datensatz per numerischer ID (z. B. `record/12345`) oder voller
  Detail-URL.
- Felder: `id`, `title`, `authors`, `publisher`, `year`, `isbn`, `subjects`,
  `media_type`, `locations[]` mit `signature`, `call_no`, `status`, `due`.

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

- Entfernt Eintrag; idempotent (unbekannte ID → exit 0, Meldung „noop").

### `bibliothek login`

- Liest `BIBLIOTHEK_USER` und `BIBLIOTHEK_PASSWORD` aus der Umgebung, nie
  CLI-Args.
- Erfolg erst nach Beweis: Seite „Mein Konto" / „Ausleihen" wurde
  gerendert.
- Session-Cookies in `$XDG_CONFIG_HOME/bibliothek-cli/session.json`,
  Mode 0600. Nur OPAC-Cookies (Origin-Check).
- Exit 2 bei fehlenden Env-Variablen; Exit 3 bei HTTP-Fehler; Exit 4 bei
  Parser-Fehler.

### `bibliothek loans list [--json]`

- Liest Ausleihen über die Session. Ohne Session: Exit 2.
- `--json`: `{"loans": [{"id", "title", "due", "renewals", "can_renew"}]}`.

### `bibliothek loans renew LOAN_ID --confirm`

- Ohne `--confirm`: Exit 5, **kein** Server-Request.
- Mit `--confirm`: POST zur Verlängerung; Erfolg erst nach Bestätigung im
  Response-Body, nicht nur HTTP 200.
- Output: `{"id", "renewed", "new_due"}` oder Fehler-Exit 2/3/4.

### `bibliothek logout`

- Löscht `session.json`. Idempotent: keine Session → exit 0.

## Konfiguration / Pfade

- `BIBLIOTHEK_USER`, `BIBLIOTHEK_PASSWORD`: nur Env, nie CLI-Args.
- `BIBLIOTHEK_BASE_URL` (optional, default `https://bsz.ibs-bw.de/hshn`).
- `XDG_CONFIG_HOME` oder Default `$HOME/.config` →
  `…/bibliothek-cli/{watch.json, session.json}`.