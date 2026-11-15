"""Unit-Tests für FAM-9 (Internet-Tagesbudget) mit simulierter Uhr."""

from datetime import date, datetime, timedelta

from familypc.config import AccountConfig, EnforcementConfig
from familypc.enforce import Enforcer
from familypc.internet import InternetBlocker
from familypc.nft import Nftables
from familypc.tracker import SessionTracker
from familypc.usage import UsageStore

UIDS = {"kind1": 1002, "kind2": 1003, "parent": 1001}


class FakeClock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += timedelta(seconds=s)


class FakeLogind:
    def __init__(self, users):
        self.users = set(users)

    def trackable_users(self, **kw):
        return set(self.users)


class FakeNft:
    def __init__(self):
        self.calls = []

    def __call__(self, args, stdin_text=None):
        self.calls.append((args, stdin_text))
        return ""


def test_internet_zaehlt_nur_bei_aktiver_session_und_nur_fuer_budget_konten(tmp_path):
    clock = FakeClock(datetime(2026, 11, 15, 10, 0, 0))
    logind = FakeLogind({"kind1", "kind2"})
    store = UsageStore(tmp_path / "usage.db")
    tracker = SessionTracker(
        __import__("familypc.config", fromlist=["TrackingConfig"]).TrackingConfig(),
        store, logind, now_fn=clock, internet_users={"kind1"},
    )
    day = date(2026, 11, 15)
    tracker.tick()
    clock.advance(120)
    tracker.tick()
    assert store.get_internet("kind1", day) == 120.0
    assert store.get_internet("kind2", day) == 0.0  # kein Internet-Budget konfiguriert
    logind.users = set()  # abmelden
    clock.advance(120)
    tracker.tick()  # letzter Stand -> noch 120s
    clock.advance(120)
    tracker.tick()  # jetzt nicht mehr aktiv -> kein Zuwachs
    assert store.get_internet("kind1", day) == 240.0
    assert store.get("kind1", day) == 240.0  # PC-Zeit: gleiche aktiven Sessions (hier gleichauf)
    store.close()


def test_internet_budget_aufgebraucht_sperrt_und_meldet(tmp_path):
    clock = FakeClock(datetime(2026, 11, 15, 10, 0, 0))
    accounts = {"kind1": AccountConfig(internet_daily_budget_minutes=2)}  # 120 s
    cfg = EnforcementConfig()
    store = UsageStore(tmp_path / "usage.db")
    day = date(2026, 11, 15)
    store.add_internet("kind1", day, 130)  # aufgebraucht
    notes, terms = [], []
    enforcer = Enforcer(
        cfg, accounts, store, now_fn=clock,
        notify_fn=lambda u, s, b: notes.append((u, s)),
        terminate_fn=lambda u: terms.append(u),
        uid_fn=lambda u: UIDS.get(u),
    )
    enforcer.tick(active_users={"kind1"})
    assert enforcer.last_internet_blocked == {1002}
    assert any("Internet" in s for _, s in notes)
    assert terms == []  # PC-Session laeuft weiter!
    store.close()


def test_internet_budget_neuer_tag_wieder_frei(tmp_path):
    clock = FakeClock(datetime(2026, 11, 15, 23, 59, 0))
    accounts = {"kind1": AccountConfig(internet_daily_budget_minutes=1)}
    store = UsageStore(tmp_path / "usage.db")
    store.add_internet("kind1", date(2026, 11, 15), 999)
    enforcer = Enforcer(EnforcementConfig(), accounts, store, now_fn=clock, uid_fn=lambda u: UIDS.get(u))
    enforcer.tick(active_users=set())
    assert enforcer.last_internet_blocked == {1002}
    clock.advance(120)  # neuer Tag
    enforcer.tick(active_users=set())
    assert enforcer.last_internet_blocked == set()
    store.close()


def test_internet_enabled_false_hat_vorrang_und_ist_dauerhaft(tmp_path):
    accounts = {
        "kind1": AccountConfig(internet_enabled=False, internet_daily_budget_minutes=60),
        "kind2": AccountConfig(internet_daily_budget_minutes=1),
    }
    fake = FakeNft()
    blocker = InternetBlocker(Nftables(runner=fake), accounts, protected_users={"parent"}, uid_fn=lambda u: UIDS.get(u))
    blocker.sync(extra_blocked={1003})  # kind2 Budget aufgebraucht
    ruleset = fake.calls[0][1]
    assert "meta skuid 1002 drop" in ruleset  # internet_enabled false
    assert "meta skuid 1003 drop" in ruleset  # Budget aufgebraucht
    # naechster Tag: Budget wieder frei, aber internet_enabled:false bleibt
    blocker.sync(extra_blocked=set())
    ruleset = fake.calls[1][1]
    assert "meta skuid 1002 drop" in ruleset
    assert "meta skuid 1003" not in ruleset
