# FAM-7 + FAM-8 — Manueller VM-Test: Tagesbudget & Nutzungsfenster (Yannic)

Voraussetzung: FAM-4 installiert (siehe FAM-4_VM_TEST.md), Testkonten parent/kind1/kind2.

Config-Beispiel `/etc/familypc/config.yaml` (als parent editieren):

```yaml
enforcement:
  enabled: true
  warn_minutes: [10, 5]
  window_prewarning_minutes: 10
  protected_users: ["parent"]
accounts:
  kind1:
    daily_budget_minutes: 15
    windows:
      0: [{ start: "15:00", end: "23:00" }]   # Mo
      1: [{ start: "15:00", end: "23:00" }]   # Di
      2: [{ start: "15:00", end: "23:00" }]   # Mi
      3: [{ start: "15:00", end: "23:00" }]   # Do
      4: [{ start: "15:00", end: "23:00" }]   # Fr
      5: [{ start: "09:00", end: "23:00" }]   # Sa
      6: [{ start: "09:00", end: "23:00" }]   # So
```

```bash
sudo systemctl restart familypc
journalctl -u familypc -n 5 --no-pager | grep -i control   # Control-Socket aktiv
```

## FAM-7 — Tagesbudget (kind1: 15 Minuten)

1. kind1 grafisch anmelden (Login innerhalb Fenster erlaubt).
2. Nach ~5 min: Notification „noch 10 Minuten" auf kind1-Desktop; nach ~10 min: „noch 5 Minuten".
3. Nach 15 min: Notification „Zeit aufgebraucht" + kind1 wird abgemeldet
   (`loginctl list-sessions` zeigt kind1 nicht mehr; Journal: `budget_logout`).
4. Erneuter Login kind1 am selben Tag wird **verweigert** (PAM-Hook; lightdm zeigt Fehler,
   Journal: `PAM-Check kind1 -> DENY Tagesbudget aufgebraucht`).
5. parent/kind2 können sich jederzeit anmelden (protected / nicht konfiguriert).
6. Reset um Mitternacht: Unit-Tests decken Rollover ab; DB: neuer `day`-Eintrag.

## FAM-8 — Nutzungsfenster

1. kind1 um 14:00 (außerhalb 15:00-23:00) anmelden versuchen → Login verweigert
   (Journal: `PAM-Check kind1 -> DENY ausserhalb des Nutzungsfensters`).
2. kind1 um 15:00 anmelden → erlaubt.
3. Fensterende während Session testen: Fenster für heute auf `start: <jetzt>, end: <jetzt+12min>`
   setzen, `sudo systemctl restart familypc`, kind1 anmelden → nach ~2 min Vorwarnung
   „Nutzungsfenster endet bald", nach Fensterende Logout (Journal: `window_terminated`).
4. Reboot-sicher: Config bleibt, PAM-Zeile in `/etc/pam.d/common-auth` bleibt.

## Fail-open prüfen

```bash
sudo systemctl stop familypc
# Login als kind1 jetzt erlaubt (PAM fail-open), keine Sperren aktiv
sudo systemctl start familypc
```

## Deinstallation

`sudo scripts/uninstall.sh` entfernt u. a. die PAM-Zeile (`familypc-pam-check`) aus
`/etc/pam.d/common-auth` und `/run/familypc`.
