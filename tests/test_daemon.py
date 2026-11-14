"""Unit-Tests für den Daemon-Sockel (FAM-2): Heartbeat mit simulierter Uhr.

Keine echten Sleeps: Clock und Wait werden injiziert, die Fake-Uhr springt
sofort weiter.
"""

import logging

from familypc.config import Config
from familypc.daemon import Daemon


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_daemon(tmp_path, interval=60, on_wait=None):
    config = Config.model_validate(
        {"daemon": {"heartbeat_interval_seconds": interval, "state_dir": str(tmp_path / "state")}}
    )
    clock = FakeClock()

    def wait(timeout):
        clock.advance(timeout)
        if on_wait is not None:
            on_wait(clock.now)
        return False

    daemon = Daemon(config, clock=clock.monotonic, wait=wait)
    return daemon, clock


def heartbeats(caplog):
    return [r for r in caplog.records if r.levelno == logging.INFO and "Heartbeat" in r.getMessage()]


def test_heartbeat_und_graceful_stop(tmp_path, caplog):
    interval = 60
    holder = {}

    def stop_after_three_beats(now):
        if now > 3 * interval:
            holder["daemon"].request_stop(signum=15)

    daemon, clock = make_daemon(tmp_path, interval=interval, on_wait=stop_after_three_beats)
    holder["daemon"] = daemon

    with caplog.at_level(logging.INFO, logger="familypc"):
        assert daemon.run() == 0

    beats = heartbeats(caplog)
    assert len(beats) == 3  # bei 60s, 120s, 180s
    assert clock.now >= 3 * interval
    assert (tmp_path / "state").is_dir()  # state_dir wurde angelegt
    assert any("gestoppt" in r.getMessage() for r in caplog.records)


def test_stop_vor_erstem_heartbeat(tmp_path, caplog):
    daemon, clock = make_daemon(tmp_path, interval=3600, on_wait=lambda now: daemon.request_stop())
    with caplog.at_level(logging.INFO, logger="familypc"):
        assert daemon.run() == 0
    assert heartbeats(caplog) == []
    assert any("startet" in r.getMessage() for r in caplog.records)
