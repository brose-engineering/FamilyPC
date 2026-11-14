"""Unit-Tests für Notification/Logout (FAM-7/8): Kommando-Shapes mit Fake-Runner."""

from familypc.notify import send_notification, terminate_user


def test_notify_kommando_enthält_session_bus_und_text():
    cmds = []
    ok = send_notification("kind1", "Titel", "Body", uid=1002, runner=lambda c: cmds.append(c) or "")
    assert ok is True
    cmd = cmds[0]
    assert cmd[:2] == ["runuser", "-u"]
    assert "kind1" in cmd
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus" in cmd
    assert "org.freedesktop.Notifications" in cmd and "Notify" in cmd
    assert "susssasa{sv}i" in cmd  # Signatur: s app_name, u id, s icon, s summary, s body, as actions, a{sv} hints, i timeout
    assert "Titel" in cmd and "Body" in cmd


def test_notify_fehler_wird_gemeldet_nicht_geworfen():
    def boom(cmd):
        raise RuntimeError("bus kaputt")

    assert send_notification("kind1", "t", "b", uid=1002, runner=boom) is False


def test_terminate_user_loginctl():
    cmds = []
    assert terminate_user("kind1", runner=lambda c: cmds.append(c) or "") is True
    assert cmds[0] == ["loginctl", "terminate-user", "kind1"]
