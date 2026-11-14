"""Session-Erkennung ueber systemd-logind (loginctl).

Der Runner ist injizierbar, damit Unit-Tests ohne echte logind-Sessions laufen.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger("familypc.sessions")

# Interaktive Session-Typen; reine SSH-Sessions sind type=tty + remote=yes.
INTERACTIVE_TYPES = {"x11", "wayland", "tty"}
# States, die nie als "aktiv" zaehlen.
NON_COUNTING_STATES = {"opening", "closing"}


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    uid: int
    user: str
    type: str
    state: str
    remote: bool
    tty: str


def _default_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} fehlgeschlagen (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


class Logind:
    def __init__(self, runner=None) -> None:
        self._run = runner or _default_runner

    def list_sessions(self) -> list[SessionInfo]:
        out = self._run(["loginctl", "list-sessions", "--no-ledger", "--no-pager"])
        sessions: list[SessionInfo] = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4 or parts[0] == "SESSION":
                continue
            try:
                uid = int(parts[1])
            except ValueError:
                continue  # z. B. Footer "1 sessions listed."
            props = self._show_session(parts[0])
            sessions.append(
                SessionInfo(
                    session_id=parts[0],
                    uid=uid,
                    user=parts[2],
                    type=props.get("Type", ""),
                    state=props.get("State", ""),
                    remote=props.get("Remote", "no") == "yes",
                    tty=props.get("TTY", ""),
                )
            )
        return sessions

    def _show_session(self, session_id: str) -> dict[str, str]:
        out = self._run(
            [
                "loginctl", "show-session", session_id,
                "-p", "Type", "-p", "State", "-p", "Remote", "-p", "TTY",
                "--no-pager",
            ]
        )
        props: dict[str, str] = {}
        for line in out.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                props[key] = value
        return props

    def trackable_users(
        self,
        *,
        excluded_users: set[str],
        count_remote: bool,
        count_inactive: bool,
    ) -> set[str]:
        """Nutzer mit mindestens einer zaehlbaren interaktiven Session."""
        users: set[str] = set()
        for s in self.list_sessions():
            if s.user in excluded_users:
                continue
            if s.type not in INTERACTIVE_TYPES:
                continue
            if s.type == "tty" and s.remote and not count_remote:
                continue  # reine SSH-Session
            if s.state in NON_COUNTING_STATES:
                continue
            if s.state != "active" and not count_inactive:
                continue  # z. B. Fast-User-Switching (state=online)
            users.add(s.user)
        return users
