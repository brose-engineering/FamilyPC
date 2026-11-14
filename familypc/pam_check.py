"""PAM-Hook (pam_exec): entscheidet, ob ein Login erlaubt ist.

Aufruf durch pam_exec mit PAM_USER in der Umgebung. Fragt den Daemon über
/run/familypc/control.sock. Fail-open: bei JEDEM Fehler exit 0 (Login erlauben)
— der Daemon-Ausfall darf niemanden aussperren.
"""

from __future__ import annotations

import os
import socket
import sys

from .control import DEFAULT_SOCKET_PATH


def ask_daemon(user: str, socket_path: str | None = None, timeout: float = 2.0) -> tuple[bool, str]:
    socket_path = socket_path or DEFAULT_SOCKET_PATH
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(socket_path)
            s.sendall(f"{user}\n".encode())
            answer = s.makefile("r").readline().strip()
        if answer.startswith("ALLOW"):
            return True, "ok"
        return False, answer.removeprefix("DENY ").strip() or "verweigert"
    except OSError:
        return True, "daemon nicht erreichbar (fail-open)"


def main() -> int:
    user = os.environ.get("PAM_USER", "").strip()
    if not user:
        return 0  # ohne User keine Meinung -> erlauben
    allowed, reason = ask_daemon(user)
    if allowed:
        return 0
    print(f"FamilyPC: Login für {user} verweigert ({reason})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
