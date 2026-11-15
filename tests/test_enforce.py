"""Unit-Tests für die Policy-Engine (FAM-7 Budget + FAM-8 Fenster) mit simulierter Uhr."""

from datetime import date, datetime, timedelta

from familypc.config import AccountConfig, EnforcementConfig
from familypc.enforce import Enforcer
from familypc.usage import UsageStore


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += timedelta(seconds=seconds)


def make_enforcer(tmp_path, clock, accounts, store_seconds=None, **cfg_overrides):
    cfg = EnforcementConfig(**cfg_overrides)
    store = UsageStore(tmp_path / "usage.db")
    day = store_day = (clock.now - timedelta(hours=cfg and 0)).date()
    if store_seconds:
        for user, secs in store_seconds.items():
            store.add(user, day, secs)
    notifications = []
    terminations = []
    enforcer = Enforcer(
        cfg,
        accounts,
        store,
        now_fn=clock,
        notify_fn=lambda u, s, b: notifications.append((u, s, b)),
        terminate_fn=lambda u: terminations.append(u),
    )
    return enforcer, store, notifications, terminations


def acct(**kwargs):
    return AccountConfig(**kwargs)


# ---------- FAM-7: Tagesbudget ----------

def test_warnung_bei_10_und_5_minuten(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))  # Montag
    accounts = {"kind1": acct(daily_budget_minutes=60)}
    # 50 Minuten verbraucht -> 10 Minuten Rest
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 50 * 60})
    enforcer.tick(active_users={"kind1"})
    assert any("noch 10 Minuten" in s for _, s, _ in notes)
    assert terms == []

    clock.advance(5 * 60 + 1)  # -> noch ~5 Minuten
    enforcer.tick(active_users={"kind1"})
    # store hat noch 3000s; wir simulieren Verbrauch über store:
    # (hier: Uhr weiter, aber Verbrauch kommt aus store — wir erhöhen ihn direkt)
    store.add("kind1", (clock.now).date(), 5 * 60)
    enforcer.tick(active_users={"kind1"})
    assert any("noch 5 Minuten" in s for _, s, _ in notes)
    assert terms == []


def test_logout_bei_budget_0_und_kein_doppel_logout(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    accounts = {"kind1": acct(daily_budget_minutes=30)}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 30 * 60})
    enforcer.tick(active_users={"kind1"})
    assert terms == ["kind1"]
    assert any("aufgebraucht" in s for _, s, _ in notes)
    enforcer.tick(active_users={"kind1"})  # nochmal -> kein doppelter Logout
    assert terms == ["kind1"]


def test_relogin_nach_budget_erneut_abgemeldet(tmp_path):
    """FAM-10: Budget per UI erhoeht -> frischer Login (may_login ALLOW) re-armt Logout."""
    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    accounts = {"kind1": acct(daily_budget_minutes=30)}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 30 * 60})
    enforcer.tick(active_users={"kind1"})
    assert terms == ["kind1"]  # erster Logout
    # Eltern setzen Budget per UI hoch -> Config-Reload -> may_login erlaubt wieder
    enforcer.accounts["kind1"].daily_budget_minutes = 60
    ok, _ = enforcer.may_login("kind1", clock.now)
    assert ok is True  # budget_logout-Alert wurde gecleared
    store.add("kind1", clock.now.date(), 31 * 60)  # neues Budget ueberschritten
    enforcer.tick(active_users={"kind1"})
    assert terms == ["kind1", "kind1"]  # erneut abgemeldet


def test_internet_sperre_gilt_auch_bei_aufgebrauchtem_pc_budget(tmp_path):
    """FAM-9/FAM-10: Internet-Block darf nicht wegen PC-Budget-continue fehlen."""
    from familypc.enforce import Enforcer as _E

    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    cfg = EnforcementConfig()
    store = UsageStore(tmp_path / "usage.db")
    day = clock.now.date()
    store.add("kind1", day, 10 * 60)  # PC-Budget 10 min aufgebraucht
    store.add_internet("kind1", day, 5 * 60)  # Internet-Budget 5 min aufgebraucht
    enforcer = _E(cfg, {"kind1": acct(daily_budget_minutes=10, internet_daily_budget_minutes=5)},
                  store, now_fn=clock, notify_fn=lambda *a: None, terminate_fn=lambda u: None,
                  uid_fn=lambda u: 1002)
    enforcer.tick(active_users={"kind1"})
    assert 1002 in enforcer.last_internet_blocked


