"""Laden und Validieren der FamilyPC-Konfiguration (/etc/familypc/config.yaml).

Konvention: Fehlende Felder bedeuten "Feature deaktiviert" — die Config
validiert trotzdem und der Daemon stürzt nicht ab.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("/etc/familypc/config.yaml")

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(Exception):
    """Config-Datei fehlt, ist kaputt oder verletzt das Schema."""


def _parse_hhmm(value: str, field_name: str) -> tuple[int, int]:
    match = _TIME_RE.match(value)
    if not match:
        raise ValueError(f"{field_name} muss HH:MM sein (00:00-23:59), got: {value!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    return hour, minute


class TimeWindow(BaseModel):
    """Erlaubtes Nutzungsfenster, z. B. 15:00-19:00 (FAM-8)."""

    model_config = ConfigDict(extra="forbid")

    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _check_time(cls, value: str, info) -> str:
        _parse_hhmm(value, info.field_name)
        return value

    @model_validator(mode="after")
    def _start_before_end(self) -> "TimeWindow":
        start = _parse_hhmm(self.start, "start")
        end = _parse_hhmm(self.end, "end")
        if start >= end:
            raise ValueError(f"Fenster-Start ({self.start}) muss vor Fenster-Ende ({self.end}) liegen")
        return self


# ISO-Wochentag: 0 = Montag ... 6 = Sonntag
Weekday = Annotated[int, Field(ge=0, le=6)]


class AccountConfig(BaseModel):
    """Pro-Konto-Regeln. Alle Felder optional; None/0 = unbegrenzt bzw. Feature aus."""

    model_config = ConfigDict(extra="forbid")

    daily_budget_minutes: Optional[int] = Field(default=None, ge=0)  # FAM-7; None/0 = unbegrenzt
    internet_enabled: Optional[bool] = None  # FAM-5; None = Feature deaktiviert
    internet_daily_budget_minutes: Optional[int] = Field(default=None, ge=0)  # FAM-9
    windows: dict[Weekday, list[TimeWindow]] = Field(default_factory=dict)  # FAM-8


class DaemonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    heartbeat_interval_seconds: int = Field(default=60, ge=1, le=3600)
    state_dir: Path = Path("/var/lib/familypc")  # SQLite-DB für Zeitverbrauch (ab FAM-4)


class TrackingConfig(BaseModel):
    """Session-Tracking (FAM-4). Sektion fehlt komplett = Tracking deaktiviert."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    poll_interval_seconds: int = Field(default=10, ge=1, le=300)  # logind-Abfrage-Intervall
    reset_hour: int = Field(default=0, ge=0, le=23)  # taeglicher Reset um reset_hour Uhr
    count_remote_sessions: bool = False  # reine SSH-Sessions zaehlen nicht (Default)
    count_inactive_sessions: bool = True  # Fast-User-Switching zaehlt weiter (Default)
    excluded_users: list[str] = Field(default_factory=lambda: ["root", "lightdm"])  # Admin-/Daemon-/System-User


class EnforcementConfig(BaseModel):
    """Durchsetzung (FAM-7 Budget + FAM-8 Fenster). Sektion fehlt = deaktiviert."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    warn_minutes: list[int] = Field(default_factory=lambda: [10, 5])  # FAM-7 Warnschwellen
    window_prewarning_minutes: int = Field(default=10, ge=0, le=120)  # FAM-8 Vorwarnung
    protected_users: list[str] = Field(default_factory=lambda: ["parent"])  # niemals sperren


class UiConfig(BaseModel):
    """Admin-Panel (FAM-10 localhost, FAM-13 LAN/HTTPS). Sektion fehlt = Panel deaktiviert.

    FAM-12: Zugriff nur mit Panel-Login (eigene Accounts, siehe panel.py) —
    'admin_groups' ist deprecated und wird ignoriert.
    FAM-13: host 0.0.0.0 = LAN, TLS selbstsigniert, http_port leitet auf HTTPS um.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    host: str = "127.0.0.1"  # FAM-13: 0.0.0.0 fuer Heimnetz
    port: int = Field(default=8787, ge=1, le=65535)  # HTTPS-Port
    http_port: int = Field(default=8786, ge=0, le=65535)  # 0 = kein HTTP-Redirect
    tls_enabled: bool = True
    tls_cert: Path = Path("/etc/familypc/panel.crt")
    tls_key: Path = Path("/etc/familypc/panel.key")
    session_hours: int = Field(default=12, ge=1, le=720)
    max_login_fails: int = Field(default=5, ge=1, le=100)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    admin_groups: list[str] = Field(default_factory=lambda: ["sudo"])  # deprecated ab FAM-12


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    tracking: Optional[TrackingConfig] = None  # None = Feature deaktiviert
    enforcement: Optional[EnforcementConfig] = None  # None = Feature deaktiviert
    accounts: dict[str, AccountConfig] = Field(default_factory=dict)
    ui: Optional[UiConfig] = None  # None = UI deaktiviert


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Lädt und validiert die YAML-Config. Wirft ConfigError mit Klartext-Meldung."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config-Datei nicht gefunden: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config-Datei {config_path} ist kein gültiges YAML: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config-Datei {config_path} muss ein YAML-Mapping (Schlüssel: Werte) sein")
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Ungültige Config in {config_path}:\n{exc}") from exc


_HEADER = (
    "# FamilyPC-Konfiguration — wird von install.sh nach /etc/familypc/config.yaml installiert.\n"
    "# Aenderungen per Admin-UI (FAM-10) schreiben diese Datei atomar; der Daemon laedt sie automatisch neu.\n"
    "# Konvention: Fehlende Felder = Feature deaktiviert, der Daemon startet trotzdem.\n"
)


def save_config(config: Config, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    """Schreibt die Config atomar (temp-Datei + rename) als YAML — Kommentare gehen dabei verloren.

    Wird von der Admin-UI (FAM-10) benutzt; der Daemon uebernimmt die Aenderung per mtime-Reload.
    """
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = _HEADER + yaml.safe_dump(
        config.model_dump(mode="json"), sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o640)
    os.replace(tmp, config_path)
