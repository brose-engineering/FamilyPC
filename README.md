<p align="center">
  <img src="docs/assets/familypc-banner.svg" alt="FamilyPC — Nutzungszeiten & Internet-Sperre pro Nutzerkonto auf Linux Mint" width="100%">
</p>

<h1 align="center">FamilyPC</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Linux-Mint-87CF3E?logo=linuxmint&logoColor=white" alt="Linux Mint">
  <img src="https://img.shields.io/badge/systemd-service-5A5A5A?logo=systemd&logoColor=white" alt="systemd Service">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
</p>

Daemon für **Linux Mint**, der pro Nutzerkonto die PC-Nutzung steuert:

- **Tagesbudget** in Minuten — Warnung per Desktop-Notification, Logout bei Ablauf
- **Nutzungszeitfenster** je Wochentag — Login außerhalb wird verweigert, bei Fensterende Logout mit Vorwarnung
- **Internetzugang** pro Konto an/aus plus **Internet-Tagesbudget** — der PC bleibt auch ohne Internet nutzbar

## Installation (auf der Mint-VM, als root)

```bash
sudo scripts/install.sh     # installiert nach /opt/familypc + /etc/familypc, aktiviert & startet familypc.service
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
  dadurch entsteht **kein Restart-Loop** bei Config-Fehlern. Nach dem Fix in
  `/etc/familypc/config.yaml`: `sudo systemctl restart familypc`.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest          # Unit-Tests (simulierte Uhr, keine echten Sleeps)
.venv/bin/python -m familypc --config config/config.yaml --check-config   # Config prüfen
.venv/bin/python -m familypc --config config/config.yaml                  # Daemon lokal starten
```

## Projekt-Layout

```
├── familypc/                  # Daemon-Paket
│   ├── config.py              # Config-Schema (pydantic) & Laden von /etc/familypc/config.yaml
│   ├── daemon.py              # Hauptschleife, Heartbeat, sauberes Herunterfahren
│   ├── sessions.py            # Session-Erkennung via loginctl (FAM-4)
│   ├── tracker.py             # Zeitverbrauch pro Konto (FAM-4)
│   ├── usage.py               # SQLite-Persistenz usage.db (FAM-4)
│   └── __main__.py            # CLI-Einstieg (python -m familypc)
├── config/config.yaml         # Beispiel-Config
├── systemd/familypc.service   # systemd-Unit (root)
├── scripts/install.sh         # Installation (idempotent)
├── scripts/uninstall.sh       # Deinstallation
├── tests/                     # Unit-Tests
└── docs/                      # VM-Testanleitungen pro Story, Banner
docs/assets/familypc-banner.svg
```

## Doku & Tests

Manuelle VM-Testschritte pro Story liegen unter `docs/` (z. B. `docs/FAM-2_VM_TEST.md`).
Commit-Messages referenzieren den Jira-Key, z. B. `FAM-7: Warn-Notification bei Restzeit`.

## Lizenz

[MIT](LICENSE) — Copyright (c) 2026 Yannic Brose
