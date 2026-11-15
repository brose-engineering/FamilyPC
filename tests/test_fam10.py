"""FAM-10: Admin-UI (FastAPI) + Config-Auto-Reload des Daemons — Unit-Tests mit simulierter Uhr."""

import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from familypc.config import AccountConfig, Config, EnforcementConfig, TimeWindow, TrackingConfig, UiConfig, load_config, save_config
from familypc.daemon import Daemon
from familypc.state import RuntimeState
from familypc.ui import create_app
from familypc.usage import UsageStore, usage_day

NOW = datetime(2026, 11, 15, 16, 0)  # Sonntag (weekday 6), 16:00 Uhr


def make_config() -> Config:
    return Config(
        tracking=TrackingConfig(),
        enforcement=EnforcementConfig(),
        accounts={
            "kind1": AccountConfig(
                daily_budget_minutes=120,
                internet_enabled=True,
                internet_daily_budget_minutes=60,
                windows={6: [TimeWindow(start="15:00", end="19:00")]},
            )
        },
        ui=UiConfig(),
    )


def make_app(tmp_path, peer_uid=1001, is_admin=None):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    store = UsageStore(tmp_path / "usage.db")
    store.add("kind1", usage_day(NOW), 300.0)  # 5 min verbraucht
    store.add_internet("kind1", usage_day(NOW), 60.0)  # 1 min Internet verbraucht
    state = RuntimeState(cfg)
    state.tracker = SimpleNamespace(last_active_users={"kind1"})
    state.enforcer = SimpleNamespace(last_internet_blocked=set())
    app = create_app(
        state,
        path,
        store,
        peer_uid_fn=lambda client_port, server_port: peer_uid,
        is_admin_fn=is_admin or (lambda uid, groups: uid in (0, 1001)),
        now_fn=lambda: NOW,
    )
    return app, path, state


# ---------- Config save/load ----------

def test_save_config_roundtrip(tmp_path):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.model_dump(mode="json") == cfg.model_dump(mode="json")
    assert path.stat().st_mode & 0o777 == 0o640


# ---------- UI-API ----------

def test_status_live_restzeiten(tmp_path):
    app, _, _ = make_app(tmp_path)
    client = TestClient(app)
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["day"] == "2026-11-15"
    kind1 = next(a for a in data["accounts"] if a["user"] == "kind1")
    assert kind1["active"] is True
    assert kind1["pc"]["budget_minutes"] == 120
    assert kind1["pc"]["remaining_seconds"] == pytest.approx(120 * 60 - 300)
    assert kind1["internet"]["remaining_seconds"] == pytest.approx(60 * 60 - 60)
    assert kind1["internet"]["blocked_now"] is False
    assert kind1["window"]["allowed_now"] is True
    assert kind1["window"]["current_end"] == "19:00"


def test_put_account_aendert_config_datei(tmp_path):
    app, path, _ = make_app(tmp_path)
    client = TestClient(app)
    body = {
        "daily_budget_minutes": 5,
        "internet_enabled": False,
        "internet_daily_budget_minutes": None,
        "windows": {"6": [{"start": "16:00", "end": "18:00"}]},
    }
    r = client.put("/api/accounts/kind1", json=body)
    assert r.status_code == 200, r.text
    reloaded = load_config(path)
    assert reloaded.accounts["kind1"].daily_budget_minutes == 5
    assert reloaded.accounts["kind1"].internet_enabled is False
    assert reloaded.accounts["kind1"].windows[6][0].start == "16:00"


def test_put_account_ungueltig_422_und_datei_unveraendert(tmp_path):
    app, path, _ = make_app(tmp_path)
    client = TestClient(app)
    before = path.read_text()
    r = client.put("/api/accounts/kind1", json={"windows": {"6": [{"start": "19:00", "end": "15:00"}]}})
    assert r.status_code == 422
    assert path.read_text() == before  # atomar: kaputte Aenderung landet nicht in der Datei


def test_delete_account(tmp_path):
    app, path, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.delete("/api/accounts/kind1").status_code == 200
    assert "kind1" not in load_config(path).accounts
    assert client.delete("/api/accounts/kind1").status_code == 404


def test_zugriff_nur_fuer_admin_uid(tmp_path):
    app, _, _ = make_app(tmp_path, peer_uid=1002, is_admin=lambda uid, groups: uid in (0, 1001))
    client = TestClient(app)
    assert client.get("/api/status").status_code == 403
    assert client.put("/api/accounts/kind1", json={}).status_code == 403


def test_uiserver_start_stop(tmp_path, monkeypatch):
    # Regression: uvicorn.Server hat kein .app — UiServer muss die App selbst halten
    import uvicorn

    from familypc.ui import UiServer

    app, _, _ = make_app(tmp_path)
    server = UiServer(app, "127.0.0.1", 0)

    def fake_run(self):
        while not self.should_exit:
            time.sleep(0.01)

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    server.start()
    assert server._thread is not None and server._thread.is_alive()
    server.stop()
    server._thread.join(timeout=2)
    assert not server._thread.is_alive()


# ---------- Daemon-Config-Reload ----------

def _bump_mtime(path):
    t = time.time() + 5
    os.utime(path, (t, t))


def test_daemon_reload_ohne_neustart(tmp_path):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    state = RuntimeState(cfg)
    tracker = SimpleNamespace(last_active_users=set(), updated=False)
    tracker.update = lambda c, iu: setattr(tracker, "updated", True)
    enforcer = SimpleNamespace(last_internet_blocked=set(), updated=False)
    enforcer.update = lambda c, a: setattr(enforcer, "updated", True)
    internet = SimpleNamespace(updated=False)
    internet.update = lambda a, p: setattr(internet, "updated", True)
    daemon = Daemon(cfg, tracker=tracker, enforcer=enforcer, internet=internet, config_path=path, state=state)

    # UI schreibt neue Config -> Daemon uebernimmt sie beim naechsten Tick
    cfg.accounts["kind1"].daily_budget_minutes = 5
    save_config(cfg, path)
    _bump_mtime(path)
    daemon._maybe_reload_config()
    assert daemon.config.accounts["kind1"].daily_budget_minutes == 5
    assert state.get_config().accounts["kind1"].daily_budget_minutes == 5
    assert tracker.updated and enforcer.updated and internet.updated

    # Kaputte Datei: alte Config bleibt aktiv, kein Crash
    path.write_text("accounts: [kaputt\n")
    _bump_mtime(path)
    daemon._maybe_reload_config()
    assert daemon.config.accounts["kind1"].daily_budget_minutes == 5
