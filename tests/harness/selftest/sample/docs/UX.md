# Demo-Tool

```ux-meta
{"tool": "demo", "install": "pipx install demo", "base_url_env": "DEMO_BASE_URL"}
```

## Angebote ansehen

```ux-session
$ pipx install demo
$ demo list
< Angebote
! exit 0
```

## Kurs buchen

```ux-session
$ demo book 1
< [j/N]
> j
< gebucht
! exit 0
```

```ux-routes
[{"method": "GET", "path": "/angebote", "response": "tests/fixtures/ux/angebote.html", "status": 200, "content_type": "text/html; charset=utf-8"}]
```

```ux-formsteps
[{"id": "kurs_waehlen", "method": "POST", "path": "/cgi/anmeldung.fcgi", "sends": ["BS_Kursid_32304"], "response": "tests/fixtures/ux/step1.html", "before_confirm": true, "live": "erkundet"},
 {"id": "daten", "method": "POST", "path": "/cgi/anmeldung.fcgi", "sends": ["vorname", "name"], "response": "tests/fixtures/ux/step2.html", "live": "synthetisch"},
 {"id": "verbindlich", "method": "POST", "path": "/cgi/anmeldung.fcgi", "sends": ["fid"], "response": "tests/fixtures/ux/step3.html", "final": true, "live": "synthetisch"}]
```
