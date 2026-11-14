"""Unit-Tests für die logind-Abstraktion (FAM-4) mit Fake-Runner."""

from familypc.sessions import Logind

LIST_HEADER = "SESSION  UID USER SEAT TTY\n"


def make_logind(sessions):
    """sessions: Liste von Dicts mit session_id/uid/user/type/state/remote/tty."""
    list_out = LIST_HEADER + "".join(
        f"{s['session_id']}  {s['uid']} {s['user']} {s.get('seat', 'seat0')} {s.get('tty', 'tty2')}\n"
        for s in sessions
    )
    show_outs = {
        s["session_id"]: (
            f"Type={s['type']}\nState={s['state']}\nRemote={'yes' if s['remote'] else 'no'}\nTTY={s.get('tty', 'tty2')}\n"
        )
        for s in sessions
    }

    def runner(cmd):
        if cmd[1] == "list-sessions":
            return list_out
        if cmd[1] == "show-session":
            return show_outs[cmd[2]]
        raise AssertionError(f"unerwarteter Befehl: {cmd}")

    return Logind(runner=runner)


def graphical(user, state="active", remote=False, sid="2", uid=1000):
    return {"session_id": sid, "uid": uid, "user": user, "type": "x11", "state": state, "remote": remote, "tty": "tty2"}


def ssh(user, sid="3", uid=1001):
    return {"session_id": sid, "uid": uid, "user": user, "type": "tty", "state": "active", "remote": True, "tty": "pts/0"}


def test_grafische_session_zaehlt():
    logind = make_logind([graphical("kind1")])
    users = logind.trackable_users(excluded_users={"root"}, count_remote=False, count_inactive=True)
    assert users == {"kind1"}


def test_ssh_session_zaehlt_nicht_default():
    logind = make_logind([ssh("kind1")])
    users = logind.trackable_users(excluded_users={"root"}, count_remote=False, count_inactive=True)
    assert users == set()
    users = logind.trackable_users(excluded_users={"root"}, count_remote=True, count_inactive=True)
    assert users == {"kind1"}


def test_fast_user_switching_zaehlt_weiter_default():
    # weggeswitchte Session hat state=online
    logind = make_logind([graphical("kind1", state="online")])
    assert logind.trackable_users(excluded_users={"root"}, count_remote=False, count_inactive=True) == {"kind1"}
    assert logind.trackable_users(excluded_users={"root"}, count_remote=False, count_inactive=False) == set()


def test_excluded_users_und_closing_state():
    logind = make_logind([graphical("root", sid="9", uid=0), graphical("kind1", state="closing", sid="4")])
    assert logind.trackable_users(excluded_users={"root"}, count_remote=False, count_inactive=True) == set()


def test_nicht_interaktive_types_zaehlen_nicht():
    s = graphical("kind1")
    s["type"] = "web"
    logind = make_logind([s])
    assert logind.trackable_users(excluded_users=set(), count_remote=False, count_inactive=True) == set()


def test_list_sessions_parsing_mit_footer():
    logind = make_logind([graphical("kind1")])
    # Footer-Zeile darf nicht crashen
    sessions = logind.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].user == "kind1"
    assert sessions[0].type == "x11"
    assert sessions[0].remote is False
