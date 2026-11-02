# UX-Spec: bibliothek-cli

Diese Spec beschreibt die drei wichtigsten Aufgaben für Menschen im Terminal:
Anmeldung am Bibliothekskonto, Suche nach einem Titel und die verbindliche
Verlängerung einer Ausleihe. Die Befehle sind so abtippbar, wie sie im
Terminal eingegeben werden.

Grundlage ist die Live-Erkundung des OPAC
`https://bsz.ibs-bw.de/hshn` (aDISWeb/BSZ OPAC04) am 2026-11-02. Suche,
Trefferliste, Vollanzeige, Anmeldemaske und der Vormerken-Einstieg wurden
lesend erkundet. Die Konto- und Verlängerungsseiten sind hinter dem Login und
wurden deshalb synthetisch nachgebaut; sie sind in den Fixtures als
`SYNTHETISCH` markiert.

## Meta

```ux-meta
{"tool": "bibliothek",
 "install": "pipx install git+https://github.com/smlfg/bibliothek-cli",
 "base_url_env": "BIBLIOTHEK_BASE_URL",
 "env": {"BIBLIOTHEK_BASE_URL": "https://bsz.ibs-bw.de/hshn"},
 "credential_env": ["BIBLIOTHEK_USER", "BIBLIOTHEK_PASSWORD"]}
```

`BIBLIOTHEK_BASE_URL` überschreibt die Basis-URL für Tests gegen einen
Fake-Server. `BIBLIOTHEK_USER` und `BIBLIOTHEK_PASSWORD` sind nur für Agenten;
im Terminal fragt `bibliothek login` interaktiv nach Ausweisnummer und
Passwort.

## Sitzungen

### Installation und Login

Der Login fragt im Terminal interaktiv nach Ausweisnummer und Passwort. Das
Passwort wird nicht angezeigt und nicht gespeichert; die Session landet in
einer Datei mit Rechten 0600. Erfolg gilt erst, wenn die Kontoseite sichtbar
ist.

```ux-session
$ pipx install git+https://github.com/smlfg/bibliothek-cli
< bibliothek
$ bibliothek login
< Ausweisnummer:
> 123456789
< Passwort:
> geheim
< Login erfolgreich als 123456789
! exit 0
```

### Titel nach Namen suchen und Detail anzeigen

Der Suchbegriff ist positional. Die Trefferliste zeigt Titel, Verfasser und
Jahr; `show` akzeptiert denselben Titel und zeigt die Vollanzeige mit
Standort, Signatur und Ausleihstatus.

```ux-session
$ bibliothek search "Grundlagen der Hydraulik"
< Treffer: 2 (angezeigt: 2)
< [1] Grundlagen der Hydraulik – Grollius, Horst-W. (2026) | ZL 4650 G875 (2026)
< [2] Technisches Zeichnen im Maschinenbau – Beispiel, Berta (2026) | ZG 9140 G875 (2026)
! exit 0
$ bibliothek show "Grundlagen der Hydraulik"
< Titel: Grundlagen der Hydraulik
< Autor: Grollius, Horst-W.
< Jahr: 2026
< Standort: TechCampus Heilbronn, Freihand / EG
< Signatur: ZL 4650 G875 (2026)
< Status: Ausgeliehen – fällig am 16.11.2026
< ID: AK63638611
! exit 0
```

### Ausleihe verlängern

`verlaengern` wählt die Ausleihe über den Titel, nicht über eine ID. Bei
mehreren passenden Ausleihen erscheint eine nummerierte Auswahl. Danach folgen
Titel und Frist als Zusammenfassung und die Frage mit Default Nein. Erst nach
`j` werden alle Formularschritte bis zur endgültigen Bestätigung gesendet.

```ux-session
$ bibliothek verlaengern "Grundlagen der Hydraulik"
< 1) Grundlagen der Hydraulik – Grollius, Horst-W. | fällig 16.11.2026
< 2) Grundlagen der Hydraulik / Übungsbuch | fällig 23.11.2026
< Auswahl [1-2]:
> 1
< Titel: Grundlagen der Hydraulik
< Frist: 16.11.2026
< Verlängerung verbindlich? [j/N]
> j
< Verlängerung bestätigt.
< Neues Fälligkeitsdatum: 07.12.2026
! exit 0
```

## Lesende Routen

`path` wird ohne Query exakt verglichen; die aDISWeb-Steuerung liegt in der
Query (`service=…`) und in Hidden-Feldern. Der Login-POST ist lesend, weil er
nur die Session aufbaut. Die Login- und Kontoseiten sind synthetisch, die
übrigen Antworten stammen aus der Live-Erkundung.

```ux-routes
[{"method":"GET","path":"/","response":"tests/fixtures/ux/home.html","status":200,"content_type":"text/html; charset=utf-8"},
 {"method":"GET","path":"/aDISWeb/app","query_contains":"service=loginform","response":"tests/fixtures/ux/login_synthetisch.html","status":200,"content_type":"text/html; charset=utf-8"},
 {"method":"POST","path":"/aDISWeb/app","query_contains":"service=login","response":"tests/fixtures/ux/konto_synthetisch.html","status":200,"content_type":"text/html; charset=utf-8"},
 {"method":"POST","path":"/aDISWeb/app","query_contains":"service=search","response":"tests/fixtures/ux/treffer.html","status":200,"content_type":"text/html; charset=utf-8"},
 {"method":"POST","path":"/aDISWeb/app","query_contains":"service=detail","response":"tests/fixtures/ux/detail.html","status":200,"content_type":"text/html; charset=utf-8"},
 {"method":"POST","path":"/aDISWeb/app","query_contains":"service=vormerken","response":"tests/fixtures/ux/login_synthetisch.html","status":200,"content_type":"text/html; charset=utf-8"}]
```

## Formularschritte der Verlängerung

Die Liste enthält alle Requests bis zur endgültigen Verlängerung. Schritt 1
lädt die Ausleihen (vor der `[j/N]`-Frage, löst nichts aus). Schritt 2 sendet
die Auswahl an aDISWeb und erhält die Bestätigungsseite. Schritt 3 bestätigt
verbindlich und trägt deshalb `final: true`. Alle drei Schritte sind
`synthetisch`, weil das Konto ohne Zugangsdaten nicht live einsehbar ist.

```ux-formsteps
[{"id":"konto_laden","method":"POST","path":"/aDISWeb/app","sends":["service","sp","selected"],"response":"tests/fixtures/ux/konto_synthetisch.html","before_confirm":true,"live":"synthetisch"},
 {"id":"verlaengern_absenden","method":"POST","path":"/aDISWeb/app","sends":["service","sp","cellCheck$0","textButton$1"],"response":"tests/fixtures/ux/verlaengern_bestaetigung_synthetisch.html","live":"synthetisch"},
 {"id":"verlaengern_bestaetigen","method":"POST","path":"/aDISWeb/app","sends":["service","sp","bestaetigungstoken","textButton"],"response":"tests/fixtures/ux/verlaengern_erfolg_synthetisch.html","final":true,"live":"synthetisch"}]
```

Bei `N` endet der Befehl nach `konto_laden` und sendet keinen Schritt ohne
`before_confirm`. Ohne Session und ohne TTY bricht `verlaengern` vor jedem
Request ab und verweist auf `bibliothek login`.
