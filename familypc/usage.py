"""Persistenz des Zeitverbrauchs in SQLite (reboot-sicher).

Ein Nutzungstag laeuft von reset_hour bis reset_hour (Default 00:00-00:00).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
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
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def add(self, user: str, day: date, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._conn:
            self._conn.execute(
                "INSERT INTO usage(day, user, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(day, user) DO UPDATE SET seconds = seconds + excluded.seconds",
                (day.isoformat(), user, seconds),
            )

    def get(self, user: str, day: date) -> float:
        row = self._conn.execute(
            "SELECT seconds FROM usage WHERE day = ? AND user = ?",
            (day.isoformat(), user),
        ).fetchone()
        return float(row[0]) if row else 0.0

    def get_all(self, day: date) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT user, seconds FROM usage WHERE day = ?", (day.isoformat(),)
        ).fetchall()
        return {user: float(seconds) for user, seconds in rows}

    def close(self) -> None:
        self._conn.close()
