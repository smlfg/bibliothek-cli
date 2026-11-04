# QA – bibliothek-cli (Pflicht-QA, 2026-11-04; Nachprüfung S6)

Gegenstand: frisch per `pipx install git+https://github.com/smlfg/bibliothek-cli`
installierter Stand `0.1.0`, Commit `407144b`, Python `3.14.7`.
Installationsprotokoll: `scratch/qa/pipx-install.log`.
In der ursprünglichen QA wurde ausschließlich
`PATH=$PWD/scratch/pipx/bin:$PATH bibliothek …` ausgeführt (nicht die
Entwicklungs-Venv); die Nachprüfung S6 nutzte die Entwicklungs-Venv
`scratch/venv` (editable install). Pseudo-Terminal-Sitzungen mit
`script -qec`, Live-Aufrufe nur lesend. Es gab keine echten Zugangsdaten;
Konto- und Verlängerungs-Aktionen wurden gegen `tests/harness/fake_server.py`
mit den `ux-routes` aus `docs/UX.md` geprüft. Kein Passwort, kein Cookie und
keine echte Anmeldung wurde gesendet oder gespeichert.

Test-Suite: `69 passed` (`scratch/venv/bin/pytest -q`).
UX-Gate: `ux_check.py .` → PASS; `ux_session.py .` → PASS.
Live-OPAC am 2026-11-04: `https://bsz.ibs-bw.de/hshn` erreichbar, aber
`/hshn/` antwortet mit HTTP 404; `/hshn` leitet mit 301 auf
`/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SOPAC04` um.

Nachprüfung S6 nach den Fixes `97d3833` (Live-Basis-URL, Suche, Vollanzeige,
Login) und `6eda0aa` (`show` per ID/Titel). Die Live-Prüfungen liefen jetzt ohne
Override mit dem Default `https://bsz.ibs-bw.de/hshn`. Beim Login wurde
ausschließlich die Anmeldemaske per GET/POST bis zum Formular geöffnet; es
wurden keine Zugangsdaten und kein echter Login-POST gesendet.

## Befunde

