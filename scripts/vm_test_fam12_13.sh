#!/usr/bin/env bash
# FamilyPC vm_test_fam12_13.sh — FAM-12/13 VM-Test auf der Panel-VM ausfuehren, Report speichern.
#
#   sudo scripts/vm_test_fam12_13.sh                 # Report unter /tmp
#   sudo scripts/vm_test_fam12_13.sh --upload        # Report zu Paste-Dienst, URL ausgeben
#   sudo scripts/vm_test_fam12_13.sh --jira FAM-12   # Report als Anhang an Jira-Ticket
#
# Panel-Passwort: PANEL_PW in Umgebung oder interaktiv abfragen.
# Achtung: fuer den Sperre-Test setzt das Script lockout_minutes kurzzeitig auf 1,
#         startet das Panel neu und stellt die Config danach wieder her.
set -uo pipefail

OUT="/tmp/familypc-fam12-13-$(date +%Y%m%d-%H%M%S).txt"
MODE="local"
JIRA_TICKET=""
case "${1:-}" in
  --upload) MODE="upload" ;;
  --jira)   MODE="jira"; JIRA_TICKET="${2:-}"; [[ -n "$JIRA_TICKET" ]] || { echo "Usage: $0 --jira <TICKET-KEY>" >&2; exit 1; } ;;
  "")       MODE="local" ;;
  *)        echo "Usage: $0 [--upload | --jira <TICKET-KEY>]" >&2; exit 1 ;;
esac

CONFIG=/etc/familypc/config.yaml
BASE="https://127.0.0.1:8787"
CJ=$(mktemp)
PANEL_PW="${PANEL_PW:-}"
if [[ -z "$PANEL_PW" ]]; then
  read -rs -p "Panel-Passwort fuer Account 'parent': " PANEL_PW
  echo
fi

