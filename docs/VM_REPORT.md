# VM_REPORT.md — Test-Output teilen, ohne gemeinsame Zwischenablage (FAM-3)

Wenn die gemeinsame Zwischenablage zwischen VM und Host nicht funktioniert,
reicht es, **eine kurze URL** von der VM abzuleseen und hier im Chat zu posten.

## Variante 1 (empfohlen): Report hochladen

In der VM (im Admin-/parent-Konto, das hat Internet):

```bash
cd ~/FamilyPC
scripts/vm_report.sh --upload
```

Das Skript sammelt `systemctl status`, `journalctl -u familypc` (200 Zeilen),
Config-Check, Config-Inhalt, nftables-Tabelle, aktive Sessions und DB-Status
in eine Datei und lädt sie zu `https://0x0.st` hoch. Ausgabe endet mit:

```
URL: https://0x0.st/xxxx.txt
```

Diese URL hier posten — ich hole mir den Inhalt direkt.

## Variante 2: Shared Clipboard in VirtualBox reparieren

Meist fehlen die Guest Additions. In der VM:

```bash
sudo apt install -y virtualbox-guest-x11 virtualbox-guest-utils
sudo reboot
```

Danach in VirtualBox: Gerät → Gemeinsame Zwischenablage → **Bidirektional**.

## Variante 3: SSH + Port-Forward + Host-Clipboard

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

## Variante 4: Jira

Report-Datei direkt am jeweiligen FAM-Ticket als Anhang hochladen
(im VM-Browser auf brose-eng.atlassian.net einloggen, Ticket öffnen, Anhang).
