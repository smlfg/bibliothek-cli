# QA – bibliothek-cli (Pflicht-QA, 2026-11-04)

Gegenstand: frisch per `pipx install git+https://github.com/smlfg/bibliothek-cli`
installierter Stand `0.1.0`, Commit `407144b`, Python `3.14.7`.
Installationsprotokoll: `scratch/qa/pipx-install.log`.
Ausgeführt wurde ausschließlich `PATH=$PWD/scratch/pipx/bin:$PATH bibliothek …`
(nicht die Entwicklungs-Venv). Pseudo-Terminal-Sitzungen mit
`script -qec`, Live-Aufrufe nur lesend. Es gab keine echten Zugangsdaten;
Konto- und Verlängerungs-Aktionen wurden gegen `tests/harness/fake_server.py`
mit den `ux-routes` aus `docs/UX.md` geprüft. Kein Passwort, kein Cookie und
keine echte Anmeldung wurde gesendet oder gespeichert.

Test-Suite: `61 passed` (`scratch/venv/bin/pytest -q`).
UX-Spec: `ux_check.py --spec-only` → PASS.
Live-OPAC am 2026-11-04: `https://bsz.ibs-bw.de/hshn` erreichbar, aber
`/hshn/` antwortet inzwischen mit HTTP 404; `/hshn` leitet mit 301 auf
`/aDISWeb/app?service=direct/0/Home/$DirectLink&sp=SOPAC04` um.

Hinweis zu den Live-Prüfungen: Da der dokumentierte Default `BIBLIOTHEK_BASE_URL`
durch den 404 auf `/hshn/` bricht (FAIL 1), wurden die semantischen Live-Checks
zusätzlich mit der dokumentierten Override-Variable und einem Query-Trick
`BIBLIOTHEK_BASE_URL='https://bsz.ibs-bw.de/hshn?x='` wiederholt. Das ist keine
Code-Korrektur, sondern nur eine Messhilfe; der Default bleibt FAIL.

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
| 14 | `search` README live (Default-Base) | `bibliothek search "Grundlagen der Hydraulik" --json` | Treffer, Exit 0 | **FAIL** | `scratch/qa/10-live-search-hydraulik.json`: Exit 4, `Kein Formular in der Antwort gefunden.` |
| 15 | `show` README live (Default-Base) | `bibliothek show "Grundlagen der Hydraulik" --json` | Detail, Exit 0 | **FAIL** | `scratch/qa/31-default-show.json`: Exit 4, `Kein Formular in der Antwort gefunden.` |
| 16 | `login` live Default-Base (Dummy, GET scheitert vor POST) | `BIBLIOTHEK_USER=qa-dummy … bibliothek login --json` | Formular erreichbar | **FAIL** | `scratch/qa/71-default-login.json`: Exit 3, `Login-Formular nicht erreichbar: HTTP 404` |
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
| 34 | `--available` | `search "Python" --available --limit 5` vs. ohne | Ranking/bevorzugt verfügbare Treffer | **FAIL** | `scratch/qa/40-live-python-limit5.json` und `43-live-available.json`: `results` byte-gleich; nur `available_only` unterscheidet sich |
| 35 | Suchfelder Autor/Signatur | Live-Suche | `Grollius, Horst-W.` und Signatur | **FAIL** | `author: "Horst-W. Grollius. - 10. Auflage. - Hanser"`, `signature: ""` (z. B. `scratch/qa/14-*.json`) |
| 36 | `show` per ID live | `bibliothek show AK63638611 --json` (Override) | Detail mit Standort/Status | **FAIL** | `scratch/qa/47-live-show-id.json`: nur Trefferfelder, `locations: []`, `signature: ""`; kein Detail-Request |
| 37 | `show` per Titel live | `script -qec "bibliothek show 'Grundlagen der Hydraulik'"` (Override) | Detailfelder | **FAIL** | `scratch/qa/50-live-show-title-tty.log`: `Titel: Ende der Sitzung` … Exit 0 |
| 38 | `show` mehrere Treffer ohne TTY | `bibliothek show "Hydraulik" --json` | Exit 1 mit Kandidaten | OK | `scratch/qa/49-live-show-multi.json`: 20 Kandidaten, Hinweis auf ID |
| 39 | `show` mehrere Treffer im TTY | Auswahl `1` | Detail des Treffers | **FAIL** | `scratch/qa/51-live-show-multi-tty.log`: nach Auswahl `Titel: Ende der Sitzung` |
| 40 | `show` unbekannte ID | `bibliothek show AK99999999 --json` | Exit 4, nächster Schritt | OK | `scratch/qa/48-live-show-missing.json`: `Prüfe die ID oder nutze bibliothek search …` |
| 41 | TTY vs. `--json` | `search …` mit/ohne `--json` | TTY Text, `--json` genau ein Objekt | OK | `scratch/qa/52-live-search-tty.log` (Text), `60-tty-json.log` (JSON) |
| 42 | Parser-/Usage-Fehler mit `--json` | `bibliothek search --json` | stdout genau ein JSON-Objekt, Exit 1 | OK | `scratch/qa/55-argparse-stdout.txt`; Usage auf stderr |
| 43 | Netzwerkfehler | `BIBLIOTHEK_BASE_URL=http://127.0.0.1:1 bibliothek search …` | Exit 3, nächster Schritt, kein Traceback | OK | `scratch/qa/32-neterr-search.json`, `33-neterr-login.json` |
| 44 | `locations` | `script -qec "bibliothek locations"` | 4 Standorte, lesbar | OK | `scratch/qa/53-live-locations-tty.log` |
| 45 | Watch lokal | `watch add/list/remove` | Exit 0, idempotent | OK | `watch add Robotik --limit 7` → `e7c85b6a`; `remove` zweimal `noop` |
| 46 | Session-Schutz | `stat -c '%a' session.json`; Log prüfen | 0600, kein Passwort | OK | `600`, `21-fake-login.log` ohne Passwort |
| 47 | Keine Tracebacks | `grep -R Traceback scratch/qa` | keine Treffer | OK | Suche über alle QA-Logs ohne Treffer |

