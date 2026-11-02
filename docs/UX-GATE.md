# UX-Gate-Bericht

Datum: 2026-11-02

Geprüft wurde der Stand nach den UX-Fixes aus Schritt S4. Beide Gates liefen
gegen den Fake-Server, ohne echte Zugangsdaten und ohne Schreibaktionen auf
echten Konten.

## Aufrufe und Exit-Codes

| Befehl | Exit-Code | Ergebnis |
| ------ | --------- | -------- |
| `python3 tests/harness/ux_check.py . --report scratch/ux_check.md` | 0 | PASS |
| `python3 tests/harness/ux_session.py . --report scratch/ux_session.md` | 0 | PASS |

## ux_check.py

- Repo: `bibliothek-cli`
- Tool: `bibliothek`
- Modus: voll
- Ergebnis: PASS

| ID | Ergebnis | Befund |
|---|---|---|
| UX00 | PASS | 29 Request(s) am Fake-Server, keine Fremdverbindung |
| UX01 | PASS | docs/UX.md: 3 Sitzungen, 3 formsteps |
| UX02 | PASS | Credential-Env BIBLIOTHEK_PASSWORD, BIBLIOTHEK_USER über `login` |
| UX03 | PASS | --help, --version und 9 Unterkommandos mit Exit 0 |
| UX04 | PASS | 9 Unterkommandos ohne Pflicht-Option statt positional |
| UX05 | PASS | 3 Sitzungen ohne JSON/Traceback im TTY |
| UX06 | PASS | Schnellstart: 4 Tool-Befehle, Installation passt |
| UX07 | PASS | 1 schreibende Sitzung(en) mit [j/N] |
| UX08 | PASS | alle formsteps in Reihenfolge und mit allen Feldern gesendet |
| UX09 | PASS | 1 schreibende Sitzung(en): Voraussetzungen vor [j/N] und Login-Felder vollständig |

## ux_session.py

- Tool: `bibliothek`
- Repo: `bibliothek-cli`
- Ergebnis: PASS

| Sitzung | Lauf | Ergebnis | Befund |
|---|---|---|---|
| Installation und Login | 1 | PASS | OK |
| Titel nach Namen suchen und Detail anzeigen | 1 | PASS | OK |
| Ausleihe verlängern | a (N) | PASS | OK |
| Ausleihe verlängern | b (j) | PASS | OK |

## Behobene Ursachen

- `show` gibt Standort und Status als eigene Felder aus und übernimmt den
  Autor aus der Trefferliste (`Grollius, Horst-W.`).
- Das Konto-Fixture trennt Titel und Autor in der Ausleihe mit einem
  Gedankenstrich, wie es die UX-Sitzung erwartet.
- Ein `N` auf die Rückfrage `Verlängerung verbindlich? [j/N]` beendet den
  Befehl ohne schreibende Requests mit Exit 0.
- Die Installationssitzung enthält keine separate PATH-Erwartung mehr; das
  Gate prüft den Befehl nach der Installation selbst.
