# Anforderungen – bibliothek-cli

Zielgruppe: KI-Agenten, die mit dem LIV-Bibliothekskatalog (OPAC HHN/DHBW
Heilbronn, BSZ/aDISWeb) interagieren, ohne einen Browser zu öffnen.

Funktionale Anforderungen:

- Katalog-Suche gegen den öffentlichen OPAC (kein Login).
- Detail-Datensatz (Titel, Autor, Verlag, ISBN, Schlagworte, Standort,
  Verfügbarkeit/Signatur).
- Lokaler Keyword-Watch (Datei-basiert, $XDG_CONFIG_HOME/bibliothek-cli).
- Login auf das Bibliothekskonto mit Env-Variablen `BIBLIOTHEK_USER`
  und `BIBLIOTHEK_PASSWORD` (nie CLI-Args, keine Anzeige). Session-Cookies
  nur für die OPAC-Origin, persistent in
  `$XDG_CONFIG_HOME/bibliothek-cli/session.json` (Mode 0600).
- Ausleihen lesen (`loans list`), Verlängerung nur mit explizitem
  `--confirm`, sonst Exit 5 ohne Server-Request.
- Sauberer Abbau: `logout` löscht Session idempotent.
- `--help`/`--version` Standard.

Nicht-funktionale Anforderungen:

- Python 3.11+, MIT-Lizenz.
- Konsistente Exit-Codes (0/1/2/3/4/5, siehe INTERFACE.md).
- `--json` produziert genau ein JSON-Objekt auf stdout, Logs auf stderr.
- Kein Netzwerk in Unit-Tests; HTML-Fixtures decken Parser ab.
- Keine erfundenen Personendaten.