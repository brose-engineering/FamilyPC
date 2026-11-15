"""Persistenz des Zeitverbrauchs in SQLite (reboot-sicher).

Ein Nutzungstag laeuft von reset_hour bis reset_hour (Default 00:00-00:00).
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    day     TEXT NOT NULL,
    user    TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user)
);
CREATE TABLE IF NOT EXISTS alerts (
    day  TEXT NOT NULL,
    user TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (day, user, kind)
);
CREATE TABLE IF NOT EXISTS internet_usage (
    day     TEXT NOT NULL,
    user    TEXT NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (day, user)
);
"""


def usage_day(now: datetime, reset_hour: int = 0) -> date:
    """Nutzungstag von `now`: alles vor reset_hour zaehlt noch zum Vortag."""
    return (now - timedelta(hours=reset_hour)).date()


class UsageStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + Lock: Daemon-Thread (Tracker/Enforcer) und
        # Control-Server-Thread (PAM-Checks) teilen sich den Store.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def add(self, user: str, day: date, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO usage(day, user, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(day, user) DO UPDATE SET seconds = seconds + excluded.seconds",
                (day.isoformat(), user, seconds),
            )

    def get(self, user: str, day: date) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT seconds FROM usage WHERE day = ? AND user = ?",
                (day.isoformat(), user),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def get_all(self, day: date) -> dict[str, float]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT user, seconds FROM usage WHERE day = ?", (day.isoformat(),)
            ).fetchall()
        return {user: float(seconds) for user, seconds in rows}

    def add_internet(self, user: str, day: date, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO internet_usage(day, user, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(day, user) DO UPDATE SET seconds = seconds + excluded.seconds",
                (day.isoformat(), user, seconds),
            )

    def get_internet(self, user: str, day: date) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT seconds FROM internet_usage WHERE day = ? AND user = ?",
                (day.isoformat(), user),
            ).fetchone()
        return float(row[0]) if row else 0.0

    def has_alert(self, user: str, day: date, kind: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM alerts WHERE day = ? AND user = ? AND kind = ?",
                (day.isoformat(), user, kind),
            ).fetchone()
        return row is not None

    def add_alert(self, user: str, day: date, kind: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO alerts(day, user, kind) VALUES (?, ?, ?)",
                (day.isoformat(), user, kind),
            )

    def close(self) -> None:
        self._conn.close()
