# bibliothek-cli

Agent-CLI für den **LIV-Bibliothekskatalog** (OPAC HHN/DHBW Heilbronn).
Treiber: aDISWeb/BSZ-OPAC04 unter
[`https://bsz.ibs-bw.de/hshn`](https://bsz.ibs-bw.de/hshn).

- **Suche live** im Katalog (kein Login)
- Detail-Datensatz aus der Trefferliste (ID `AK…` aus
  `data-ajax`/`htmlOnLink`)
- Lokaler Keyword-Watch (Datei-basiert, kein Server)
- Login am Bibliothekskonto per **Env-Variablen** (`BIBLIOTHEK_USER` +
  `BIBLIOTHEK_PASSWORD`, nie CLI-Flags)
- Ausleihen lesen, Verlängern **nur** mit `--confirm`
- Idempotenter `logout`

Status: gebaut; Live-Suche gegen BSZ/aDISWeb getestet.

## Installation

```bash
python -m venv /tmp/bib-venv
/tmp/bib-venv/bin/pip install bibliothek-cli
# oder aus diesem Repo:
# pip install /home/box/cli-daily/bibliothek-cli
```

## Schnellstart

```bash
# Katalog live durchsuchen
bibliothek search "Python" --limit 5
bibliothek search "Machine Learning" --media ebook --json

# Standorte
bibliothek locations --json

# Lokaler Watch
bibliothek watch add "Deep Learning" --limit 10
bibliothek watch list
bibliothek watch remove 7be907e3

# Login + Verlängern (mit Bestätigung)
BIBLIOTHEK_USER=... BIBLIOTHEK_PASSWORD=... bibliothek login
bibliothek loans list
bibliothek loans renew LOAN_ID --confirm
bibliothek logout
```

## Schnittstelle

| Befehl | Zweck |
| ------ | ---- |
| `bibliothek search QUERY [--media book|ebook|all] [--available] [--limit N] [--json]` | Live-Suche |
| `bibliothek show RECORD_OR_URL [--json]` | Detail-Datensatz aus Trefferliste |
| `bibliothek locations [--json]` | Bekannte Standorte (statisch) |
| `bibliothek watch add QUERY [--limit N]` | Watch hinzufügen |
| `bibliothek watch list` | Watch-Liste |
| `bibliothek watch remove ID` | Watch entfernen (idempotent) |
| `bibliothek login` | Session aufbauen |
| `bibliothek loans list [--json]` | Ausleihen |
| `bibliothek loans renew LOAN_ID --confirm` | Verlängern (nur mit Bestätigung) |
| `bibliothek logout` | Session löschen (idempotent) |

Exit-Codes: `0` ok, `1` Usage, `2` Auth, `3` Netzwerk, `4` Parse,
`5` Action ohne `--confirm`.

Mit `--json` steht **genau ein** JSON-Objekt auf stdout, Prompts auf stderr.

Volle Spezifikation: [`INTERFACE.md`](./INTERFACE.md).

## Konfiguration

- `BIBLIOTHEK_USER`, `BIBLIOTHEK_PASSWORD`: Env, nie CLI-Args.
- `BIBLIOTHEK_BASE_URL` (optional, default `https://bsz.ibs-bw.de/hshn`).
- `BIBLIOTHEK_LOG` (optional, default `INFO`).
- `BIBLIOTHEK_CONFIG` (optional, default
  `$XDG_CONFIG_HOME/bibliothek-cli`). Watch + Session landen hier.

## Bekannte Limitierungen

- aDISWeb ist eine JS-/Forms-SPA ohne SRU/DAIA/REST. Der Login und die
  Detail-Anzeige (Standort/Verfügbarkeit) sind in dieser Version als
  **Mock** implementiert; ein Live-Login-Roundtrip (Cookie-POST +
  Mein-Konto-Beweis) steht in
  [`docs/QA.md`](./docs/QA.md) als Follow-up.
- `show` liefert die Felder aus der Trefferliste. Vollanzeite (mit
  Standort/Verfügbarkeit pro Exemplar) folgt in einer Folge-Iteration
  mit Playwright.

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