| # | Prüfung | Befehl | Erwartet | Ergebnis | Beleg |
|---|---------|--------|----------|----------|-------|
| 1 | Frische pipx-Installation | `pipx install git+https://github.com/smlfg/bibliothek-cli` (Log) | App `bibliothek` installiert | OK | `scratch/qa/pipx-install.log`: `installed package bibliothek-cli 0.1.0`, `- bibliothek` |
| 2 | Installation aus `main` | `pipx_metadata.json` | `git+…@main`, 0.1.0 | OK | `package_or_url: git+https://github.com/smlfg/bibliothek-cli@main`, Python 3.14.7 |
| 3 | Nur pipx im PATH | `which bibliothek` | Pfad unter `scratch/pipx/bin` | OK | `/home/box/cli-daily/bibliothek-cli/scratch/pipx/bin/bibliothek` |
| 4 | Version | `bibliothek --version` | `bibliothek 0.1.0`, Exit 0 | OK | `scratch/qa/01-install.txt` |
| 5 | Test-Suite | `scratch/venv/bin/pytest -q` | grün | OK | `61 passed, 4 warnings in 33.96s` |
| 6 | UX-Spec | `python3 tests/harness/ux_check.py . --spec-only` | PASS | OK | `scratch/qa/03-ux-spec.txt`: `Ergebnis: PASS`, 3 Sitzungen, 3 formsteps |
| 7 | `--help`/`--version` aller Unterkommandos | `bibliothek <cmd> --help` | jeweils Exit 0 | OK | `scratch/qa/help-*.err` leer, alle Exit 0 |
| 8 | README-Installationszeile | `pipx install git+https://github.com/smlfg/bibliothek-cli` | landet im PATH | OK | `scratch/qa/pipx-install.log` |
| 9 | `login` Prompt + EOF (Ausweisnummer) | `script -qec "bibliothek login" … < /dev/null` | Prompt, sauberer Abbruch, kein Traceback | OK | `scratch/qa/20-live-login-eof.log`: `Ausweisnummer: Abgebrochen.`, Exit 1 |
| 10 | `login` Prompt + EOF (Passwort) | Username eingeben, dann EOF | `Abgebrochen.`, Exit 1 | OK | `scratch/qa/56-live-login-eof-password.log` |
| 11 | `login` interaktiv gegen Fake | Ausweisnummer + Passwort per PTY | Erfolg, Session 0600, Passwort nicht gespeichert | OK | `scratch/qa/21-fake-login.log`, `session.json` Mode `600`, kein Passwort im Log/File |
| 12 | `login` unvollständige Eingabe | Fake, leere Ausweisnummer/Passwort | Exit 2, nächster Schritt | OK | `scratch/qa/57-fake-login-empty.log`: `Login unvollständig … Starte bibliothek login erneut.` |
| 13 | `login` ohne TTY/Env | `bibliothek login --json` | Exit 2, Verweis auf Login | OK | `scratch/qa/71-default-login.err` (Variante mit Env) bzw. `Login fehlt …` |
| 14 | `search` README live (Default-Base) | `bibliothek search "Grundlagen der Hydraulik" --json` | Treffer, Exit 0 | OK (nach Fix `97d3833`) | `scratch/qa/s6-14-default-search.json`: Exit 0, 72 Treffer, erste Signatur `ZL 4650 G875 (2026)` |
| 15 | `show` README live (Default-Base) | `bibliothek show "Grundlagen der Hydraulik" --json` | Detail, Exit 0 | OK (nach Fix `97d3833`) | `scratch/qa/s6-15-default-show.json`: Exit 0, Standort/Status/Signatur vorhanden |
| 16 | `login` live Default-Base (Dummy, GET scheitert vor POST) | `BIBLIOTHEK_USER=qa-dummy … bibliothek login --json` | Formular erreichbar | OK (nach Fix `97d3833`; nur Formular-GET) | `scratch/qa/s6-16-login-form.log`: Anmeldemaske HTTP 200, Passwortfeld vorhanden; kein Login-POST |
| 17 | `verlaengern` live ohne Session (TTY) | `script -qec "bibliothek verlaengern 'Grundlagen der Hydraulik'"` | Exit 2, kein Request | OK | `scratch/qa/74-live-verlaengern-nosession-tty.log`: `[auth] exit 2: Login fehlt …` |
| 18 | `search` Fake/TTY | `script -qec "bibliothek search 'Grundlagen der Hydraulik'"` | lesbare Trefferliste, kein JSON | OK | `scratch/qa/22-fake-search.log`: `Treffer: 2 (angezeigt: 2)` |
| 19 | `show` Fake/TTY | `script -qec "bibliothek show 'Grundlagen der Hydraulik'"` | lesbare Detailfelder | OK | `scratch/qa/23-fake-show.log`: Titel/Autor/Jahr/Standort/Signatur/Status/ID |
| 20 | `verlaengern` Fake, Antwort `N` | PTY, Auswahl `1`, dann `n` | Exit 0, nur `konto_laden`, keine schreibenden Schritte | OK | `scratch/qa/24-fake-verlaengern-n.log`; Request-Log: GET `/`, POST Konto, sonst nichts |
| 21 | `verlaengern` Fake, Antwort `j` | PTY, Auswahl `1`, dann `j` | alle Formsteps bis Bestätigung | OK | `scratch/qa/25-fake-verlaengern-j.log`; Requests: Konto, `service=renew`, `service=renewconfirm` |
| 22 | `verlaengern` ohne TTY mit Session | `bibliothek verlaengern … --json` | Exit 5, **kein** Request | OK | Request-Delta 0; Meldung nennt `--confirm` |
| 23 | `loans`/`whoami` Fake | `bibliothek loans --json`, `bibliothek whoami` | Ausleihen bzw. Ausweisnummer | OK | `scratch/qa/27-fake-loans.json`, `scratch/qa/72-fake-loans-tty.log`, `73-fake-whoami-tty.log` |
| 24 | `loans renew` Alias | `bibliothek loans renew 3360581 --confirm --json` | alle Schritte, neues Datum | OK | `scratch/qa/29-fake-renew-alias.json`: `new_due 07.12.2026`; Request-Delta 4 |
| 25 | `logout` idempotent | `bibliothek logout --json` zweimal | Exit 0, zweites Mal `existed:false` | OK | `removed:true, existed:true` → `removed:true, existed:false` |
| 26 | Live-Suche Grundbegriff | `search "Grundlagen der Hydraulik" --limit 5` (Override) | plausible Hydraulik-Treffer | OK | `scratch/qa/14-live-search-workaround.json`: 72 Treffer, Titel/Autor/Jahr plausibel |
| 27 | Filter `--media ebook` über alle Treffer | `search "Algorithmen" --media ebook --limit 50` | nur ebooks | OK | `scratch/qa/41-live-ebook.json`: 18/18 `media_type=ebook` |
| 28 | Filter `--media book` über alle Treffer | `search "Grundlagen der Hydraulik" --media book --limit 50` | nur Bücher | OK | `scratch/qa/58-media-book.json`: 5/5 `book`, 0 ebooks |
| 29 | Filter `--media all` | `search "Grundlagen der Hydraulik" --media all --limit 50` | Mischung | OK | `scratch/qa/58-media-all.json`: 22 Treffer, `book` + `ebook` + `stücktitel/band` |
| 30 | `--limit`-Grenzen | `search "Python" --limit 0` / `--limit 99` | Exit 1 Usage | OK | `limit muss zwischen 1 und 50 liegen` |
| 31 | Leerer Suchbegriff | `search "" --json`, `search "   " --json` | Exit 1 Usage | OK | `Suchbegriff darf nicht leer sein.` |
| 32 | Keine Treffer | `search "xyznonexistent99999" --json` | Exit 0, `count=0` | OK | `scratch/qa/46-live-empty.json`: `total_found:0`, `results:[]` |
| 33 | Umlaute/Tippvarianten | `Künzelsau`/`Kunzelsau`, `Grollius`/`Gröllius`, `Hydralik` | plausible Treffer | OK | `scratch/qa/44-*.json`, `45-*.json`, `54-*.json` |
| 34 | `--available` | `search "Python" --available --limit 5` vs. ohne | Ranking/bevorzugt verfügbare Treffer | OK (nach Fix `97d3833`; Python-Beleg ohne verfügbare Treffer) | `scratch/qa/s6-34-*.json`: Python identisch (alle ebooks `available:null`); Hydraulik mit `--available` sortiert Bücher zuerst |
| 35 | Suchfelder Autor/Signatur | Live-Suche | `Grollius, Horst-W.` und Signatur | OK (nach Fix `97d3833`) | `scratch/qa/s6-35-search-fields.json`: `author: "Grollius, Horst-W."`, Signatur `ZL 4650 G875 (2026)` |
| 36 | `show` per ID live | `bibliothek show AK63638611 --json` (Override) | Detail mit Standort/Status | OK (nach Fix `97d3833`) | `scratch/qa/s6-36-show-id.json`: Vollanzeige mit Signatur, Standort, Status `Verfügbar` |
| 37 | `show` per Titel live | `script -qec "bibliothek show 'Grundlagen der Hydraulik'"` (Override) | Detailfelder | OK (nach Fix `97d3833`) | `scratch/qa/s6-37-show-title-tty.log`: Detailfelder statt „Ende der Sitzung“ |
| 38 | `show` mehrere Treffer ohne TTY | `bibliothek show "Hydraulik" --json` | Exit 1 mit Kandidaten | OK | `scratch/qa/49-live-show-multi.json`: 20 Kandidaten, Hinweis auf ID |
| 39 | `show` mehrere Treffer im TTY | Auswahl `1` | Detail des Treffers | OK (nach Fix `97d3833`) | `scratch/qa/s6-39-show-multi-tty.log`: Auswahl `1`, danach vollständige Detailfelder |
| 40 | `show` unbekannte ID | `bibliothek show AK99999999 --json` | Exit 4, nächster Schritt | OK | `scratch/qa/48-live-show-missing.json`: `Prüfe die ID oder nutze bibliothek search …` |
| 41 | TTY vs. `--json` | `search …` mit/ohne `--json` | TTY Text, `--json` genau ein Objekt | OK | `scratch/qa/52-live-search-tty.log` (Text), `60-tty-json.log` (JSON) |
| 42 | Parser-/Usage-Fehler mit `--json` | `bibliothek search --json` | stdout genau ein JSON-Objekt, Exit 1 | OK | `scratch/qa/55-argparse-stdout.txt`; Usage auf stderr |
| 43 | Netzwerkfehler | `BIBLIOTHEK_BASE_URL=http://127.0.0.1:1 bibliothek search …` | Exit 3, nächster Schritt, kein Traceback | OK | `scratch/qa/32-neterr-search.json`, `33-neterr-login.json` |
| 44 | `locations` | `script -qec "bibliothek locations"` | 4 Standorte, lesbar | OK | `scratch/qa/53-live-locations-tty.log` |
| 45 | Watch lokal | `watch add/list/remove` | Exit 0, idempotent | OK | `watch add Robotik --limit 7` → `e7c85b6a`; `remove` zweimal `noop` |
| 46 | Session-Schutz | `stat -c '%a' session.json`; Log prüfen | 0600, kein Passwort | OK | `600`, `21-fake-login.log` ohne Passwort |
| 47 | Keine Tracebacks | `grep -R Traceback scratch/qa` | keine Treffer | OK | Suche über alle QA-Logs ohne Treffer |

