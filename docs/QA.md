# QA – bibliothek / Evangelisierung

## Status 2026-10-14

| Befehl | Status | Notizen |
| ------ | ---- | ------ |
| `--help` / `--version` | grün | argparse ruft, ok |
| `search --json` | grün (live) | 1002 Treffer bei „python", 22 pro Seite; Parser aus `li.rList_li` |
| `locations --json` | grün (statisch) | HN/SN/KU/SHA als statische Liste |
| `watch add/list/remove` | grün | `~/.config/bibliothek-cli/watch.json`, Mode 0600 |
| `login` ohne Env | grün (Exit 2) | saubere JSON-Fehlerausgabe |
| `login` mit Env | grün (Mock) | siehe „Limitierungen" |
| `loans list` | grün (Mock) | siehe „Limitierungen" |
| `loans renew` ohne `--confirm` | grün (Exit 5, kein Server-Request) | |
| `logout` | grün (idempotent) | |

## Smoke gegen Live-OPAC

```
$ bibliothek search python --limit 3 --json
{
  "query": "python",
  "media": "all",
  "available_only": false,
  "total_found": 1002,
  "count": 3,
  "results": [ … 3 Treffer mit id AK63608656, AK63661239, AK63870454 … ]
}
```

## Follow-ups (offen)

1. **Login live**: aDISWeb benötigt einen POST mit `service=direct/...` + ein
   zweites Cookie. JS-Redirect-Check. Cookie-Allowlist (Origin = bsz.ibs-bw.de)
   steht.
2. **Vollanzeige / Standort / Verfügbarkeit**: per Playwright (headless) auf
   `htmlOnLink('AK…')`. Mit den IDs aus der Trefferliste trivial.
3. **Pagination**: aktuell nur Seite 1; `gotoPage`/`SR…`-Parameter nötig.