{
  echo "===== FamilyPC FAM-12/13 VM-Test $(date -Is) ====="
  echo
  echo "--- reset-failed + Restart beider Services ---"
  sudo systemctl reset-failed familypc familypc-panel 2>&1 || true
  sudo systemctl restart familypc familypc-panel 2>&1 || true
  sleep 2
  sudo systemctl restart avahi-daemon 2>&1 || true
  sudo systemctl status familypc --no-pager | head -4
  sudo systemctl status familypc-panel --no-pager | head -4
  echo
  echo "--- journal familypc-panel (letzte 8) ---"
  sudo journalctl -u familypc-panel -n 8 --no-pager 2>&1 || true
  echo
  echo "--- ss: Ports 8787/8786 ---"
  sudo ss -tlnp | grep -E '8787|8786' || echo "(nichts)"
  echo
  echo "--- FAM-12: ohne Login kein API-Zugriff ---"
  curl -sk -o /dev/null -w 'GET /api/status ohne Login: %{http_code} (erwartet 401)\n' "$BASE/api/status"
  curl -sk -o /dev/null -w 'PUT /api/accounts/kind1 ohne Login: %{http_code} (erwartet 401)\n' -X PUT "$BASE/api/accounts/kind1" -H 'Content-Type: application/json' -d '{}'
  echo
  echo "--- FAM-12: 5x falsches Passwort, dann Sperre ---"
  for i in 1 2 3 4 5; do
    curl -sk -o /dev/null -w '%{http_code} ' -X POST "$BASE/api/login" -H 'Content-Type: application/json' -d '{"username":"parent","password":"falsch"}'
  done
  echo " (erwartet: 401 401 401 401 401)"
  curl -sk -o /dev/null -w 'Login mit RICHTIGEM PW waehrend Sperre: %{http_code} (erwartet 423)\n' -X POST "$BASE/api/login" -H 'Content-Type: application/json' -d "{\"username\":\"parent\",\"password\":\"$PANEL_PW\"}"
  echo
  echo "--- Panel-Login-Log (Passwort darf NICHT vorkommen) ---"
  sudo journalctl -u familypc-panel -n 30 --no-pager | grep -i 'Panel-Login' || echo "(keine Eintraege)"
  if sudo journalctl -u familypc-panel -n 30 --no-pager | grep -qF "$PANEL_PW"; then
    echo "!!! LEAK: Passwort im Log !!!"
  else
    echo "OK: Passwort nicht im Log."
  fi
  echo
  echo "--- Sperre-Test: lockout kurzzeitig auf 1 min (Config wird danach wiederhergestellt) ---"
  cp "$CONFIG" "$CONFIG.famtest.bak"
  # robust via Config-API (alte Configs ohne lockout_minutes-Zeile: sed wuerde nicht greifen)
  sudo /opt/familypc/venv/bin/python - "$CONFIG" <<'PY' || echo "PATCH FEHLGESCHLAGEN"
import sys
from familypc.config import load_config, save_config
p = sys.argv[1]
cfg = load_config(p)
if cfg.ui is None:
    raise SystemExit("keine ui-Sektion in Config")
cfg.ui.lockout_minutes = 1
save_config(cfg, p)
PY
  sudo systemctl restart familypc-panel 2>&1 || true
  sleep 2
  echo "warte 65 s ..."
  sleep 65
  code=$(curl -sk -c "$CJ" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/login" -H 'Content-Type: application/json' -d "{\"username\":\"parent\",\"password\":\"$PANEL_PW\"}")
  echo "Login nach Sperre: $code (erwartet 200)"
  cp "$CONFIG.famtest.bak" "$CONFIG" && sudo rm -f "$CONFIG.famtest.bak"
  sudo systemctl restart familypc-panel 2>&1 || true
  sleep 2
  echo "Config wiederhergestellt."
  echo
  echo "--- Cookies nach Login ---"
  grep familypc "$CJ" || true
  echo
  echo "--- mit Session ---"
  curl -sk -b "$CJ" -o /dev/null -w 'GET /api/status mit Session: %{http_code} (erwartet 200)\n' "$BASE/api/status"
  curl -sk -b "$CJ" "$BASE/api/whoami"; echo
  echo
  echo "--- FAM-12: CSRF-Schutz ---"
  CSRF=$(awk '/familypc_csrf/{print $NF}' "$CJ")
  curl -sk -b "$CJ" -o /dev/null -w 'PUT ohne X-CSRF-Token: %{http_code} (erwartet 403)\n' -X PUT "$BASE/api/accounts/kind1" -H 'Content-Type: application/json' -d '{"daily_budget_minutes":30}'
  curl -sk -b "$CJ" -o /dev/null -w 'PUT mit X-CSRF-Token: %{http_code} (erwartet 200)\n' -X PUT "$BASE/api/accounts/kind1" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"daily_budget_minutes":30}'
  echo
  echo "--- FAM-10 im Panel: Status + Config-Aenderung ohne Daemon-Neustart ---"
  curl -sk -b "$CJ" "$BASE/api/status" | python3 -m json.tool | head -25
  sudo journalctl -u familypc -n 10 --no-pager | grep -i 'Config neu geladen' || echo "(noch kein Reload)"
  echo
  echo "--- Logout ---"
  curl -sk -b "$CJ" -X POST "$BASE/api/logout" -o /dev/null -w 'logout: %{http_code}\n'
  curl -sk -b "$CJ" -o /dev/null -w 'GET /api/status nach Logout: %{http_code} (erwartet 401)\n' "$BASE/api/status"
  echo
  echo "--- FAM-13: HTTP->HTTPS Redirect + Avahi ---"
  curl -s -o /dev/null -w 'http://127.0.0.1:8786/ -> %{http_code} Location=%{redirect_url}\n' http://127.0.0.1:8786/
  sudo systemctl status avahi-daemon --no-pager | head -4 || true
  avahi-resolve -n familypc.local 2>/dev/null || getent hosts familypc.local || echo "familypc.local loest nicht auf (libnss-mdns installiert?)"
  curl -sk -o /dev/null -w 'https://familypc.local:8787/api/status: %{http_code} (erwartet 401 = erreichbar)\n' https://familypc.local:8787/api/status
  echo
  echo "--- Zertifikat ---"
  sudo openssl x509 -in /etc/familypc/panel.crt -noout -subject -ext subjectAltName 2>/dev/null || true
  echo
  echo "--- Panel-Accounts ---"
  sudo /opt/familypc/venv/bin/familypc-panel-admin --config "$CONFIG" list || true
  echo
  echo "===== Ende FAM-12/13 VM-Test ====="
} > "$OUT" 2>&1
rm -f "$CJ"

echo "Report: $OUT ($(wc -l < "$OUT") Zeilen)"

case "$MODE" in
  upload)
    if resp=$(curl -s --max-time 30 -F "files[]=@$OUT" https://uguu.se/upload.php 2>/dev/null); then
      url=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['files'][0]['url'])" 2>/dev/null || true)
      if [[ -n "$url" ]]; then echo "URL: $url"; echo "-> URL hier im Chat posten."; exit 0; fi
    fi
    if command -v nc >/dev/null 2>&1; then
      url=$(nc -w 15 termbin.com 9999 < "$OUT" 2>/dev/null | tr -d '\0[:space:]')
      if [[ "$url" == https://* ]]; then echo "URL: $url"; exit 0; fi
    fi
    echo "Upload fehlgeschlagen — siehe $OUT lokal oder --jira <TICKET>." >&2
    exit 1
    ;;
  jira)
    "$(dirname "${BASH_SOURCE[0]}")/jira_attach.sh" "$JIRA_TICKET" "$OUT"
    echo "-> Anhang am Ticket $JIRA_TICKET."
    ;;
esac
