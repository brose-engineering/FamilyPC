"""Unit-Tests für das Config-Schema (FAM-2)."""

import pytest

from familypc.config import ConfigError, load_config


def write(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_leere_datei_gibt_defaults(tmp_path):
    cfg = load_config(write(tmp_path, ""))
    assert cfg.daemon.log_level == "INFO"
    assert cfg.daemon.heartbeat_interval_seconds == 60
    assert cfg.accounts == {}


def test_fehlende_felder_sind_feature_deaktiviert(tmp_path):
    cfg = load_config(write(tmp_path, "accounts:\n  kind1: {}\n"))
    account = cfg.accounts["kind1"]
    assert account.daily_budget_minutes is None  # unbegrenzt
    assert account.internet_enabled is None  # Feature aus
    assert account.windows == {}


def test_vollstaendige_config(tmp_path):
    path = write(
        tmp_path,
        """
daemon:
  log_level: DEBUG
  heartbeat_interval_seconds: 30
  state_dir: /tmp/familypc-state
accounts:
  kind1:
    daily_budget_minutes: 120
    internet_enabled: false
    internet_daily_budget_minutes: 60
    windows:
      0: [{ start: "15:00", end: "19:00" }, { start: "20:00", end: "21:30" }]
      6: [{ start: "09:00", end: "19:00" }]
""",
    )
    cfg = load_config(path)
    assert cfg.daemon.log_level == "DEBUG"
    assert cfg.daemon.heartbeat_interval_seconds == 30
    kind1 = cfg.accounts["kind1"]
    assert kind1.daily_budget_minutes == 120
    assert kind1.internet_enabled is False
    assert len(kind1.windows[0]) == 2
    assert kind1.windows[6][0].start == "09:00"


def test_datei_fehlt(tmp_path):
    with pytest.raises(ConfigError, match="nicht gefunden"):
        load_config(tmp_path / "gibt-es-nicht.yaml")


def test_kein_yaml(tmp_path):
    with pytest.raises(ConfigError, match="YAML"):
        load_config(write(tmp_path, "daemon: [kaputt"))


def test_kein_mapping(tmp_path):
    with pytest.raises(ConfigError, match="Mapping"):
        load_config(write(tmp_path, "- nur\n- eine\n- liste\n"))


@pytest.mark.parametrize(
    "snippet",
    [
        "daemon:\n  heartbeat_interval_seconds: 0\n",  # ge=1 verletzt
        "daemon:\n  log_level: LOUD\n",  # ungültiges Literal
        "accounts:\n  kind1:\n    daily_budget_minutes: -5\n",  # ge=0 verletzt
        "accounts:\n  kind1:\n    windows:\n      7: [{ start: '09:00', end: '10:00' }]\n",  # Wochentag > 6
        "accounts:\n  kind1:\n    windows:\n      0: [{ start: '25:00', end: '26:00' }]\n",  # HH:MM ungültig
        "accounts:\n  kind1:\n    windows:\n      0: [{ start: '19:00', end: '15:00' }]\n",  # start >= end
        "unbekannter_key: 1\n",  # extra=forbid
    ],
)
def test_ungueltige_config_wirft_config_error(tmp_path, snippet):
    with pytest.raises(ConfigError, match="Ungültige Config"):
        load_config(write(tmp_path, snippet))
