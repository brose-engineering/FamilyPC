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

echo "==> Systempakete (python3-venv, python3-pip, nftables, avahi-daemon, openssl) ..."
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nftables avahi-daemon openssl

echo "==> Projekt nach $PREFIX kopieren ..."
mkdir -p "$PREFIX"
rm -rf "$PREFIX/familypc" "$PREFIX/pyproject.toml" "$PREFIX/ui_static"
cp -r "$SRC_DIR/familypc" "$SRC_DIR/pyproject.toml" "$PREFIX/"
# FAM-10: gebautes React-Frontend (ui/dist -> familypc/ui_static im Repo) nach $PREFIX/ui_static
if [[ -d "$SRC_DIR/familypc/ui_static" ]]; then
  cp -r "$SRC_DIR/familypc/ui_static" "$PREFIX/ui_static"
fi

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

echo "==> PAM-Hook eintragen (Login-Verweigerung, fail-open) ..."
PAM_FILE=/etc/pam.d/common-auth
PAM_LINE='auth required pam_exec.so quiet seteuid /opt/familypc/venv/bin/familypc-pam-check # familypc-pam-check'
if grep -q 'familypc-pam-check' "$PAM_FILE" 2>/dev/null; then
  echo "    PAM-Zeile bereits vorhanden."
else
  # vor die erste auth-Zeile einfügen
  tmp=$(mktemp)
  awk -v line="$PAM_LINE" 'BEGIN{done=0} /^auth[ \t]/ && !done {print line; done=1} {print}' "$PAM_FILE" > "$tmp"
  cat "$tmp" > "$PAM_FILE" && rm -f "$tmp"
  echo "    PAM-Zeile in $PAM_FILE eingetragen."
fi
# Hook muss ohne PAM_USER fehlerfrei exit 0 liefern (fail-open), sonst Lockout-Risiko
"$VENV/bin/familypc-pam-check" </dev/null || true

echo "==> Admin-Panel (FAM-12/13): TLS-Zertifikat, Avahi (familypc.local), Panel-Unit ..."
# Selbstsigniertes Zertifikat nur erzeugen, wenn nicht vorhanden (sonst bleiben Browser-Warnungen stabil)
if [[ ! -f /etc/familypc/panel.crt || ! -f /etc/familypc/panel.key ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout /etc/familypc/panel.key -out /etc/familypc/panel.crt \
    -subj "/CN=familypc.local" -addext "subjectAltName=DNS:familypc.local,DNS:localhost,IP:127.0.0.1" 2>/dev/null
  chmod 0600 /etc/familypc/panel.key
  echo "    Selbstsigniertes Zertifikat erzeugt: /etc/familypc/panel.crt (Browser-Warnung beim ersten Aufruf normal)"
fi
# Avahi/mDNS: Panel als familypc.local bekannt geben
mkdir -p /etc/avahi/services
cat > /etc/avahi/services/familypc.service <<'XML'
<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">FamilyPC Admin-Panel auf %h</name>
  <service>
    <type>_https._tcp</type>
    <port>8787</port>
  </service>
</service-group>
XML
systemctl enable --now avahi-daemon.service 2>/dev/null || true

PANEL_UNIT_SRC="$SRC_DIR/systemd/familypc-panel.service"
PANEL_UNIT_DST=/etc/systemd/system/familypc-panel.service

echo "==> systemd-Units installieren und Services starten ..."
install -m 0644 "$UNIT_SRC" "$UNIT_DST"
install -m 0644 "$PANEL_UNIT_SRC" "$PANEL_UNIT_DST"
systemctl daemon-reload
systemctl enable familypc.service familypc-panel.service
systemctl restart familypc.service
systemctl restart familypc-panel.service
echo "    Panel: https://familypc.local:8787 (oder https://<IP>:8787) — Initial-Account: sudo familypc-panel-admin --config $CONFIG_FILE add <name>"

echo
systemctl --no-pager --full status familypc.service || true
echo
echo "Installation fertig."
echo "  Status:  systemctl status familypc"
echo "  Logs:    journalctl -u familypc -f   (Heartbeat-Zeilen inklusive)"
