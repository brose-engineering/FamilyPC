"""Desktop-Notification in die Nutzer-Session (D-Bus org.freedesktop.Notifications).

Läuft als root: wir springen per runuser in die Session des Users und rufen
busctl --user auf dessen Session-Bus auf. Runner injizierbar für Tests.
"""

from __future__ import annotations

import logging
import pwd
import subprocess

log = logging.getLogger("familypc.notify")


def _default_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def user_uid(user: str) -> int:
    return pwd.getpwnam(user).pw_uid


def send_notification(
    user: str,
    summary: str,
    body: str,
    *,
    uid: int | None = None,
    timeout_ms: int = 15000,
    runner=None,
) -> bool:
    """Schickt eine Notification an den Desktop des Users. False bei Fehler (nie crashen)."""
    run = runner or _default_runner
    if uid is None:
        try:
            uid = user_uid(user)
        except KeyError:
            log.warning("notify: unbekannter User %r", user)
            return False
    cmd = [
        "runuser", "-u", user, "--",
        "env", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        "busctl", "--user", "call",
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications", "Notify",
        "susssasa{sv}i",
        "FamilyPC", "0", "", summary, body, "[]", "{}", str(timeout_ms),
    ]
    try:
        run(cmd)
        return True
    except Exception as exc:
        log.warning("notify an %s fehlgeschlagen: %s", user, exc)
        return False


def terminate_user(user: str, *, runner=None) -> bool:
    """Logout per loginctl terminate-user. False bei Fehler."""
    run = runner or _default_runner
    try:
        run(["loginctl", "terminate-user", user])
        log.info("User %s per loginctl terminate-user abgemeldet", user)
        return True
    except Exception as exc:
        log.error("terminate-user %s fehlgeschlagen: %s", user, exc)
        return False
