# QA – bibliothek-cli (Live-Lauf 2026-10-14)

QA-Lauf gegen frisch installiertes `git+https://github.com/smlfg/bibliothek-cli.git@main`
in `/tmp/bib-qa` (venv, Python 3.13). Lauf-Beginn: 2026-10-14 08:24 UTC.

Test-Suite: **17 passed in 2.64s** (`pytest -q`, davon 13 altbestand + 2 für empty-/limit-usage + 2 für media-Filter).

Live-OPAC: `https://bsz.ibs-bw.de/hshn` (aDISWeb/BSZ OPAC04), erreichbar.

## Befehlstabelle

| # | Befehl | Erwartet | Beobachtet | OK/FAIL | Fixes |
| - | ------ | -------- | ---------- | ------- | ----- |
| 1 | `search "Python" --limit 5 --json` | HTTP 200; `count<=5`; `total_found>0`; Treffer mit Python-Bezug | exit 0; total_found=1002; count=5; 3/5 Titel enthalten das Token "Python" (OPAC rankt zusätzlich 2 Metadata-Hits auf Seite 1); strukturierte JSON | OK (mit Hinweis) | – |
| 2 | `search "Maschinenbau" --limit 3 --json` | HTTP 200; Treffer passen zum Thema | exit 0; total_found=1841; 0/3 Titel enthalten "Maschinenbau" auf Seite 1 — OPAC rankt Schlagwort-/Metadaten-Treffer (CATIA, Chemie, CSR) vor Titeln. 3/22 Titel auf Seite 1 treffen | OK (mit Hinweis) | – |
| 3 | `search "" --json` | Exit 1, JSON-Fehler `kind=usage` | exit 1; `{"error":{"kind":"usage","code":1,"message":"Suchbegriff darf nicht leer sein."}}` | OK nach Fix | `fix: empty/whitespace search query returns exit 1 usage error` (709f8b0) |
| 3b | `search "   " --json` | analog zu 3 | exit 1, gleiche JSON-Struktur | OK nach Fix | siehe 709f8b0 |
| 4 | `search "xyznonexistent99999" --limit 5 --json` | Exit 0; `count=0`; `total_found=0`; kein Crash | exit 0; total_found=0; count=0; results=[] | OK | – |
| 5 | `show AK63608656 --json` | echtes Detail ODER klar dokumentierter Fehler (kein Traceback) | exit 0; `id=AK63608656`, Titel/Autor aus der Trefferliste; `note: Vollanzeite via Playwright (Follow-up)`; `locations=[]` | OK (Doku-Limit) | – |
| 5b | `show AK99999999 --json` | sauberer Fehler Exit 4 | exit 4; `kind=parse`; `message: Datensatz AK99999999 nicht in erster Anzeige; Vollanzeite via Playwright` | OK | – |
| 6 | `locations --json` | Standorte Heilbronn inkl. HN/SN/KU/SHA | exit 0; 4 Standorte; HN = „Bibliothek Bildungscampus Heilbronn", SN = „Standort Sontheim", KU = Künzelsau, SHA = „Hochschule Heilbronn, Campus Schwäbisch Hall" | OK | – |
| 7a | `watch add "Robotik" --limit 7` | Exit 0; `{id, query, limit, created_at}` | exit 0; `id=e7c85b6a`, query="Robotik", limit=7, created_at als UTC-ISO | OK | – |
| 7b | `watch list --json` | Exit 0; Liste enthält Eintrag | exit 0; `items=[1]`; `wid` ist in stdout | OK | – |
| 7c | `watch remove e7c85b6a` | Exit 0; idempotent | exit 0; `{"removed":true,"id":"e7c85b6a"}` | OK | – |
| 7d | `watch remove e7c85b6a --json` (idempotent) | Exit 0; noop | exit 0; `{"noop":true,"id":"e7c85b6a"}` | OK | – |
| 8 | `loans renew MOCK-1 --json` ohne `--confirm` | Exit 5; **kein Server-Request**; JSON-Fehler `kind=confirm_required` | exit 5; `{"error":{"kind":"confirm_required","code":5,"message":"Verlängerung verlangt --confirm; keine Aktion ausgeführt."}}` | OK | – |
| 9 | `login --json` ohne Env | Exit 2; `kind=auth` | exit 2; `{"error":{"kind":"auth","code":2,"message":"BIBLIOTHEK_USER und/oder BIBLIOTHEK_PASSWORD nicht gesetzt."}}` | OK | – |
| 10 | `search "Algorithmen" --media ebook --limit 5 --json` | alle Treffer `media_type=ebook` | exit 0; 5/5 `media_type=ebook` | OK nach Fix | `fix: --media filter actually restricts media_type in results` (a06efb4) |
| 10b | `search "Python" --media book --limit 5 --json` | keine Treffer mit `media_type=ebook` | exit 0; 0 ebooks unter `media=book` | OK nach Fix | siehe a06efb4 |
| 11 | `search "Python" --available --limit 3 --json` | Feld `available_only=true`; Ranking-Hinweis | exit 0; `available_only=true`, `total_found=1002` (Ranking, kein Hard-Filter — INTERFACE-konform) | OK | – |
| 12 | `search "Python" --limit 99 --json` | Exit 1; `kind=usage` | exit 1; `{"error":{"kind":"usage","code":1,"message":"limit muss zwischen 1 und 50 liegen"}}` | OK | – |
| 13 | `--help` / `--version` | Exit 0, sauberer Text | exit 0; `bibliothek 0.1.0` | OK | – |
| 14 | `loans list --json` ohne Session | Exit 2; `kind=auth` | exit 2; `{"error":{"kind":"auth","code":2,"message":"Keine Session. Erst \`bibliothek login\` mit gültigen BIBLIOTHEK_USER/BIBLIOTHEK_PASSWORD ausführen."}}` | OK | – |
| 15 | `logout --json` (kein Session-File) | Exit 0 idempotent | exit 0; `{"removed":true,"existed":false}` | OK | – |

