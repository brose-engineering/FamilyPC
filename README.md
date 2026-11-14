# FamilyPC

Daemon für Linux Mint, der pro Nutzerkonto **Nutzungszeiten durchsetzt** (Tagesbudget,
erlaubte Zeitfenster je Wochentag) und **Internetzugang beschränkt** (an/aus + Internet-Tagesbudget).
Backlog & Akzeptanzkriterien: Jira-Projekt **FAM** (brose-eng.atlassian.net). Details siehe `AGENTS.md`.

## Installation (auf der Mint-VM, als root)

```bash
sudo scripts/install.sh     # installiert nach /opt/familypc, /etc/familypc, aktiviert & startet familypc.service
sudo scripts/uninstall.sh   # entfernt alles wieder (inkl. Config und Nutzungsdaten)
```

`install.sh` ist idempotent: mehrfaches Ausführen ist schadlos, eine bestehende
`/etc/familypc/config.yaml` wird nicht überschrieben.

## Betrieb

```bash
systemctl status familypc          # Daemon aktiv?
journalctl -u familypc -f          # Logs inkl. Heartbeat (alle 60 s, konfigurierbar)
```

Konfiguration: `/etc/familypc/config.yaml` (Schema in `familypc/config.py`, validiert per pydantic).
**Fehlende Felder = Feature deaktiviert** — der Daemon startet trotzdem.

### Verhalten bei Daemon-Ausfall (fail-open)

- Stoppt der Daemon (egal warum), greifen **keine** Sperren mehr: Der PC bleibt voll nutzbar,
  Internet-Sperren (ab FAM-5) werden beim Stop entfernt. Es gibt kein Lockout-Risiko.
- Ist die Config ungültig, beendet sich der Daemon mit **Exit-Code 2** und Klartext-Meldung im
  journald. Die systemd-Unit wertet Exit 2 als sauberes Ende (`SuccessExitStatus=2`) —
  dadurch entsteht **kein Restart-Loop** bei Config-Fehlern. Zum Korrigieren:
  `sudo systemctl restart familypc` nach dem Fix in `/etc/familypc/config.yaml`.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # Unit-Tests (simulierte Uhr, keine echten Sleeps)
.venv/bin/python -m familypc --config config/config.yaml --check-config   # Config prüfen
.venv/bin/python -m familypc --config config/config.yaml                  # Daemon lokal starten
```

Manuelle VM-Testschritte pro Story liegen unter `docs/` (z. B. `docs/FAM-2_VM_TEST.md`).
