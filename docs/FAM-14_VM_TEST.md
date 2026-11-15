# FAM-14 — Manueller VM-Test: Mobile UX & Quick-Actions

Voraussetzung: FAM-12/13 installiert (`git pull && sudo ./scripts/install.sh && sudo systemctl restart familypc-panel`).

## Schritte

1. **Login + SSE-Live:** Browser (Handy im WLAN oder Desktop-Browser mit DevTools-Geräteansicht 375 px):
   `https://familypc.local:8787` → Login → Liste. Restzeit aktualisiert sich **live ohne Reload**
   (SSE `/api/events`, sichtbar z. B. wenn kind1 angemeldet ist und die Sekunden runterlaufen).
2. **Quick-Actions je Konto (ab 375 px Breite, grosse Touch-Ziele):**
   - `+15` antippen → kind1 Tagesbudget steigt um 15 min (sofort in Config, Daemon lädt neu, kein Restart):
     ```bash
     sudo grep -A3 'kind1:' /etc/familypc/config.yaml
     sudo journalctl -u familypc -n 10 --no-pager | grep 'Config neu geladen'
     ```
   - „Verlängern in drei Taps": +30 antippen → Budget +30.
   - **Session beenden**: kind1 anmelden, dann Button → `loginctl list-sessions` zeigt kind1 nicht mehr.
   - **Internet an/aus**: Button → `sudo nft list table inet familypc` zeigt `skuid <uid>` sofort (reject) bzw. entfernt.
3. **Responsive:** DevTools auf 375×667 — Karten statt Tabelle, Buttons ≥ 44 px.
4. **Ohne Login keine Quick-Actions:** `curl -k -X POST https://127.0.0.1:8787/api/accounts/kind1/extend -d '{"minutes":15}'` → 401.

## API

```bash
CSRF=$(awk '/familypc_csrf/{print $NF}' /tmp/cj)   # nach Login mit Cookie-Jar
curl -sk -b /tmp/cj -H "X-CSRF-Token: $CSRF" -X POST https://127.0.0.1:8787/api/accounts/kind1/extend -H 'Content-Type: application/json' -d '{"minutes":30}'
curl -sk -b /tmp/cj -H "X-CSRF-Token: $CSRF" -X POST https://127.0.0.1:8787/api/accounts/kind1/terminate
curl -sk -b /tmp/cj -H "X-CSRF-Token: $CSRF" -X POST https://127.0.0.1:8787/api/accounts/kind1/internet -H 'Content-Type: application/json' -d '{"enabled":false}'
curl -sk -b /tmp/cj -N https://127.0.0.1:8787/api/events   # SSE-Stream (data: {...} alle 3 s)
```
