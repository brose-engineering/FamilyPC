# FAM-4 — Manueller VM-Test: Session-Tracking & Zeitverbrauch (Yannic)

Voraussetzung: Test-VM mit `parent`/`kind1`/`kind2` (SETUP.md), FamilyPC installiert
(`sudo scripts/install.sh`), Config mit `tracking:`-Sektion (Default aktiv, siehe
`/etc/familypc/config.yaml`).

DB: `/var/lib/familypc/usage.db`, Tabelle `usage(day, user, seconds)` — Nutzungstag
= lokales Datum ab `reset_hour` (Default 00:00).

Hilfreiches Query (heute, lokales Datum):

```bash
TODAY=$(date +%F)
sudo sqlite3 /var/lib/familypc/usage.db "SELECT user, round(seconds,1) FROM usage WHERE day='$TODAY' ORDER BY user;"
```

## Schritte

1. **Daemon frisch starten, Tracking-Logzeile prüfen**
   ```bash
   sudo systemctl restart familypc
   journalctl -u familypc -n 10 --no-pager | grep -i tracking
   # erwartet: "Session-Tracking aktiv (poll=10s, reset=00:00, remote=False, inaktiv=True, excluded=root)"
   ```

2. **kind1 10 Minuten angemeldet → DB zeigt ca. 10 Minuten**
   ```bash
   # in der grafischen Sitzung als kind1 anmelden, 10 min warten (z. B. offen lassen)
   sudo sqlite3 /var/lib/familypc/usage.db "SELECT user, round(seconds,1) FROM usage WHERE day='$(date +%F)';"
   # erwartet: kind1 ca. 600 s (Abweichung max. poll_interval_seconds=10 s)
   ```

3. **Reboot-sicher**
   ```bash
   sudo reboot
   # nach Reboot erneut obiges Query: kind1-Wert ist erhalten (derselbe Nutzungstag)
   ```

4. **Reine SSH-Session zaehlt nicht**
   ```bash
   # als parent: ssh kind1@localhost  (Session type=tty, remote=yes)
   # 2 Minuten offen halten, dann Query: kind1-Wert steigt in der Zeit NICHT
   ```

5. **Fast-User-Switching zaehlt weiter**
   ```bash
   # kind1 grafisch anmelden, dann zu kind2 wechseln (Abmelden-Menue / Strg+Alt+F2)
   loginctl list-sessions --no-pager   # kind1-Session hat state=online
   # Query nach 2 Minuten: kind1-Wert steigt weiter (count_inactive_sessions: true)
   # zum Gegen-Test in Config count_inactive_sessions: false + restart -> kind1 bleibt stehen
   ```

6. **Excluded users**
   ```bash
   # root-Session (z. B. su -) taucht nicht in der DB auf (excluded_users: ["root"])
   ```

7. **Reset konfigurierbar**
   ```bash
   # in Config tracking.reset_hour auf z. B. 4 setzen + sudo systemctl restart familypc
   # Nutzungstag wechselt dann um 04:00 statt 00:00 (Coverage im Unit-Test test_reset_hour_konfigurierbar)
   ```

## Ergebnis hier reinkopieren / an FAM-4 anhängen
