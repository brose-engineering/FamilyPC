# VM_REPORT.md — Test-Output teilen, ohne gemeinsame Zwischenablage (FAM-3)

Wenn die gemeinsame Zwischenablage zwischen VM und Host nicht funktioniert,
laufen Reports über `scripts/vm_report.sh` — entweder als **Jira-Anhang**
(empfohlen, bleibt in unserer Infrastruktur) oder als Paste-URL.

## Variante 1 (empfohlen): Report als Jira-Anhang

Einmalig in der VM den eigenen Jira-API-Token hinterlegen
(Token anlegen: https://id.atlassian.com/manage-profile/security/api-tokens):

```bash
echo 'export JIRA_EMAIL="dein.name@brose-engineering.de"' >> ~/.bashrc
echo 'export JIRA_API_TOKEN="<dein-token>"' >> ~/.bashrc
source ~/.bashrc
```

Nach dem Testlauf in der VM (aus einem Konto mit Internet, z. B. `parent`):

```bash
cd ~/FamilyPC
scripts/vm_report.sh --jira FAM-2
```

Der Report landet als Anhang am Ticket FAM-2 — ich lese ihn direkt von dort.
Das Skript sammelt: `systemctl status`, `journalctl -u familypc` (200 Zeilen),
Config-Check + Config, nftables-Tabelle, aktive Sessions, DB-Status.

## Variante 2: Paste-URL

```bash
scripts/vm_report.sh --upload
```

Probiert nacheinander `uguu.se` und `termbin.com` (netcat) und gibt eine URL
aus (`https://d.uguu.se/...` bzw. `https://termbin.com/...`). URL ablesen und
hier im Chat posten — ich hole den Inhalt direkt. Hinweis: 0x0.st und ix.io
nehmen derzeit keine Uploads mehr an.

Einzelbefehle gehen auch direkt:

```bash
sudo journalctl -u familypc -n 200 --no-pager | nc termbin.com 9999     # -> URL
curl -s -F "files[]=@/tmp/report.txt" https://uguu.se/upload.php        # -> JSON mit URL
```

## Variante 3: Shared Clipboard in VirtualBox reparieren

Meist fehlen die Guest Additions. In der VM:

```bash
sudo apt install -y virtualbox-guest-x11 virtualbox-guest-utils
sudo reboot
```

Danach in VirtualBox: Gerät → Gemeinsame Zwischenablage → **Bidirektional**.

## Variante 4: SSH + Port-Forward + Host-Clipboard

```bash
# Host: NAT-Portforward einrichten
VBoxManage modifyvm "familypc-test" --natpf1 "ssh,tcp,,2222,,22"
# VM: sshd sicherstellen
sudo apt install -y openssh-server
# Host: Output direkt in die Host-Zwischenablage
sudo apt install -y xclip
ssh -p 2222 yannic@127.0.0.1 'sudo journalctl -u familypc -n 200 --no-pager' | xclip -selection clipboard
```

Danach normal mit Strg+V hier einfügen.
