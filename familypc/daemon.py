"""Daemon-Hauptschleife: Heartbeat-Logging ins journald, sauberes Herunterfahren.

Unter systemd landen stdout/stderr automatisch im journald; das logging-Setup
schreibt deshalb auf stderr. Clock und Wait sind injizierbar, damit Unit-Tests
mit simulierter Uhr laufen (keine echten Sleeps).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .config import Config, ConfigError, load_config
from .state import RuntimeState

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
        internet=None,
        config_path: Path | None = None,
        state: RuntimeState | None = None,
    ) -> None:
        self.config = config
        self._clock = clock
        self._stop_event = threading.Event()
        self._wait = wait if wait is not None else self._stop_event.wait
        self.tracker = tracker
        self.enforcer = enforcer
        self.control = control
        self.internet = internet
        # FAM-10: Config-Datei auf Aenderungen pruefen (Admin-UI schreibt sie) und automatisch nachladen
        self.config_path = Path(config_path) if config_path is not None else None
        self.state = state
        self._config_mtime: float | None = None
        self._tracking_on = tracker is not None
        self._enforcement_on = enforcer is not None
        if self.config_path is not None:
            try:
                self._config_mtime = self.config_path.stat().st_mtime
            except OSError:
                self._config_mtime = None

    def request_stop(self, signum=None, _frame=None) -> None:
        """Signal-Handler: Daemon fährt kontrolliert herunter."""
        log.info("Signal %s empfangen, fahre herunter ...", signum)
        self._stop_event.set()

    def _maybe_reload_config(self) -> None:
        """FAM-10: Config-Datei bei mtime-Aenderung neu laden und an Komponenten durchreichen.

        Ungueltige Datei: alte Config bleibt aktiv (kein Absturz, kein Restart-Loop), Warnung ins Journal.
        """
        if self.config_path is None:
            return
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            return
        if self._config_mtime is not None and mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        try:
            new = load_config(self.config_path)
        except ConfigError as exc:
            log.warning("Config-Reload fehlgeschlagen, behalte alte Config: %s", exc)
            return
        log.info("Config neu geladen: %s", self.config_path)
        self.config = new
        if self.state is not None:
            self.state.set_config(new)
        # Komponenten fortschreiben (Control-Server haelt die Enforcer-Referenz -> sieht Aenderung sofort)
        if new.tracking is not None and new.tracking.enabled:
            if self.tracker is not None:
                internet_users = {u for u, a in new.accounts.items() if a.internet_daily_budget_minutes}
                self.tracker.update(new.tracking, internet_users)
                self._tracking_on = True
            else:
                log.warning("tracking-Sektion neu aktiviert — bitte Daemon neu starten (kein Runtime-Enable)")
        else:
            self._tracking_on = False
        if new.enforcement is not None and new.enforcement.enabled:
            if self.enforcer is not None:
                self.enforcer.update(new.enforcement, new.accounts)
                self._enforcement_on = True
            else:
                log.warning("enforcement-Sektion neu aktiviert — bitte Daemon neu starten (kein Runtime-Enable)")
        else:
            self._enforcement_on = False
        if self.internet is not None:
            protected = set(new.enforcement.protected_users) if new.enforcement else {"parent"}
            self.internet.update(new.accounts, protected)

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
                self._maybe_reload_config()
                now = self._clock()
                heartbeat = self.config.daemon.heartbeat_interval_seconds
                if now >= next_heartbeat:
                    log.info("Heartbeat: FamilyPC %s aktiv, Uptime %.0f s", __version__, now - started)
                    next_heartbeat = now + heartbeat
                if self._tracking_on and self.tracker is not None:
                    self.tracker.tick()
                    if self._enforcement_on and self.enforcer is not None:
                        self.enforcer.tick(active_users=self.tracker.last_active_users)
                if self.internet is not None:
                    extra = self.enforcer.last_internet_blocked if self._enforcement_on and self.enforcer is not None else set()
                    self.internet.sync(extra_blocked=extra)
                # In kleinen Schritten warten, damit Stopps sofort reagieren.
                self._wait(timeout=min(1.0, max(0.0, next_heartbeat - self._clock())))
        finally:
            if self.control is not None:
                self.control.stop()
            if self.internet is not None:
                self.internet.clear()  # fail-open: Sperren weg beim Stop

        log.info("Daemon gestoppt (Uptime %.0f s)", self._clock() - started)
        return 0
