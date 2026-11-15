# FAM-10 — Manueller VM-Test: Admin-UI (Übersicht + Regeln setzen)

Voraussetzung: FAM-9 installiert. Nach `git pull && sudo ./scripts/install.sh` ist die
UI konfiguriert (`ui:`-Sektion in `/etc/familypc/config.yaml`, Default an — falls die
bestehende Config die Sektion noch nicht hat, ergänzen):

```yaml
ui:
  enabled: true
  host: 127.0.0.1
  port: 8787
  admin_groups: ["sudo"]
```

```bash
sudo systemctl restart familypc
journalctl -u familypc -n 20 --no-pager | grep -i 'Admin-UI'   # erwartet: Admin-UI aktiv: http://127.0.0.1:8787
```

## Schritte

1. **Nur Admin-Sitzung:** Browser als `parent`/`yannic` (sudo-Gruppe) öffnen: `http://127.0.0.1:8787`
   → UI lädt, zeigt Konten mit Restzeit PC/Internet, Fenster- und Internet-Status (live, 5 s).
   ```bash
   curl -s -o /dev/null -w 'yannic: %{http_code}\n' http://127.0.0.1:8787/api/status          # 200
   sudo runuser -u kind1 -- curl -s -o /dev/null -w 'kind1: %{http_code}\n' http://127.0.0.1:8787/api/status  # 403
   sudo ss -tlnp | grep 8787                                                                  # LISTEN nur 127.0.0.1:8787
   ```
2. **Regeln per UI ändern (ohne Neustart):** kind1 auf „Bearbeiten" → Tagesbudget 5 Minuten →
   Speichern. Prüfen:
   ```bash
   journalctl -u familypc -f | grep -i 'Config neu geladen'   # Daemon hat die Datei übernommen
   sudo grep -A3 'kind1:' /etc/familypc/config.yaml
   ```
3. **VM-Test Akzeptanz:** kind1 grafisch anmelden → nach 5 Minuten Logout
   (Journal: `Budget kind1 aufgebraucht` + `budget_logout`; `loginctl` zeigt kind1 nicht mehr).
4. **Internet per UI schalten:** kind1 → Internet an/aus → Speichern →
   `sudo nft list table inet familypc` zeigt `skuid <uid>` sofort (reject/drop), ohne `systemctl restart`.
   Internet-Budget-Feld setzen → Sperre nach Ablauf (FAM-9-Verhalten).
5. **Fenster per UI setzen:** z. B. heute `HH:MM-HH:MM` ab jetzt+10 min → Login innerhalb erlaubt,
   PAM-DENY außerhalb (`PAM-Check kind1 -> DENY ausserhalb des Nutzungsfensters`).
6. **Ungültige Eingabe:** Fenster `19:00-15:00` → UI zeigt Fehler (422), Config-Datei bleibt unverändert.
7. **Fail-open unverändert:** `sudo systemctl stop familypc` → UI weg (Connection refused), PAM fail-open, nft-Tabelle weg.

## API (localhost only)

```bash
curl -s http://127.0.0.1:8787/api/status | python3 -m json.tool
curl -s http://127.0.0.1:8787/api/config
curl -s -X PUT http://127.0.0.1:8787/api/accounts/kind1 -H 'Content-Type: application/json' \
  -d '{"daily_budget_minutes": 30, "internet_enabled": true, "internet_daily_budget_minutes": 20, "windows": {"0": [{"start": "15:00", "end": "19:00"}]}}'
curl -s -X DELETE http://127.0.0.1:8787/api/accounts/kind1
```
