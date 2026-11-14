#!/usr/bin/env bash
# FamilyPC install.sh — installiert den Daemon auf Linux Mint (idempotent, root erforderlich).
# Legt an: /opt/familypc (Code + venv), /etc/familypc/config.yaml (nur wenn fehlt),
#          /var/lib/familypc (State), systemd-Unit. Aktiviert und startet den Service.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX=/opt/familypc
VENV="$PREFIX/venv"
CONFIG_DIR=/etc/familypc
CONFIG_FILE="$CONFIG_DIR/config.yaml"
STATE_DIR=/var/lib/familypc
UNIT_SRC="$SRC_DIR/systemd/familypc.service"
UNIT_DST=/etc/systemd/system/familypc.service

if [[ $EUID -ne 0 ]]; then
  echo "Fehler: bitte als root ausfuehren, z. B. sudo $0" >&2
  exit 1
fi

echo "==> Systempakete (python3-venv, python3-pip) ..."
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

echo "==> Projekt nach $PREFIX kopieren ..."
mkdir -p "$PREFIX"
rm -rf "$PREFIX/familypc" "$PREFIX/pyproject.toml"
cp -r "$SRC_DIR/familypc" "$SRC_DIR/pyproject.toml" "$PREFIX/"

echo "==> venv erstellen und Paket installieren ..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet "$PREFIX"

echo "==> Config installieren (bestehende Config bleibt erhalten) ..."
mkdir -p "$CONFIG_DIR"
if [[ ! -f "$CONFIG_FILE" ]]; then
  install -m 0640 -o root -g root "$SRC_DIR/config/config.yaml" "$CONFIG_FILE"
else
  echo "    $CONFIG_FILE existiert bereits, wird nicht ueberschrieben."
  # Upgrade-Hinweis: Top-Level-Sektionen der Beispiel-Config, die in der bestehenden fehlen
  missing=$(comm -23 \
    <(grep -oE '^[a-z_]+:' "$SRC_DIR/config/config.yaml" | sort -u) \
    <(grep -oE '^[a-z_]+:' "$CONFIG_FILE" | sort -u) | tr -d ':' | tr '\n' ' ' || true)
  if [[ -n "${missing// /}" ]]; then
    echo "    Hinweis: bestehende Config kennt folgende Sektion(en) noch nicht: $missing"
    echo "            Vorlage siehe $SRC_DIR/config/config.yaml (z. B. 'tracking' ab FAM-4)."
  fi
fi
mkdir -p "$STATE_DIR"
chmod 0750 "$STATE_DIR"

echo "==> Config validieren ..."
"$VENV/bin/python" -m familypc --config "$CONFIG_FILE" --check-config

echo "==> systemd-Unit installieren und Service starten ..."
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable familypc.service
systemctl restart familypc.service

echo
systemctl --no-pager --full status familypc.service || true
echo
echo "Installation fertig."
echo "  Status:  systemctl status familypc"
echo "  Logs:    journalctl -u familypc -f   (Heartbeat-Zeilen inklusive)"
