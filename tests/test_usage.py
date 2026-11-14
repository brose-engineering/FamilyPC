"""Unit-Tests für den SQLite-Usage-Store (FAM-4)."""

from datetime import date, datetime

from familypc.usage import UsageStore, usage_day


def test_usage_day_default_mitternacht():
    assert usage_day(datetime(2026, 11, 14, 23, 59), 0) == date(2026, 11, 14)
    assert usage_day(datetime(2026, 11, 15, 0, 0), 0) == date(2026, 11, 15)
    assert usage_day(datetime(2026, 11, 15, 0, 30), 0) == date(2026, 11, 15)


def test_usage_day_mit_reset_hour():
    # reset um 04:00: 02:00 Uhr zaehlt noch zum Vortag
    assert usage_day(datetime(2026, 11, 15, 2, 0), 4) == date(2026, 11, 14)
    assert usage_day(datetime(2026, 11, 15, 4, 0), 4) == date(2026, 11, 15)


def test_add_get_akkumuliert(tmp_path):
    store = UsageStore(tmp_path / "usage.db")
    day = date(2026, 11, 14)
    assert store.get("kind1", day) == 0.0
    store.add("kind1", day, 60)
    store.add("kind1", day, 30)
    store.add("kind2", day, 10)
    assert store.get("kind1", day) == 90.0
    assert store.get_all(day) == {"kind1": 90.0, "kind2": 10.0}
    store.close()


def test_reboot_sicher_persistenz_ueber_reopen(tmp_path):
    db = tmp_path / "usage.db"
    day = date(2026, 11, 14)
    store = UsageStore(db)
    store.add("kind1", day, 600)
    store.close()
    # neuer Store auf derselben Datei (entspricht Daemon-Neustart/Reboot)
    store2 = UsageStore(db)
    assert store2.get("kind1", day) == 600.0
    store2.close()


def test_getrennte_tage(tmp_path):
    store = UsageStore(tmp_path / "usage.db")
    store.add("kind1", date(2026, 11, 14), 100)
    store.add("kind1", date(2026, 11, 15), 50)
    assert store.get("kind1", date(2026, 11, 14)) == 100.0
    assert store.get("kind1", date(2026, 11, 15)) == 50.0
    store.close()
