# FAM-9 — Manueller VM-Test: Internet-Tagesbudget pro Konto (Yannic)

Voraussetzung: FAM-5 (nftables) getestet. Config `/etc/familypc/config.yaml`:

```yaml
accounts:
  kind1:
    internet_enabled: true            # an (Vorrang vor Budget, wenn false)
    internet_daily_budget_minutes: 2 # 2 Minuten Internet heute
```

```bash
sudo systemctl restart familypc
sudo sqlite3 /var/lib/familypc/usage.db "SELECT * FROM internet_usage WHERE day='$(date +%F)';"
```

## Schritte

1. kind1 grafisch anmelden → Internet geht (`curl -m 5 https://example.com` -> 200).
2. Internet-Verbrauch wird nur bei aktiver Session gezaehlt:
   `SELECT * FROM internet_usage ...` steigt im Sekundentakt.
3. Nach 2 Minuten: Notification „Internet-Zeit aufgebraucht" auf kind1-Desktop;
   `nft list table inet familypc` enthaelt `meta skuid 1002 drop`;
   `curl`/`ping` schlagen fehl — **PC-Session laeuft weiter** (kind1 bleibt angemeldet).
4. Andere Konten (parent) surfen normal; kind1 ohne Internet-Budget unberuehrt.
5. Reset um Mitternacht (neuer `day` in internet_usage).
6. Vorrang-Regel: `internet_enabled: false` sperrt dauerhaft, egal wie viel Budget Rest hat
   (andersrum: Budget aufgebraucht + enabled true -> gesperrt bis Mitternacht).
7. Fail-open wie FAM-5: `systemctl stop familypc` -> Tabelle weg -> Internet wieder da.

## Journal

```bash
journalctl -u familypc -n 80 --no-pager | grep -iE 'internet|nft'
# erwartet: 'Internet-Budget kind1 aufgebraucht (..s/2min)' + 'nftables Tabelle familypc gesetzt: blockierte uids=[1002]'
```
