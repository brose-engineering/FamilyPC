#!/usr/bin/env bash
# FamilyPC create_test_users.sh — legt die Testkonten aus FAM-3 an (idempotent, root).
#   parent      -> sudo-Gruppe (Admin-/Eltern-Konto)
#   kind1, kind2 -> ohne sudo (Kinder-Konten)
# Passwort für alle Testkonten: familypc  (nur Test-VM!)
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Fehler: bitte als root ausfuehren, z. B. sudo $0" >&2
  exit 1
fi

PASSWORD="familypc"

create_user() {
  local name="$1" with_sudo="$2"
  if id "$name" &>/dev/null; then
    echo "Konto '$name' existiert bereits."
  else
    useradd --create-home --shell /bin/bash "$name"
    echo "$name:$PASSWORD" | chpasswd
    echo "Konto '$name' angelegt (Passwort: $PASSWORD)."
  fi
  if [[ "$with_sudo" == "sudo" ]]; then
    usermod --append --groups sudo "$name"
  else
    # sicherstellen, dass Kinder-Konten nicht in sudo/adm landen
    gpasswd --delete "$name" sudo 2>/dev/null || true
    gpasswd --delete "$name" adm 2>/dev/null || true
  fi
}

create_user parent sudo
create_user kind1 no
create_user kind2 no

echo
echo "Testkonten:"
for u in parent kind1 kind2; do
  echo "  $u -> $(id "$u")"
done
