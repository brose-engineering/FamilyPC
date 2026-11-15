#!/usr/bin/env bash
# FamilyPC uninstall.sh — entfernt den Daemon vollstaendig (root erforderlich).
# Entfernt: systemd-Unit, /opt/familypc, /var/lib/familypc (Nutzungsdaten!),
#           /etc/familypc (Config). Idempotent: mehrfaches Ausfuehren ist schadlos.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Fehler: bitte als root ausfuehren, z. B. sudo $0" >&2
  exit 1
fi

echo "==> Services stoppen und deaktivieren ..."
systemctl disable --now familypc.service familypc-panel.service 2>/dev/null || true
systemctl reset-failed familypc.service familypc-panel.service 2>/dev/null || true

echo "==> PAM-Hook entfernen ..."
if [[ -f /etc/pam.d/common-auth ]]; then
  sed -i '/familypc-pam-check/d' /etc/pam.d/common-auth
fi

echo "==> nftables-Tabelle entfernen (fail-open) ..."
nft delete table inet familypc 2>/dev/null || true

echo "==> Dateien entfernen ..."
rm -f /etc/systemd/system/familypc.service /etc/systemd/system/familypc-panel.service
rm -f /etc/avahi/services/familypc.service
systemctl daemon-reload
rm -rf /opt/familypc
rm -rf /var/lib/familypc   # inkl. SQLite-Nutzungsdaten + panel.db
rm -rf /etc/familypc      # inkl. config.yaml, panel.crt/key
rm -rf /run/familypc      # Control-Socket

echo "FamilyPC wurde vollstaendig entfernt (Unit, /opt/familypc, /var/lib/familypc, /etc/familypc)."
