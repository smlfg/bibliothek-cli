# bibliothek-cli

## Schnellstart

```bash
pipx install git+https://github.com/smlfg/bibliothek-cli
bibliothek login
bibliothek search "Grundlagen der Hydraulik"
bibliothek show "Grundlagen der Hydraulik"
bibliothek verlaengern "Grundlagen der Hydraulik"
```

CLI für den **LIV-Bibliothekskatalog** (OPAC HHN/DHBW Heilbronn).
Treiber: aDISWeb/BSZ-OPAC04 unter
[`https://bsz.ibs-bw.de/hshn`](https://bsz.ibs-bw.de/hshn).

- **Suche live** im Katalog (kein Login), Suchbegriff positional
- Detail-Datensatz per Titel oder ID (Standort, Signatur, Status, Frist)
- Lokaler Keyword-Watch (Datei-basiert, kein Server)
- Login am Bibliothekskonto interaktiv im Terminal oder per
  **Env-Variablen** (`BIBLIOTHEK_USER` + `BIBLIOTHEK_PASSWORD`, nie CLI-Flags);
  `whoami` und idempotenter `logout`
- Ausleihen echt aus dem Konto lesen (`loans`, Alias `loans list`)
- Verlängern über den **Titel**: Auswahl, Zusammenfassung und
  `Verlängerung verbindlich? [j/N]` im Terminal; erst nach `j` werden alle
  Formularschritte gesendet. `--confirm`/`--yes` nur für Agenten, ohne TTY
  bricht der Befehl vor jedem Request ab.

Status: Suche und Anzeige live; Konto und Verlängern werden auf die echte
aDISWeb-Session nachgerüstet. Schnittstelle und Akzeptanztests stehen.

## Installation

Für eine isolierte Installation ohne pipx:

```bash
python -m venv .venv
.venv/bin/pip install git+https://github.com/smlfg/bibliothek-cli
```

## Weitere Beispiele

```bash
bibliothek search "Python" --limit 5
bibliothek search "Machine Learning" --media ebook --json
bibliothek show AK63638611
bibliothek locations
bibliothek watch add "Deep Learning" --limit 10
bibliothek watch list
BIBLIOTHEK_USER=... BIBLIOTHEK_PASSWORD=... bibliothek login
bibliothek whoami
bibliothek loans
bibliothek verlaengern "Grundlagen der Hydraulik" --confirm
bibliothek loans renew AK63638611 --confirm
bibliothek logout
```

## Schnittstelle

| Befehl | Zweck |
| ------ | ----- |
| `bibliothek search QUERY [--media book\|ebook\|all] [--available] [--limit N] [--json]` | Live-Suche |
| `bibliothek show TITEL\|NR [--json]` | Detail per Titel oder ID |
| `bibliothek locations [--json]` | Bekannte Standorte (statisch) |
| `bibliothek watch add QUERY [--limit N]` | Watch hinzufügen |
| `bibliothek watch list` | Watch-Liste |
| `bibliothek watch remove ID` | Watch entfernen (idempotent) |
| `bibliothek login` | Session interaktiv oder per Env aufbauen |
| `bibliothek whoami [--json]` | Angemeldete Ausweisnummer |
| `bibliothek logout` | Session löschen (idempotent) |
| `bibliothek loans [list] [--json]` | Ausleihen aus dem Konto |
| `bibliothek verlaengern TITEL [--confirm\|--yes] [--json]` | Ausleihe per Titel verlängern |
| `bibliothek loans renew LOAN_ID --confirm` | Alias für Agenten |

Exit-Codes: `0` ok, `1` Usage/abgebrochen, `2` Auth, `3` Netzwerk, `4` Parse,
`5` schreibende Aktion ohne `--confirm`/`--yes`.

Im Terminal erscheint ohne `--json` eine lesbare Textausgabe; bei Pipe/Agent
bleibt die JSON-Ausgabe erhalten. Mit `--json` steht **genau ein** JSON-Objekt
auf stdout, Prompts auf stderr. Schreibende Aktionen fragen im TTY
`Verlängerung verbindlich? [j/N]` (Default Nein).

Volle Spezifikation: [`INTERFACE.md`](./INTERFACE.md).

## Konfiguration

- `BIBLIOTHEK_USER`, `BIBLIOTHEK_PASSWORD`: Env, nie CLI-Args.
- `BIBLIOTHEK_BASE_URL` (optional, default `https://bsz.ibs-bw.de/hshn`).
- `BIBLIOTHEK_LOG` (optional, default `WARNING`; `-v` zeigt INFO-Logs).
- `BIBLIOTHEK_CONFIG` (optional, default
  `$XDG_CONFIG_HOME/bibliothek-cli`). Watch + Session landen hier.
- Session: `session.json` mit Mode 0600, nur OPAC-Cookies.

## Bekannte Limitierungen

- aDISWeb ist eine JS-/Forms-SPA ohne SRU/DAIA/REST. Suche, Detail und Login
  laufen über Form-POSTs mit Hidden-Feldern und Session-Cookies.
- Ohne Zugangsdaten ist der Konto-Bereich nicht live einsehbar. Die
  Verlängerungsseiten sind in den Fixtures als `SYNTHETISCH` nachgebaut.
- Vormerken ist optional und erst nach Live-Erkundung des Konto-Formulars
  zugesagt; der öffentliche Einstieg endet an der Anmeldemaske.

## Entwicklung

```bash
git clone https://github.com/smlfg/bibliothek-cli
cd bibliothek-cli
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

## Lizenz

MIT – siehe [`LICENSE`](./LICENSE).