**Zählung: 47 OK / 47, 0 FAIL.**

## Aufgelöste FAILs (S6)

1. **Default-Basis-URL live defekt.** Behoben in `97d3833`: Startseite wird ohne
   erzwungenen Schraegstrich geladen; `/hshn` folgt der 301-Weiterleitung.
   Betroffen waren `search`, `show`, `login` und damit Konto/Verlängern.
2. **Live-Detail (`show` per Titel) liefert „Ende der Sitzung“.** Behoben in
   `97d3833`: Der Detail-POST übernimmt die Formular-`action` inklusive
   `;jsessionid=…` und sendet `selected=ZTEXT       <ID>`.
3. **`show` per ID lädt gar kein Detail.** Behoben in `97d3833`/`6eda0aa`:
   Der ID-Zweig lädt die Vollanzeige und übernimmt Standort, Signatur, Status,
   Exemplare und Frist.
4. **`--available` ist wirkungslos.** Behoben in `97d3833`: verfügbare Treffer
   werden clientseitig vor den übrigen einsortiert. Bei Suchläufen, deren Treffer
   ausschließlich aus ebooks ohne Verfügbarkeitsangabe bestehen (z. B. `Python`),
   bleibt die Reihenfolge erwartungsgemäß unverändert; der Beleg mit gemischten
   Treffern ist `s6-34-*-hyd.json`.
5. **Suchfelder sind verschmutzt/leer.** Behoben in `97d3833`: Autoren werden
   bereinigt, Signaturen aus der Trefferliste bzw. per Standort-AJAX ergänzt.

Nicht als FAIL gewertet, aber Beobachtung: unbekannte Medientypen werden
unverändert kleingeschrieben (`stücktitel/band`), siehe `58-media-all.json`.

## Nicht live prüfbar

`loans`, `verlaengern` und `renew` benötigen ein echtes Konto. Ohne
Zugangsdaten wurden nur die Wege ohne Request (Exit 2/5) live geprüft und die
vollständigen Formularschritte gegen den Fake-Server (`ux-routes`). Es wurde
keine echte Anmeldung und keine echte Verlängerung ausgelöst.
