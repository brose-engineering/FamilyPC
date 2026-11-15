"""Setup-CLI fuer Panel-Accounts (FAM-12): Initial-Account anlegen, Passwort-Reset.

Nur als root auf der Konsole (schreibt /var/lib/familypc/panel.db, root-only).
Passwoerter werden per getpass eingegeben (nie im Klartext in Logs/History).

    familypc-panel-admin --config /etc/familypc/config.yaml add <name>
    familypc-panel-admin --config /etc/familypc/config.yaml passwd <name>
    familypc-panel-admin --config /etc/familypc/config.yaml del <name>
    familypc-panel-admin --config /etc/familypc/config.yaml list
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .panel import PanelAuth


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="familypc-panel-admin", description="FamilyPC Panel-Accounts verwalten (root-only)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_add = sub.add_parser("add")
    p_add.add_argument("username")
    p_passwd = sub.add_parser("passwd")
    p_passwd.add_argument("username")
    p_del = sub.add_parser("del")
    p_del.add_argument("username")
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        print("Fehler: nur als root auf der Konsole ausfuehren (sudo familypc-panel-admin ...)", file=sys.stderr)
        return 1
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"Config-Fehler: {exc}", file=sys.stderr)
        return 2

    auth = PanelAuth(config.daemon.state_dir / "panel.db")
    try:
        if args.cmd == "list":
            users = auth.list_users()
            print("Panel-Accounts: " + (", ".join(users) if users else "(keine — 'add <name>' anlegen)"))
        elif args.cmd == "add":
            pw1 = getpass.getpass(f"Passwort fuer {args.username}: ")
            pw2 = getpass.getpass("Passwort wiederholen: ")
            if pw1 != pw2:
                print("Passwoerter stimmen nicht ueberein.", file=sys.stderr)
                return 1
            auth.add_user(args.username, pw1)
            print(f"Panel-Account {args.username!r} angelegt.")
        elif args.cmd == "passwd":
            if args.username not in auth.list_users():
                print(f"Unbekannter Panel-Account {args.username!r} (siehe 'list').", file=sys.stderr)
                return 1
            pw1 = getpass.getpass(f"Neues Passwort fuer {args.username}: ")
            pw2 = getpass.getpass("Neues Passwort wiederholen: ")
            if pw1 != pw2:
                print("Passwoerter stimmen nicht ueberein.", file=sys.stderr)
                return 1
            auth.add_user(args.username, pw1)  # upsert = Reset
            print(f"Passwort fuer {args.username!r} geaendert.")
        elif args.cmd == "del":
            if auth.remove_user(args.username):
                print(f"Panel-Account {args.username!r} entfernt.")
            else:
                print(f"Unbekannter Panel-Account {args.username!r}.", file=sys.stderr)
                return 1
    finally:
        auth.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
