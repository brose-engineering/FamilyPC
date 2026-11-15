# MANUELLE_TESTS.md — manuelle Checkliste pro Feature (FAM-3)

Auf der Test-VM ausführen (siehe `docs/SETUP.md`). Pro Testlauf: frischer
Snapshot „familypc-basis", dann `sudo ~/FamilyPC/scripts/install.sh`.

Testkonten: `parent` (sudo), `kind1`, `kind2` — Passwort jeweils `familypc`.

**Output teilen ohne gemeinsame Zwischenablage:** `scripts/vm_report.sh --jira FAM-x`
→ Report als Anhang am Jira-Ticket (Details in `docs/VM_REPORT.md`).

## FAM-2 — Projekt-Skeleton & Daemon-Sockel

- [ ] `sudo scripts/install.sh` läuft fehlerfrei durch (auch 2. Mal = idempotent)
- [ ] `systemctl status familypc` → `active (running)`, Prozess als root
- [ ] `journalctl -u familypc -f` zeigt Start-Zeile + Heartbeat (Default 60 s; testweise 10 s in Config)
- [ ] Config-Fehler (z. B. `heartbeat_interval_seconds: 0`) → `Config-Fehler:` im Journal, Exit 2, **kein Restart-Loop**; nach Fix `sudo systemctl restart familypc` → läuft
- [ ] `sudo systemctl stop familypc` → „Daemon gestoppt" im Log, fail-open (keine Sperren aktiv)
- [ ] `sudo scripts/uninstall.sh` entfernt Unit, `/opt/familypc`, `/etc/familypc`, `/var/lib/familypc`

Details: `docs/FAM-2_VM_TEST.md`

## FAM-4 — Session-Tracking & Zeitverbrauch

Details: `docs/FAM-4_VM_TEST.md`. Query: `sudo sqlite3 /var/lib/familypc/usage.db "SELECT user, round(seconds,1) FROM usage WHERE day='$(date +%F)';"`

- [ ] `kind1` grafisch anmelden, 10 min warten → DB zeigt ca. 600 s für kind1 (±10 s Poll-Intervall)
- [ ] Reboot → Verbrauch bleibt erhalten (reboot-sicher, Tabelle `usage(day, user, seconds)`)
- [ ] reine SSH-Session von kind1 zählt **nicht** (`count_remote_sessions: false`)
- [ ] Fast-User-Switching kind1 ↔ kind2 → beide zählen weiter (`count_inactive_sessions: true`)
- [ ] `root`/Daemon-Sessions tauchen nicht auf (`excluded_users`)
- [ ] Reset um `reset_hour` (Default 00:00) — neuer Nutzungstag = frischer Zähler

## FAM-5 — Internet-Sperre pro Konto (nftables)

Details: `docs/FAM-5_VM_TEST.md`. Tabelle: `nft list table inet familypc`.

- [ ] kind1 mit `internet_enabled: false` → `curl https://example.com` + DNS schlagen fehl
- [ ] `parent` und `kind2` surfen normal (Admin/protected unberührt, root nie blockiert)
- [ ] Restart mehrfach → keine Doppel-Regeln; Reboot → Regeln idempotent wieder da
- [ ] `systemctl stop familypc` → Tabelle weg (fail-open, ExecStopPost + Daemon-Clear)
- [ ] Koexistenz mit ufw geprüft
- [ ] `internet_enabled: true` → Sperre aufgehoben

## FAM-7 + FAM-8 — Tagesbudget & Nutzungsfenster

Details: `docs/FAM-7_FAM-8_VM_TEST.md` (Config-Beispiel, PAM-Checks im Journal).

- [ ] kind1 mit `daily_budget_minutes: 15` → Notification bei 10 und 5 min Restzeit (Desktop von kind1)
- [ ] bei 0 min → Logout (`loginctl terminate-user`); Re-Login am selben Tag verweigert (PAM: `DENY Tagesbudget aufgebraucht`)
- [ ] nach Mitternacht (Reset) → Login wieder möglich
- [ ] Fenster heute z. B. 15:00–23:00 → Login um 14:00 verweigert (`DENY ausserhalb des Nutzungsfensters`)
- [ ] Login innerhalb des Fensters möglich
- [ ] Fensterende während Session → Vorwarnung (10 min) → Logout
- [ ] `parent` (protected_users) wird nie eingesperrt; Daemon-Stop = fail-open (Login erlaubt)
- [ ] reboot-sicher; uninstall.sh entfernt PAM-Zeile aus /etc/pam.d/common-auth

## FAM-9 — Internet-Tagesbudget pro Konto

Details: `docs/FAM-9_VM_TEST.md`. Verbrauch: Tabelle `internet_usage(day, user, seconds)`.

- [ ] kind1 mit `internet_daily_budget_minutes: 2` → nach 2 min aktiver Session kein HTTP/DNS mehr (`nft list table` zeigt skuid drop), Notification „Internet-Zeit aufgebraucht"
- [ ] Verbrauch nur bei aktiver Session (internet_usage steigt nur dann)
- [ ] PC bleibt nutzbar (Session läuft weiter), andere Konten unberührt
- [ ] Reset um Mitternacht; `internet_enabled: false` hat Vorrang vor dem Budget
- [ ] fail-open wie FAM-5 (stop -> Tabelle weg)

## FAM-10 — Admin-UI

Details: `docs/FAM-10_VM_TEST.md`. UI: `http://127.0.0.1:8787` (nur Admin-Sitzung, sudo-Gruppe).

- [ ] UI auf `127.0.0.1` nur aus Admin-Sitzung (sudo-Gruppe) erreichbar (`curl` als kind1 → 403, `ss -tlnp` zeigt nur 127.0.0.1:8787)
- [ ] Übersicht zeigt Restzeiten (PC + Internet), Fenster- und Internet-Status live (5 s)
- [ ] Budget im UI auf 5 min setzen → `Config neu geladen` im Journal → kind1 wird nach 5 min abgemeldet (ohne Daemon-Neustart)
- [ ] Internet an/aus + Internet-Budget + Fenster je Wochentag per UI änderbar → nft/PAM wirken sofort
- [ ] ungültige Eingabe (z. B. Fenster 19:00-15:00) → 422, Config-Datei bleibt unverändert
- [ ] fail-open unverändert (Daemon-Stop → UI weg, PAM fail-open, nft-Tabelle weg)
