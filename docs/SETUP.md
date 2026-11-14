# SETUP.md — Test-VM aufsetzen (FAM-3)

Ziel: ein Snapshot, aus dem in **unter 10 Minuten** eine einsatzbereite Test-VM
wird (Repo + Testkonten + installierter Daemon nach `install.sh`).

Getestet mit: Linux Mint 22.x Cinnamon (64 Bit), VirtualBox **oder** KVM.

## 1. VM anlegen

**VirtualBox:** Neu → Typ Linux, Version „Linux Mint 22 (Cinnamon)", ISO von
linuxmint.com einbinden. Eckdaten: 2 CPUs, 4096 MB RAM, 25 GB VDI (dynamisch),
Netzwerk **NAT** (damit die Internet-Sperr-Tests greifen), optional
bidirektionale Zwischenablage.

**KVM (virt-manager):** gleiche Eckdaten, Netzwerk „default" (NAT), Display Spice.

## 2. Mint installieren

Normales Desktop-Setup. Der bei der Installation angelegte Benutzer bleibt
bestehen (hat sudo). zusätzlich legen wir die Testkonten an (Schritt 4).

## 3. Basis-Software in der VM

```bash
sudo apt update
sudo apt install -y git openssh-server sqlite3 curl
```

## 4. Repo klonen & Testkonten anlegen

```bash
cd ~
git clone git@github.com:brose-engineering/FamilyPC.git     # SSH-Key bei GitHub hinterlegt
# alternativ HTTPS: git clone https://github.com/brose-engineering/FamilyPC.git

sudo ~/FamilyPC/scripts/create_test_users.sh
```

Testkonten danach (Passwort jeweils `familypc`):

| Konto | sudo | Zweck |
|---|---|---|
| `parent` | ja | Admin-/Eltern-Konto (darf nie ausgesperrt werden) |
| `kind1` | nein | Kinder-Konto für Budget-/Fenster-/Internet-Tests |
| `kind2` | nein | zweites Kinder-Konto (Fast-User-Switching, Vergleich) |

## 5. Snapshot „familypc-basis" anlegen

VM herunterfahren, Snapshot speichern (VirtualBox: Maschine → Snapshots → Take;
KVM: virt-manager → Snapshots). Ab jetzt: Snapshot wiederherstellen = einsatzbereit.

## 6. FamilyPC installieren & FAM-2-Test

```bash
cd ~/FamilyPC
sudo scripts/install.sh
systemctl status familypc
```

Manuelle Checkliste für FAM-2: `docs/FAM-2_VM_TEST.md`.
Alle Feature-Checklisten: `docs/MANUELLE_TESTS.md`.
