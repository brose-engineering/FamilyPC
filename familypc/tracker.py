"""Session-Tracking (FAM-4): zaehlt aktive Nutzungszeit pro Konto und persistiert sie.

Genauigkeit: Poll-Intervall (Default 10 s). Eine Session, die zwischen zwei Ticks
endet, wird noch bis zum einen Tick nach dem letzten Sichtbarsein gezaehlt.
Die Uhr (now_fn) ist injizierbar — Unit-Tests laufen mit simulierter Uhr.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from .config import TrackingConfig
from .sessions import Logind
from .usage import UsageStore, usage_day

log = logging.getLogger("familypc.tracker")


class SessionTracker:
    def __init__(
        self,
        config: TrackingConfig,
        store: UsageStore,
        logind: Logind,
        now_fn=datetime.now,
        internet_users: set[str] | None = None,
    ) -> None:
        self.cfg = config
        self.store = store
        self.logind = logind
        self._now = now_fn
        # FAM-9: Internet-Verbrauch nur fuer diese Konten mitzaehlen (nur bei aktiver Session)
        self._internet_users = internet_users or set()
        self._last_tick: datetime | None = None
        self._active_users: set[str] = set()
        self._last_query: datetime | None = None
        self._cached_users: set[str] = set()

    @property
    def last_active_users(self) -> set[str]:
        return self._active_users

    def update(self, config: TrackingConfig, internet_users: set[str] | None = None) -> None:
        """FAM-10: Config-Reload ohne Neustart — Daemon ruft das pro Tick nach Datei-Aenderung auf."""
        self.cfg = config
        if internet_users is not None:
            self._internet_users = internet_users

    def tick(self) -> None:
        now = self._now()
        if self._last_tick is None:
            self._last_tick = now
            self._active_users = self._query_users(now)
            log.info(
                "Session-Tracking aktiv (poll=%ss, reset=%02d:00, remote=%s, inaktiv=%s, excluded=%s)",
                self.cfg.poll_interval_seconds,
                self.cfg.reset_hour,
                self.cfg.count_remote_sessions,
                self.cfg.count_inactive_sessions,
                ",".join(self.cfg.excluded_users) or "-",
            )
            return

        elapsed = (now - self._last_tick).total_seconds()
        current = self._query_users(now)
        if elapsed > 0:
            # Session, die mitten im Intervall endet, zaehlt bis einen Tick danach.
            charge = current | self._active_users
            day_now = usage_day(now, self.cfg.reset_hour)
            day_last = usage_day(self._last_tick, self.cfg.reset_hour)
            if day_now == day_last:
                for user in charge:
                    self.store.add(user, day_now, elapsed)
                    if user in self._internet_users:
                        self.store.add_internet(user, day_now, elapsed)
            else:
                # Intervall ueber die Reset-Grenze splitten
                boundary = datetime.combine(day_now, time.min) + timedelta(hours=self.cfg.reset_hour)
                for user in charge:
                    self.store.add(user, day_last, (boundary - self._last_tick).total_seconds())
                    self.store.add(user, day_now, (now - boundary).total_seconds())
                    if user in self._internet_users:
                        self.store.add_internet(user, day_last, (boundary - self._last_tick).total_seconds())
                        self.store.add_internet(user, day_now, (now - boundary).total_seconds())
            if charge:
                log.debug("tick %s: +%.0fs fuer %s", now.isoformat(), elapsed, sorted(charge))
        self._active_users = current
        self._last_tick = now

    def _query_users(self, now: datetime) -> set[str]:
        if (
            self._last_query is not None
            and (now - self._last_query).total_seconds() < self.cfg.poll_interval_seconds
        ):
            return self._cached_users
        try:
            users = self.logind.trackable_users(
                excluded_users=set(self.cfg.excluded_users),
                count_remote=self.cfg.count_remote_sessions,
                count_inactive=self.cfg.count_inactive_sessions,
            )
        except Exception as exc:
            # auch bei Fehler Intervall setzen, sonst Warn-Spam im Sekundentakt
            self._last_query = now
            log.warning("logind-Abfrage fehlgeschlagen, letzter Stand bleibt: %s", exc)
            return self._cached_users
        self._cached_users = users
        self._last_query = now
        return users
