"""Daemon-Hauptschleife: Heartbeat-Logging ins journald, sauberes Herunterfahren.

Unter systemd landen stdout/stderr automatisch im journald; das logging-Setup
schreibt deshalb auf stderr. Clock und Wait sind injizierbar, damit Unit-Tests
mit simulierter Uhr laufen (keine echten Sleeps).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from . import __version__
from .config import Config

log = logging.getLogger("familypc")


class Daemon:
    def __init__(
        self,
        config: Config,
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Optional[Callable[[float], bool]] = None,
        tracker=None,
        enforcer=None,
        control=None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._stop_event = threading.Event()
        self._wait = wait if wait is not None else self._stop_event.wait
        self.tracker = tracker
        self.enforcer = enforcer
        self.control = control

    def request_stop(self, signum=None, _frame=None) -> None:
        """Signal-Handler: Daemon fährt kontrolliert herunter."""
        log.info("Signal %s empfangen, fahre herunter ...", signum)
        self._stop_event.set()

    def run(self) -> int:
        cfg = self.config.daemon
        log.info(
            "FamilyPC %s startet (state_dir=%s, heartbeat=%ss, log_level=%s)",
            __version__,
            cfg.state_dir,
            cfg.heartbeat_interval_seconds,
            cfg.log_level,
        )
        cfg.state_dir.mkdir(parents=True, exist_ok=True)

        if self.control is not None:
            self.control.start()
        started = self._clock()
        next_heartbeat = started + cfg.heartbeat_interval_seconds
        try:
            while not self._stop_event.is_set():
                now = self._clock()
                if now >= next_heartbeat:
                    log.info("Heartbeat: FamilyPC %s aktiv, Uptime %.0f s", __version__, now - started)
                    next_heartbeat = now + cfg.heartbeat_interval_seconds
                if self.tracker is not None:
                    self.tracker.tick()
                    if self.enforcer is not None:
                        self.enforcer.tick(active_users=self.tracker.last_active_users)
                # In kleinen Schritten warten, damit Stopps sofort reagieren.
                self._wait(timeout=min(1.0, max(0.0, next_heartbeat - self._clock())))
        finally:
            if self.control is not None:
                self.control.stop()

        log.info("Daemon gestoppt (Uptime %.0f s)", self._clock() - started)
        return 0
