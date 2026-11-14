"""Desktop-Notification in die Nutzer-Session (D-Bus org.freedesktop.Notifications).

Läuft als root: wir springen per runuser in die Session des Users und rufen dort
einen Notification-Client auf dessen Session-Bus auf. Backend-Kette:
gdbus (robustes GVariant-Parsing) -> notify-send -> busctl (Fallback).
Runner injizierbar für Tests.
"""

from __future__ import annotations

import logging
import pwd
import shutil
import subprocess

log = logging.getLogger("familypc.notify")


def _default_runner(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def user_uid(user: str) -> int:
    return pwd.getpwnam(user).pw_uid


def _gvariant_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _prefix(user: str, uid: int) -> list[str]:
    return [
        "runuser", "-u", user, "--",
        "env", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
    ]


def _cmd_gdbus(user, uid, summary, body, timeout_ms):
    return _prefix(user, uid) + [
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.Notifications",
        "--object-path", "/org/freedesktop/Notifications",
        "--method", "org.freedesktop.Notifications.Notify",
        _gvariant_str("FamilyPC"), "0", _gvariant_str(""),
        _gvariant_str(summary), _gvariant_str(body),
        "@as []", "@a{sv} {}", str(timeout_ms),
    ]


def _cmd_notify_send(user, uid, summary, body, timeout_ms):
    return _prefix(user, uid) + [
        "notify-send", "-a", "FamilyPC", "-t", str(timeout_ms), summary, body,
    ]


def _cmd_busctl(user, uid, summary, body, timeout_ms):
    # busctl kann leere Arrays nicht parsen ('[]' -> Invalid argument), daher nur Fallback
    return _prefix(user, uid) + [
        "busctl", "--user", "call",
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications", "Notify",
        "susssasa{sv}i",
        "FamilyPC", "0", "", summary, body, "[]", "{}", str(timeout_ms),
    ]


_BACKENDS = (
    ("gdbus", _cmd_gdbus),
    ("notify-send", _cmd_notify_send),
    ("busctl", _cmd_busctl),
)


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
    for tool, builder in _BACKENDS:
        if shutil.which(tool) is None:
            continue
        cmd = builder(user, uid, summary, body, timeout_ms)
        try:
            run(cmd)
            return True
        except Exception as exc:
            log.warning("notify an %s via %s fehlgeschlagen: %s", user, tool, exc)
    log.error("notify an %s: kein Backend (gdbus/notify-send/busctl) funktioniert", user)
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
