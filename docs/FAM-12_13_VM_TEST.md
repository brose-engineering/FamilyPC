# FAM-12 + FAM-13 — Manueller VM-Test: Panel-Login & Heimnetz (HTTPS)

Voraussetzung: FAM-10 installiert. `git pull && sudo ./scripts/install.sh` installiert
avahi-daemon, erzeugt das selbstsignierte Zertifikat und startet `familypc-panel.service`.

## FAM-12 — Eltern-Authentifizierung

```bash
# Initial-Account als root auf der Konsole anlegen (Passwort wird nicht angezeigt)
sudo /opt/familypc/venv/bin/familypc-panel-admin --config /etc/familypc/config.yaml add parent
sudo /opt/familypc/venv/bin/familypc-panel-admin --config /etc/familypc/config.yaml list
```

1. **Ohne Login kein Zugriff** (auch nicht localhost):
   ```bash
   curl -sk -o /dev/null -w 'ohne Login: %{http_code}\n' https://127.0.0.1:8787/api/status   # 401
   curl -sk -X PUT -o /dev/null -w 'PUT ohne Login: %{http_code}\n' https://127.0.0.1:8787/api/accounts/kind1 -H 'Content-Type: application/json' -d '{}'  # 401
   ```
2. **Falsches Passwort 5x -> Sperre:**
   ```bash
   for i in 1 2 3 4 5; do curl -sk -o /dev/null -w "%{http_code} " -X POST https://127.0.0.1:8787/api/login -H 'Content-Type: application/json' -d '{"username":"parent","password":"falsch"}'; done; echo   # 401 401 401 401 401
   curl -sk -X POST https://127.0.0.1:8787/api/login -H 'Content-Type: application/json' -d '{"username":"parent","password":"RICHTIG"}' -w '\n%{http_code}\n'   # 423 Locked
   journalctl -u familypc-panel -n 20 --no-pager | grep -i 'Panel-Login'   # Fehlversuche geloggt, Passwort NICHT im Log
   ```
3. **Login ok -> Session-Cookie (HttpOnly, Secure, SameSite=Strict) + CSRF-Cookie:**
   ```bash
   curl -sk -c /tmp/cj -X POST https://127.0.0.1:8787/api/login -H 'Content-Type: application/json' -d '{"username":"parent","password":"RICHTIG"}'
   grep familypc /tmp/cj   # familypc_session (HttpOnly) + familypc_csrf
   curl -sk -b /tmp/cj -o /dev/null -w 'mit Session: %{http_code}\n' https://127.0.0.1:8787/api/status   # 200
   ```
4. **CSRF-Schutz:** PUT ohne `X-CSRF-Token` -> 403; mit Header (Wert aus Cookie) -> 200:
   ```bash
   CSRF=$(awk '/familypc_csrf/{print $NF}' /tmp/cj)
   curl -sk -b /tmp/cj -o /dev/null -w 'PUT ohne CSRF: %{http_code}\n' -X PUT https://127.0.0.1:8787/api/accounts/kind1 -H 'Content-Type: application/json' -d '{"daily_budget_minutes":30}'   # 403
   curl -sk -b /tmp/cj -o /dev/null -w 'PUT mit CSRF: %{http_code}\n' -X PUT https://127.0.0.1:8787/api/accounts/kind1 -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"daily_budget_minutes":30}'  # 200
   ```
5. **Logout:** `curl -sk -b /tmp/cj -X POST https://127.0.0.1:8787/api/logout` -> danach /api/status -> 401.
6. **Passwort-Reset nur als root:** `sudo familypc-panel-admin --config ... passwd parent`.
7. Browser: `https://127.0.0.1:8787` -> Login-Maske; nach Login volle Bedienung (alle FAM-10-Funktionen).

## FAM-13 — Heimnetz / HTTPS

Config: `ui.host: 0.0.0.0` (Beispiel-Config default), `ui.port: 8787` (HTTPS), `ui.http_port: 8786` (Redirect).

```bash
sudo systemctl status familypc-panel.service --no-pager | head -6
sudo ss -tlnp | grep -E '8787|8786'        # 0.0.0.0:8787 (https) + 0.0.0.0:8786 (redirect)
curl -s -o /dev/null -w 'HTTP->HTTPS: %{http_code} -> %{redirect_url}\n' http://127.0.0.1:8786/   # 301 https://...
getent hosts familypc.local               # Avahi loest auf
curl -sk -o /dev/null -w 'familypc.local: %{http_code}\n' https://familypc.local:8787/api/status  # 401 (Login noetig)
# vom Handy im selben WLAN: https://familypc.local:8787 -> Browser-Zertifikatwarnung einmalig akzeptieren -> Login -> bedienen
# reboot-sicher: sudo reboot, danach wieder Panel erreichbar
```

## Deinstallation

`sudo scripts/uninstall.sh` entfernt u. a. beide Units, das Avahi-Servicefile, Zertifikate, panel.db.

## Automatisiert

```bash
sudo PANEL_PW=<panel-passwort> scripts/vm_test_fam12_13.sh --jira FAM-12
# oder lokal: sudo scripts/vm_test_fam12_13.sh   (Report unter /tmp/familypc-fam12-13-*.txt)
```

Das Script macht `reset-failed` + Restart, testet 401 ohne Login, 5x Fehlversuch -> 423,
Sperre (lockout kurz auf 1 min), Login -> Session -> CSRF 403/200, Logout -> 401,
HTTP->HTTPS-Redirect, `familypc.local` und listet die Panel-Accounts. Achtung: es setzt
`lockout_minutes` temporaer auf 1 und stellt die Config danach wieder her.

Hinweis: install.sh setzt `host-name=familypc` in `/etc/avahi/avahi-daemon.conf` — der PC
antwortet im LAN als **familypc.local** (der bisherige `<hostname>.local`-Name entfaellt damit).
