#!/usr/bin/env bash
# FamilyPC vm_report.sh — sammelt Diagnose-Daten der Test-VM in eine Datei.
# Output teilen ohne gemeinsame Zwischenablage:
#   scripts/vm_report.sh --jira FAM-2    # Report als Anhang an das Jira-Ticket (empfohlen,
#                                        # braucht JIRA_EMAIL/JIRA_API_TOKEN in der Umgebung)
#   scripts/vm_report.sh --upload        # Report zu einem Paste-Dienst (uguu.se, Fallback termbin),
#                                        # URL wird ausgegeben und hier im Chat gepostet
#   scripts/vm_report.sh                # nur lokale Datei unter /tmp
set -uo pipefail

OUT="/tmp/familypc-report-$(date +%Y%m%d-%H%M%S).txt"
MODE="local"
JIRA_TICKET=""
case "${1:-}" in
  --upload) MODE="upload" ;;
  --jira)   MODE="jira"; JIRA_TICKET="${2:-}"; [[ -n "$JIRA_TICKET" ]] || { echo "Usage: $0 --jira <TICKET-KEY>" >&2; exit 1; } ;;
  "")       MODE="local" ;;
  *)        echo "Usage: $0 [--upload | --jira <TICKET-KEY>]" >&2; exit 1 ;;
esac

{
  echo "===== FamilyPC VM-Report $(date -Is) ====="
  echo "--- uname / OS ---"
  uname -a
  if [[ -r /etc/os-release ]]; then . /etc/os-release; echo "PRETTY_NAME=${PRETTY_NAME:-?}"; fi
  echo "--- systemctl status familypc ---"
  sudo systemctl status familypc --no-pager --full 2>&1 || true
  echo "--- journalctl -u familypc (letzte 200 Zeilen) ---"
  sudo journalctl -u familypc -n 200 --no-pager 2>&1 || true
  echo "--- config check ---"
  /opt/familypc/venv/bin/python -m familypc --config /etc/familypc/config.yaml --check-config 2>&1 || true
  echo "--- /etc/familypc/config.yaml ---"
  sudo cat /etc/familypc/config.yaml 2>/dev/null || echo "(nicht vorhanden)"
  echo "--- nftables Tabelle familypc ---"
  sudo nft list table inet familypc 2>/dev/null || sudo nft list table ip familypc 2>/dev/null || echo "(keine Tabelle)"
  echo "--- loginctl sessions ---"
  loginctl list-sessions --no-pager 2>&1 || true
  echo "--- usage db ---"
  sudo sqlite3 /var/lib/familypc/usage.db '.tables' 2>/dev/null || echo "(noch keine DB)"
  echo "===== Ende Report ====="
} > "$OUT" 2>&1

echo "Report: $OUT ($(wc -l < "$OUT") Zeilen)"

upload_paste() {
  # 1) uguu.se (multipart, JSON-Antwort mit URL)
  local resp url
  if resp=$(curl -s --max-time 30 -F "files[]=@$OUT" https://uguu.se/upload.php 2>/dev/null); then
    url=$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['files'][0]['url'])" 2>/dev/null || true)
    if [[ -n "$url" ]]; then echo "$url"; return 0; fi
  fi
  # 2) termbin.com via netcat
  if command -v nc >/dev/null 2>&1; then
    url=$(nc -w 15 termbin.com 9999 < "$OUT" 2>/dev/null | tr -d '\0[:space:]')
    if [[ "$url" == https://* ]]; then echo "$url"; return 0; fi
  fi
  return 1
}

case "$MODE" in
  upload)
    if url=$(upload_paste); then
      echo "URL: $url"
      echo "-> URL hier im Chat posten, ich lese den Report direkt aus."
    else
      echo "Paste-Upload fehlgeschlagen (uguu.se + termbin)." >&2
      echo "Alternative: --jira <TICKET> (Anhang am Jira-Ticket) oder siehe docs/VM_REPORT.md" >&2
      exit 1
    fi
    ;;
  jira)
    "$(dirname "${BASH_SOURCE[0]}")/jira_attach.sh" "$JIRA_TICKET" "$OUT"
    echo "-> Anhang am Ticket $JIRA_TICKET in Jira; ich lese ihn von dort."
    ;;
esac