def test_relogin_nach_budget_verweigert_may_login(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    accounts = {"kind1": acct(daily_budget_minutes=30)}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 30 * 60})
    ok, reason = enforcer.may_login("kind1", clock.now)
    assert ok is False and "Tagesbudget" in reason
    ok, _ = enforcer.may_login("parent", clock.now)
    assert ok is True  # protected
    ok, _ = enforcer.may_login("yannic", clock.now)
    assert ok is True  # nicht konfiguriert


def test_budget_0_bedeutet_unbegrenzt(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 15, 0, 0))
    accounts = {"kind1": acct(daily_budget_minutes=0)}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 999999})
    enforcer.tick(active_users={"kind1"})
    assert terms == [] and notes == []
    assert enforcer.may_login("kind1", clock.now)[0] is True


def test_neuer_tag_reset_durch_neuen_day(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 23, 59, 0))
    accounts = {"kind1": acct(daily_budget_minutes=30)}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts, store_seconds={"kind1": 30 * 60})
    assert enforcer.may_login("kind1", clock.now)[0] is False
    clock.advance(120)  # -> nächster Tag 00:01
    assert enforcer.may_login("kind1", clock.now)[0] is True
    enforcer.tick(active_users={"kind1"})
    assert terms == []


# ---------- FAM-8: Nutzungsfenster ----------

def _mo_window(start="15:00", end="19:00"):
    return {0: [{"start": start, "end": end}]}


def test_login_ausserhalb_fenster_verweigert(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 14, 0, 0))  # Montag 14:00, Fenster 15-19
    accounts = {"kind1": acct(windows=_mo_window())}
    enforcer, *_ = make_enforcer(tmp_path, clock, accounts)
    ok, reason = enforcer.may_login("kind1", clock.now)
    assert ok is False and "Nutzungsfenster" in reason
    clock.now = datetime(2026, 11, 16, 15, 30, 0)
    assert enforcer.may_login("kind1", clock.now)[0] is True


def test_fensterende_vorwarnung_dann_logout(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 18, 55, 0))  # Mo, 5 min vor Ende 19:00
    accounts = {"kind1": acct(windows=_mo_window())}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts)
    enforcer.tick(active_users={"kind1"})  # 18:55 -> innerhalb Vorwarnung (10 min)
    assert any("endet bald" in s for _, s, _ in notes)
    assert terms == []

    clock.now = datetime(2026, 11, 16, 19, 1, 0)  # nach Fensterende
    enforcer.tick(active_users={"kind1"})
    assert terms == ["kind1"]
    assert any("beendet" in s for _, s, _ in notes)
    # nochmal -> kein doppelter Logout
    enforcer.tick(active_users={"kind1"})
    assert terms == ["kind1"]


def test_kein_logout_ausserhalb_fenster_wenn_nicht_angemeldet(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 20, 0, 0))  # Mo 20:00, ausserhalb
    accounts = {"kind1": acct(windows=_mo_window())}
    enforcer, store, notes, terms = make_enforcer(tmp_path, clock, accounts)
    enforcer.tick(active_users=set())  # niemand angemeldet
    assert terms == [] and notes == []


def test_mehrere_fenster_pro_tag(tmp_path):
    clock = FakeClock(datetime(2026, 11, 16, 12, 0, 0))  # Mo 12:00, Fenster 15-16 und 17-19
    accounts = {"kind1": acct(windows={0: [{"start": "15:00", "end": "16:00"}, {"start": "17:00", "end": "19:00"}]})}
    enforcer, *_ = make_enforcer(tmp_path, clock, accounts)
    assert enforcer.may_login("kind1", clock.now)[0] is False  # 12:00 ausserhalb
    clock.now = datetime(2026, 11, 16, 15, 30, 0)
    assert enforcer.may_login("kind1", clock.now)[0] is True
    clock.now = datetime(2026, 11, 16, 16, 30, 0)
    assert enforcer.may_login("kind1", clock.now)[0] is False  # zwischen den Fenstern


def test_anderer_wochentag_anderes_fenster(tmp_path):
    # Dienstag (weekday=1) hat kein Fenster -> verweigert
    clock = FakeClock(datetime(2026, 11, 17, 15, 30, 0))  # Di
    accounts = {"kind1": acct(windows=_mo_window())}
    enforcer, *_ = make_enforcer(tmp_path, clock, accounts)
    assert enforcer.may_login("kind1", clock.now)[0] is False
