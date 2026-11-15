# FAM-5 — Manueller VM-Test: Internet-Sperre pro Konto via nftables (Yannic)

Voraussetzung: FAM-4 installiert, Testkonten vorhanden.

Config `/etc/familypc/config.yaml`:

```yaml
accounts:
  kind1:
    internet_enabled: false    # Internet komplett aus für kind1
```

```bash
sudo systemctl restart familypc
nft list table inet familypc     # Tabelle + skuid-Regeln sichtbar
```

## Schritte

1. **Sperre greift**: als kind1 anmelden (erlaubt, Fenster/Budget beachten) →
   ```bash
   curl -sS -m 5 https://example.com   # schlägt fehl (Timeout/Connection refused)
   ping -c1 8.8.8.8                     # schlägt fehl
   ```
2. **Admin unberührt**: als parent/yannic `curl https://example.com` → funktioniert.
3. **Idempotent / keine Doppel-Regeln**: `sudo systemctl restart familypc` mehrfach →
   `nft list table inet familypc` zeigt pro uid genau 2 Regeln (output+input), nicht mehr.
4. **Reboot-sicher**: `sudo reboot`, nach Boot `nft list table inet familypc` → Regeln
   wieder da (Daemon stellt sie beim Start idempotent her).
5. **Fail-open**: `sudo systemctl stop familypc` → `nft list table inet familypc` →
   "No such file or directory" (Tabelle weg), kind1 hat wieder Internet (curl geht).
   `sudo systemctl start familypc` → Sperre wieder aktiv.
6. **Koexistenz mit ufw**: `sudo ufw status` — ufw-Regeln und familypc-Tabelle
   koexistieren (eigene Tabelle, priority 0; ufw nutzt eigene Chains).
7. **Config-Schalter**: `internet_enabled: true` für kind1 + restart → kind1 surft wieder.

## Journal-Kontrolle

```bash
journalctl -u familypc -n 50 --no-pager | grep -i nft
# erwartet: 'nftables Tabelle familypc gesetzt: blockierte uids=[1002]' bzw. 'entfernt (fail-open)'
```
