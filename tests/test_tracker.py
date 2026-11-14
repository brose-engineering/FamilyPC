"""Unit-Tests für den SessionTracker (FAM-4) mit simulierter Uhr und Fake-logind."""

from datetime import date, datetime, timedelta

from familypc.config import TrackingConfig
from familypc.sessions import Logind
from familypc.tracker import SessionTracker
from familypc.usage import UsageStore, usage_day


class FakeClock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += timedelta(seconds=seconds)


class FakeLogind:
    """Liefert pro Aufruf die aktuell gesetzten Sessions."""

    def __init__(self, sessions_by_user=None):
        self._sessions_by_user = sessions_by_user or {}
        self.calls = 0

    def set_users(self, users: set[str]):
        self._sessions_by_user = {u: True for u in users}

    def trackable_users(self, *, excluded_users, count_remote, count_inactive):
        self.calls += 1
        return {u for u in self._sessions_by_user if u not in excluded_users}


def make_tracker(tmp_path, clock, logind, **cfg_overrides):
    cfg = TrackingConfig(**cfg_overrides)
    store = UsageStore(tmp_path / "usage.db")
    return SessionTracker(cfg, store, logind, now_fn=clock), store


def test_10_minuten_session_werden_gespeichert(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind)
    day = usage_day(clock.now, 0)

    tracker.tick()  # init
    assert store.get("kind1", day) == 0.0

    for _ in range(60):  # 60 Ticks à 10 s = 10 Minuten
        clock.advance(10)
        tracker.tick()

    assert store.get("kind1", day) == 600.0
    store.close()


def test_session_ende_zaehlt_bis_einen_tick_nach_last_seen(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind)
    day = usage_day(clock.now, 0)

    tracker.tick()
    clock.advance(60)
    tracker.tick()          # kind1 aktiv -> +60
    logind.set_users(set())  # abgemeldet
    clock.advance(60)
    tracker.tick()          # noch letzter Stand -> +60 (Poll-Genauigkeit)
    clock.advance(60)
    tracker.tick()          # jetzt nicht mehr -> +0

    assert store.get("kind1", day) == 120.0
    store.close()


def test_zwei_konten_unabhaengig(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))
    logind = FakeLogind({"kind1", "kind2"})
    tracker, store = make_tracker(tmp_path, clock, logind)
    day = usage_day(clock.now, 0)

    tracker.tick()
    clock.advance(60)
    logind.set_users({"kind1"})  # kind2 abmelden
    tracker.tick()
    clock.advance(60)
    tracker.tick()

    assert store.get("kind1", day) == 120.0
    assert store.get("kind2", day) == 60.0  # nur bis einen Tick nach Abmeldung
    store.close()


def test_reset_um_mitternacht_split(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 23, 59, 50))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind, reset_hour=0)

    tracker.tick()
    clock.advance(20)  # 23:59:50 -> 00:00:10 (naechster Tag)
    tracker.tick()

    assert store.get("kind1", date(2026, 11, 14)) == 10.0  # bis 00:00
    assert store.get("kind1", date(2026, 11, 15)) == 10.0  # ab 00:00 (neuer Tag = Reset)
    store.close()


def test_reset_hour_konfigurierbar(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 23, 59, 50))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind, reset_hour=4)

    tracker.tick()
    clock.advance(20)  # 00:00:10, aber reset erst um 04:00 -> selbero Nutzungstag
    tracker.tick()

    assert store.get("kind1", date(2026, 11, 14)) == 20.0
    assert store.get("kind1", date(2026, 11, 15)) == 0.0
    store.close()


def test_poll_intervall_begrenzt_logind_aufrufe(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind, poll_interval_seconds=30)

    tracker.tick()  # init -> 1. Abfrage
    for _ in range(5):
        clock.advance(10)  # 50 s gesamt, Intervall 30 s
        tracker.tick()

    assert logind.calls <= 3  # nicht bei jedem Tick neu fragen
    assert store.get("kind1", usage_day(clock.now, 0)) == 50.0
    store.close()


def test_logind_fehler_behaelt_letzten_stand(tmp_path):
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))

    class BrokenLogind(FakeLogind):
        def trackable_users(self, **kwargs):
            raise RuntimeError("logind down")

    logind = BrokenLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind)
    day = usage_day(clock.now, 0)
    tracker.tick()  # init: Abfrage schlaegt fehl -> cached leer
    clock.advance(60)
    tracker.tick()  # weiter fehlschlagend -> kein Crash, kein Verbrauch
    assert store.get("kind1", day) == 0.0
    store.close()


def test_tracker_ueberlebt_reopen_der_db(tmp_path):
    # entspricht Reboot: neuer Store auf gleicher Datei, Verbrauch bleibt
    clock = FakeClock(datetime(2026, 11, 14, 15, 0, 0))
    logind = FakeLogind({"kind1"})
    tracker, store = make_tracker(tmp_path, clock, logind)
    day = usage_day(clock.now, 0)
    tracker.tick()
    clock.advance(120)
    tracker.tick()
    store.close()

    store2 = UsageStore(tmp_path / "usage.db")
    assert store2.get("kind1", day) == 120.0
    store2.close()
