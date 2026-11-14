"""Unit-Tests für Control-Socket (Unix) und PAM-Check (FAM-7/8 Login-Verweigerung)."""

import os
import socket
from datetime import datetime

from familypc.control import ControlServer
from familypc.enforce import Enforcer
from familypc.config import AccountConfig, EnforcementConfig
from familypc.pam_check import ask_daemon, main as pam_main
from familypc.usage import UsageStore


class StubEnforcer:
    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def may_login(self, user, now):
        self.seen.append(user)
        return self.answers.get(user, (True, "ok"))


def test_control_socket_roundtrip(tmp_path):
    sock = str(tmp_path / "control.sock")
    enforcer = StubEnforcer({"kind1": (False, "ausserhalb des Nutzungsfensters"), "parent": (True, "ok")})
    server = ControlServer(enforcer, socket_path=sock, now_fn=lambda: datetime(2026, 11, 16, 14, 0))
    server.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock)
            s.sendall(b"kind1\n")
            assert s.makefile("r").readline().strip() == "DENY ausserhalb des Nutzungsfensters"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock)
            s.sendall(b"parent\n")
            assert s.makefile("r").readline().strip() == "ALLOW"
        assert enforcer.seen == ["kind1", "parent"]
    finally:
        server.stop()
    assert not os.path.exists(sock)


def test_pam_check_fail_open_ohne_daemon(tmp_path):
    ok, reason = ask_daemon("kind1", socket_path=str(tmp_path / "gibt-es-nicht.sock"))
    assert ok is True and "fail-open" in reason
    # main() ohne PAM_USER -> exit 0
    os.environ.pop("PAM_USER", None)
    assert pam_main() == 0


def test_control_server_fail_open_bei_enforcer_fehler(tmp_path):
    class BrokenEnforcer:
        def may_login(self, user, now):
            raise RuntimeError("sqlite thread bug")

    sock = str(tmp_path / "control.sock")
    server = ControlServer(BrokenEnforcer(), socket_path=sock, now_fn=lambda: datetime(2026, 11, 16, 14, 0))
    server.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(sock)
            s.sendall(b"kind1\n")
            assert s.makefile("r").readline().strip() == "ALLOW fail-open"
    finally:
        server.stop()


def test_usage_store_thread_safe(tmp_path):
    import threading
    from familypc.usage import UsageStore
    from datetime import date

    store = UsageStore(tmp_path / "usage.db")
    day = date(2026, 11, 16)

    def writer():
        for _ in range(50):
            store.add("kind1", day, 1.0)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert store.get("kind1", day) == 200.0
    store.close()


def test_pam_check_deny_bei_daemon(tmp_path, monkeypatch):
    import familypc.pam_check as pam_mod

    sock = str(tmp_path / "control.sock")
    enforcer = StubEnforcer({"kind1": (False, "Tagesbudget aufgebraucht")})
    server = ControlServer(enforcer, socket_path=sock, now_fn=lambda: datetime(2026, 11, 16, 20, 0))
    server.start()
    monkeypatch.setattr(pam_mod, "DEFAULT_SOCKET_PATH", sock)
    try:
        ok, reason = ask_daemon("kind1", socket_path=sock)
        assert ok is False and "Tagesbudget" in reason
        os.environ["PAM_USER"] = "kind1"
        assert pam_main() == 1
        os.environ["PAM_USER"] = "parent"
        assert pam_main() == 0
    finally:
        server.stop()
        os.environ.pop("PAM_USER", None)


def test_enforcer_may_login_integriert_mit_store(tmp_path):
    from tests.test_enforce import FakeClock, make_enforcer, acct

    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    accounts = {"kind1": acct(daily_budget_minutes=60, windows={0: [{"start": "15:00", "end": "19:00"}]})}
    enforcer, store, _, _ = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 3600})
    ok, reason = enforcer.may_login("kind1", clock.now)
    assert ok is False and "Tagesbudget" in reason