**Zählung: 39 OK / 47, 8 FAIL.**

## Offene FAILs

1. **Default-Basis-URL live defekt (kritisch).** `BIBLIOTHEK_BASE_URL=https://bsz.ibs-bw.de/hshn`
   funktioniert nicht mehr, weil der Code an mehreren Stellen `root + "/"` lädt und
   `https://bsz.ibs-bw.de/hshn/` inzwischen HTTP 404 liefert. `/hshn` selbst leitet
   mit 301 auf `/aDISWeb/app?…&sp=SOPAC04` um. Betroffen: `search`, `show`, `login`
   (und damit auch Konto/Verlängern). Belege: `10-*`, `30-*`, `31-*`, `71-*`,
   `scratch/qa/11-live-root.headers`. Ein Override mit `?x=` zeigt, dass die
   Suchlogik selbst funktioniert.
2. **Live-Detail (`show` per Titel) liefert „Ende der Sitzung“ mit Exit 0.**
   Der Detail-POST baut die action-URL ohne die `;jsessionid=…` aus dem
   Formular-`action` neu zusammen; die Antwort ist eine Sitzungsende-Seite.
   Statt eines Fehlers wird sie als Titel ausgegeben. Belege: `15-*`, `50-*`, `51-*`.
3. **`show` per ID lädt gar kein Detail.** Der ID-Zweig gibt nur die Trefferfelder
   zurück; `locations`, `copies`, `signature`, Status und Frist fehlen. Beleg:
   `47-live-show-id.json`.
4. **`--available` ist wirkungslos.** Die Trefferliste ist identisch zu einem Lauf
   ohne den Schalter; es gibt weder einen Serverparameter noch eine clientseitige
   Bevorzugung. Belege: `40-live-python-limit5.json` vs. `43-live-available.json`.
5. **Suchfelder sind verschmutzt/leer.** `author` enthält Edition und Verlag
   (`Horst-W. Grollius. - 10. Auflage. - Hanser`), `signature` ist live leer.
   Das weicht von `docs/UX.md` (Name, Signatur) ab. Beleg: `14-*`, `58-media-book.json`.

Nicht als FAIL gewertet, aber Beobachtung: unbekannte Medientypen werden
unverändert kleingeschrieben (`stücktitel/band`), siehe `58-media-all.json`.

## Nicht live prüfbar

`loans`, `verlaengern` und `renew` benötigen ein echtes Konto. Ohne
Zugangsdaten wurden nur die Wege ohne Request (Exit 2/5) live geprüft und die
vollständigen Formularschritte gegen den Fake-Server (`ux-routes`). Es wurde
keine echte Anmeldung und keine echte Verlängerung ausgelöst.
