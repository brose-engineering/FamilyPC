"""Geteilter Runtime-State (FAM-10): Daemon und Admin-UI lesen hier die aktuelle Config.

Der Daemon ersetzt bei Config-Reload (mtime-Wechsel) das Config-Objekt atomar;
UI-Tasks und Control-Server lesen es lock-geschützt. Komponenten (Tracker,
Enforcer) werden vom Daemon per update() fortgeschrieben, daher genuegt hier
nur das Config-Objekt.
"""

from __future__ import annotations

import threading

from .config import Config


class RuntimeState:
    def __init__(self, config: Config) -> None:
        self._lock = threading.Lock()
        self._config = config
        self.tracker = None  # SessionTracker | None
        self.enforcer = None  # Enforcer | None

    def get_config(self) -> Config:
        with self._lock:
            return self._config

    def set_config(self, config: Config) -> None:
        with self._lock:
            self._config = config
