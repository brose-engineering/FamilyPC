#!/usr/bin/env bash
# FamilyPC uninstall.sh — entfernt den Daemon vollstaendig (root erforderlich).
# Entfernt: systemd-Unit, /opt/familypc, /var/lib/familypc (Nutzungsdaten!),
#           /etc/familypc (Config). Idempotent: mehrfaches Ausfuehren ist schadlos.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Fehler: bitte als root ausfuehren, z. B. sudo $0" >&2
  exit 1
fi

echo "==> Service stoppen und deaktivieren ..."
systemctl disable --now familypc.service 2>/dev/null || true
systemctl reset-failed familypc.service 2>/dev/null || true

echo "==> Dateien entfernen ..."
rm -f /etc/systemd/system/familypc.service
systemctl daemon-reload
rm -rf /opt/familypc
rm -rf /var/lib/familypc   # inkl. SQLite-Nutzungsdaten
rm -rf /etc/familypc      # inkl. config.yaml

echo "FamilyPC wurde vollstaendig entfernt (Unit, /opt/familypc, /var/lib/familypc, /etc/familypc)."
