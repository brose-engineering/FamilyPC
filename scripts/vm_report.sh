#!/usr/bin/env bash
# FamilyPC vm_report.sh — sammelt Diagnose-Daten der Test-VM in eine Datei.
# Ohne gemeinsame Zwischenablage: --upload laedt den Report zu 0x0.st hoch,
# die ausgegebene URL kann hier im Chat gepostet werden (Agent liest sie aus).
#
# Aufruf in der VM:
#   scripts/vm_report.sh              # schreibt /tmp/familypc-report-<ts>.txt
#   scripts/vm_report.sh --upload     # zusaetzlich Upload, gibt die URL aus
set -uo pipefail

OUT="/tmp/familypc-report-$(date +%Y%m%d-%H%M%S).txt"
UPLOAD=0
[[ "${1:-}" == "--upload" ]] && UPLOAD=1

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
if [[ $UPLOAD -eq 1 ]]; then
  url=$(curl -s --max-time 30 -F "file=@$OUT" https://0x0.st)
  echo "URL: $url"
  echo "-> URL hier im Chat posten, ich lese den Report direkt aus."
fi
