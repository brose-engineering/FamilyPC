# MANUELLE_TESTS.md — manuelle Checkliste pro Feature (FAM-3)

Auf der Test-VM ausführen (siehe `docs/SETUP.md`). Pro Testlauf: frischer
Snapshot „familypc-basis", dann `sudo ~/FamilyPC/scripts/install.sh`.

Testkonten: `parent` (sudo), `kind1`, `kind2` — Passwort jeweils `familypc`.

## FAM-2 — Projekt-Skeleton & Daemon-Sockel

- [ ] `sudo scripts/install.sh` läuft fehlerfrei durch (auch 2. Mal = idempotent)
- [ ] `systemctl status familypc` → `active (running)`, Prozess als root
- [ ] `journalctl -u familypc -f` zeigt Start-Zeile + Heartbeat (Default 60 s; testweise 10 s in Config)
- [ ] Config-Fehler (z. B. `heartbeat_interval_seconds: 0`) → `Config-Fehler:` im Journal, Exit 2, **kein Restart-Loop**; nach Fix `sudo systemctl restart familypc` → läuft
- [ ] `sudo systemctl stop familypc` → „Daemon gestoppt" im Log, fail-open (keine Sperren aktiv)
- [ ] `sudo scripts/uninstall.sh` entfernt Unit, `/opt/familypc`, `/etc/familypc`, `/var/lib/familypc`

Details: `docs/FAM-2_VM_TEST.md`

## FAM-4 — Session-Tracking & Zeitverbrauch

- [ ] `kind1` grafisch anmelden, 10 min warten → `sqlite3 /var/lib/familypc/usage.db` zeigt ca. 10 min für kind1
- [ ] Reboot → Verbrauch bleibt erhalten (reboot-sicher)
- [ ] reine SSH-Session von kind1 zählt **nicht**
- [ ] Fast-User-Switching kind1 ↔ kind2 → beide Sessions zählen weiter
- [ ] Reset um 00:00 (konfigurierbar)

## FAM-5 — Internet-Sperre pro Konto (nftables)

- [ ] kind1 mit `internet_enabled: false` → `curl https://example.com` schlägt fehl, DNS schlägt fehl
- [ ] `parent` und `kind2` surfen normal (Admin-Konto unberührt)
- [ ] Reboot → Sperre wieder aktiv, keine Doppel-Regeln (`nft list table familypc`)
- [ ] `systemctl stop familypc` → Sperre weg (fail-open, kein Lockout)
- [ ] Koexistenz mit ufw geprüft

## FAM-7 — Tagesbudget pro Konto

- [ ] kind1 mit `daily_budget_minutes: 15` → Desktop-Notification bei 10 und 5 min Restzeit
- [ ] bei 0 min → Logout (`loginctl terminate-user`), Re-Login am selben Tag blockiert
- [ ] nach Mitternacht (Reset) → Login wieder möglich

## FAM-8 — Nutzungsfenster pro Wochentag

- [ ] Fenster heute z. B. 15:00–19:00 → Login um 14:00 wird verweigert + Hinweis-Notification
- [ ] Login innerhalb des Fensters möglich
- [ ] Fensterende während laufender Session → Vorwarnung (Default 10 min) → Logout
- [ ] reboot-sicher

## FAM-9 — Internet-Tagesbudget pro Konto

- [ ] kind1 mit `internet_daily_budget_minutes: 10` → nach 10 min aktiver Session kein HTTP/DNS mehr
- [ ] PC bleibt weiter nutzbar (Session läuft), andere Konten unberührt
- [ ] Reset um Mitternacht; `internet_enabled: false` hat Vorrang vor dem Budget

## FAM-10 — Admin-UI

- [ ] UI auf `127.0.0.1` nur aus Admin-Sitzung (sudo-Gruppe) erreichbar
- [ ] Übersicht zeigt Restzeiten (PC + Internet) live
- [ ] Budget im UI auf 5 min setzen → kind1 wird nach 5 min abgemeldet (ohne Daemon-Neustart)
