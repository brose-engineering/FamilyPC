# FAM-2 — Manueller VM-Test (auf der Mint-VM durch Yannic)

Voraussetzung: frische Mint-VM (siehe FAM-3), Repo auf der VM ausgecheckt.

## Schritte

1. **Installation**
   ```bash
   sudo scripts/install.sh
   ```
   - Erwartet: läuft ohne Fehler durch, endet mit `systemctl status`-Ausgabe.
   - Idempotenz: `sudo scripts/install.sh` ein zweites Mal ausführen → ebenfalls fehlerfrei,
     bestehende `/etc/familypc/config.yaml` bleibt unverändert (keine Doppel-Install).

2. **Daemon aktiv**
   ```bash
   systemctl status familypc
   ```
   - Erwartet: `active (running)`, Prozess läuft als root.

3. **Heartbeat im journald**
   ```bash
   journalctl -u familypc -f
   ```
   - Erwartet: Start-Zeile (`FamilyPC 0.1.0 startet ...`) und alle 60 s eine
     `Heartbeat: FamilyPC 0.1.0 aktiv, Uptime ... s`-Zeile.
   - Heartbeat-Intervall testweise in `/etc/familypc/config.yaml` auf 10 s setzen,
     `sudo systemctl restart familypc` → Heartbeats alle 10 s.

4. **Config-Fehler → kein Restart-Loop**
   ```bash
   sudoedit /etc/familypc/config.yaml   # z. B. heartbeat_interval_seconds: 0 eintragen
   sudo systemctl restart familypc
   systemctl status familypc
   journalctl -u familypc -n 20 --no-pager
   ```
   - Erwartet: Service geht auf `inactive (dead)` (nicht `activating`/auto-restart im Loop),
     journald zeigt `Config-Fehler: ...` mit Klartext. Config korrigieren,
     `sudo systemctl restart familypc` → läuft wieder.

5. **Sauberes Stoppen**
   ```bash
   sudo systemctl stop familypc
   journalctl -u familypc -n 5 --no-pager
   ```
   - Erwartet: `Daemon gestoppt` im Log, kein Absturz. Fail-open: Während der Daemon
     down ist, gibt es keinerlei Einschränkungen.

6. **Deinstallation**
   ```bash
   sudo scripts/uninstall.sh
   ls /opt/familypc /etc/familypc /var/lib/familypc   # alles weg
   systemctl status familypc                          # Unit unbekannt
   ```

## Config prüfen ohne Service-Start

```bash
/opt/familypc/venv/bin/python -m familypc --config /etc/familypc/config.yaml --check-config
```
Exit 0 = OK, Exit 2 = Config-Fehler (wird auch als `ExecStartPre` in der Unit genutzt).
