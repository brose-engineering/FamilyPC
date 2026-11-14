#!/usr/bin/env bash
# FamilyPC jira_attach.sh — hängt eine Datei an ein Jira-Ticket an (z. B. FAM-2).
# Damit kann Test-Output aus der VM direkt am Ticket landen (Agent liest ihn von dort).
#
# Credentials kommen aus der Umgebung und werden NIE im Repo committed:
#   export JIRA_EMAIL='dein.name@brose-engineering.de'
#   export JIRA_API_TOKEN='<Token von https://id.atlassian.com/manage-profile/security/api-tokens>'
# (einmalig in der VM in ~/.bashrc eintragen)
#
# Aufruf: scripts/jira_attach.sh FAM-2 /tmp/familypc-report-....txt
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <TICKET-KEY> <DATEI>" >&2
  exit 1
fi
ticket="$1"
file="$2"

: "${JIRA_EMAIL:?JIRA_EMAIL ist nicht gesetzt — siehe docs/VM_REPORT.md}"
: "${JIRA_API_TOKEN:?JIRA_API_TOKEN ist nicht gesetzt — siehe docs/VM_REPORT.md}"
if [[ ! -f "$file" ]]; then
  echo "Datei nicht gefunden: $file" >&2
  exit 1
fi

resp=$(mktemp)
code=$(curl -s -o "$resp" -w '%{http_code}' --max-time 60 \
  -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
  -H 'X-Atlassian-Token: no-check' \
  -F "file=@$file" \
  "https://brose-eng.atlassian.net/rest/api/3/issue/$ticket/attachments")
if [[ "$code" == "200" ]]; then
  echo "OK: '$file' hänge an $ticket an."
else
  echo "Fehler (HTTP $code):" >&2
  cat "$resp" >&2
  rm -f "$resp"
  exit 1
fi
rm -f "$resp"