## Was gefixt wurde

1. **`search ""` (leere / whitespace-only Query)** lieferte vorher Exit 0 mit `count: 0`,
   maskierte also einen Usage-Fehler als Erfolg. Per INTERFACE.md ist das ein
   Validation-Fehler → Exit 1, `kind=usage`. Fix in
   `src/bibliothek_cli/cli.py::handle_search` (Commit `709f8b0`).

2. **`--media ebook|book` filterte nicht**: das Parsermodul hatte einen
   `pass`-Stub, der alle Treffer durchließ, obwohl `media != "all"`. Da das
   OPAC-Form den Medientyp nicht an den Server sendet, ist die Filterung
   rein clientseitig im Parser. Fix in
   `src/bibliothek_cli/http.py::_parse_hits` (Commit `a06efb4`).

Zusätzliche Begleitarbeit:
- `.gitignore` für `__pycache__`, `*.egg-info`, `build/`, `.pytest_cache/`.
- 4 neue Tests (`test_search_empty_query_exits_1`, `test_search_limit_range_exits_1`,
  `test_parse_hits_filters_by_media_ebook`, `test_parse_hits_filters_by_media_book_excludes_ebooks`).

## Was noch Mock / Follow-up ist

1. **Login (echt)**: aDISWeb braucht JS+Cookie-POST + einen zweiten Schritt
   (`htmlOnLink`) zur Bestätigung im Konto-Bereich. Aktueller `cmd_login`
   speichert eine Mock-Session mit `mock: true`. **LIVE-Login bleibt offen** —
   siehe README und INTERFACE.md.
2. **Vollanzeige (`show` mit `locations[]`)**: Parser bedient sich aktuell
   aus der Trefferliste. Detailseite mit Standort/Verfügbarkeit pro Exemplar
   müsste per Playwright (oder einem aDISWeb-JS-Server-Roundtrip) nachgeladen
   werden. Der Platzhalter in der JSON-Antwort (`"locations":[]`, `"note"`)
   ist dokumentiert.
3. **Pagination**: aktuell nur Seite 1 (20–50 Treffer). `gotoPage`-Parameter
   nötig, um an spätere Hits zu kommen — etwa damit Maschinenbau-Titel ab
   Treffer ~3 erreichbar werden, ohne `--limit 50` zu setzen.
4. **OPAC-Ranking**: für Suchen wie „Maschinenbau" liefert das OPAC
   Schlagwort-/Metadata-Matches vor exakten Titel-Treffern. Das ist
   aDISWeb-Verhalten und kein Parser-Bug (mit `--limit 30` finden sich
   auch hier Titel mit dem Token).

## Exit-Summary

**GRÜN** — 17/17 Live- und Unit-Tests grün nach den beiden Fixes. Beide
Befunde wurden im Repo gefixt, kleinteilig als `fix:`-Commits auf
`origin/main` gepusht, frisch re-installiert und re-verifiziert.

Offen (kein Block für Green der implementierten Spec):
- Login-Roundtrip (Mock steht; Live ist Follow-up).
- Detail-`locations[]` (Vollanzeige via Playwright).
- Pagination über Seite 1 hinaus.
