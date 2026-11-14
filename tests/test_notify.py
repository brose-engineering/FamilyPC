"""Unit-Tests für Notification/Logout (FAM-7/8): Backend-Kette mit Fake-Runner."""

import shutil

from familypc import notify
from familypc.notify import send_notification, terminate_user


def test_notify_nutzt_gdbus_mit_korrekten_gvariant_args(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool == "gdbus" else None)
    cmds = []
    ok = send_notification("kind1", 'Titel "X"', "Body", uid=1002, runner=lambda c: cmds.append(c) or "")
    assert ok is True
    cmd = cmds[0]
    assert cmd[:2] == ["runuser", "-u"] and "kind1" in cmd
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus" in cmd
    assert "gdbus" in cmd and "org.freedesktop.Notifications.Notify" in cmd
    assert '"Titel \\"X\\""' in cmd  # GVariant-escaped
    assert "@as []" in cmd and "@a{sv} {}" in cmd


def test_notify_fallback_auf_notify_send(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool == "notify-send" else None)
    cmds = []
    ok = send_notification("kind1", "Titel", "Body", uid=1002, runner=lambda c: cmds.append(c) or "")
    assert ok is True
    cmd = cmds[0]
    assert "notify-send" in cmd and "Titel" in cmd and "Body" in cmd


def test_notify_fallback_kette_springt_ueber_kaputtes_backend(monkeypatch):
    # gdbus "installiert" aber kaputt, notify-send geht
    monkeypatch.setattr(shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool in ("gdbus", "notify-send") else None)
    cmds = []

    def runner(cmd):
        cmds.append(cmd)
        if "gdbus" in cmd:
            raise RuntimeError("gdbus kaputt")
        return ""

    ok = send_notification("kind1", "T", "B", uid=1002, runner=runner)
    assert ok is True
    assert any("notify-send" in c for c in cmds)


def test_notify_kein_backend_verfuegbar(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda tool: None)
    assert send_notification("kind1", "t", "b", uid=1002, runner=lambda c: "") is False


def test_notify_unbekannter_user():
    assert send_notification("gibtsnicht", "t", "b", runner=lambda c: "") is False


def test_terminate_user_loginctl():
    cmds = []
    assert terminate_user("kind1", runner=lambda c: cmds.append(c) or "") is True
    assert cmds[0] == ["loginctl", "terminate-user", "kind1"]
