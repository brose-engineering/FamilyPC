"""FAM-10/12/13: Admin-Panel (panel.py) — API-Tests mit Login-Session + CSRF, stateless Status."""

import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from familypc.config import AccountConfig, Config, EnforcementConfig, TimeWindow, TrackingConfig, UiConfig, load_config, save_config
from familypc.daemon import Daemon
from familypc.panel import PanelAuth, create_panel_app
from familypc.state import RuntimeState
from familypc.usage import UsageStore, usage_day

NOW = datetime(2026, 11, 15, 16, 0)  # Sonntag (weekday 6), 16:00 Uhr


class FakeHasher:
    def hash(self, pw):
        return "h:" + pw

    def verify(self, h, pw):
        return h == "h:" + pw


class FakeClock:
    def __init__(self):
        self.t = 1_700_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


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


def make_panel(tmp_path, active_users={"kind1"}):
    """Panel-App mit PanelAuth (FakeHasher) + frischem Login. Liefert (client, path, auth)."""
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    store = UsageStore(tmp_path / "usage.db")
    store.add("kind1", usage_day(NOW), 300.0)
    store.add_internet("kind1", usage_day(NOW), 60.0)
    clock = FakeClock()
    auth = PanelAuth(tmp_path / "panel.db", hasher=FakeHasher(), now_fn=clock, max_fails=5, lockout_seconds=900)
    auth.add_user("parent", "geheim")
    logind = type("L", (), {"trackable_users": lambda self, **kw: set(active_users)})()
    app = create_panel_app(
        path,
        tmp_path,
        auth,
        store=store,
        logind=logind,
        users_fn=lambda: ["kind1", "kind2", "parent"],
        static_dir=None,
        now_fn=lambda: NOW,
        session_hours=12,
        cookie_secure=False,
    )
    client = TestClient(app)
    r = client.post("/api/login", json={"username": "parent", "password": "geheim"})
    assert r.status_code == 200, r.text
    return client, path, auth, clock


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("familypc_csrf")}


# ---------- Config save/load ----------

def test_save_config_roundtrip(tmp_path):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.model_dump(mode="json") == cfg.model_dump(mode="json")
    assert path.stat().st_mode & 0o777 == 0o640


# ---------- FAM-12: ohne Login kein Zugriff ----------

def test_ohne_login_kein_api_zugriff(tmp_path):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    auth = PanelAuth(tmp_path / "panel.db", hasher=FakeHasher())
    auth.add_user("parent", "geheim")
    app = create_panel_app(path, tmp_path, auth, store=UsageStore(tmp_path / "u.db"),
                           logind=type("L", (), {"trackable_users": lambda self, **kw: set()})(),
                           static_dir=None, cookie_secure=False)
    anon = TestClient(app)
    assert anon.get("/api/status").status_code == 401
    assert anon.get("/api/config").status_code == 401
    assert anon.put("/api/accounts/kind1", json={}).status_code == 401
    assert anon.get("/api/whoami").status_code == 401
    # Login-Endpunkt ist offen, falsches Passwort -> 401
    assert anon.post("/api/login", json={"username": "parent", "password": "falsch"}).status_code == 401


def test_login_falsches_passwort_und_kein_passwort_im_log(tmp_path, caplog):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    auth = PanelAuth(tmp_path / "panel.db", hasher=FakeHasher())
    auth.add_user("parent", "geheim")
    app = create_panel_app(path, tmp_path, auth, store=UsageStore(tmp_path / "u.db"),
                           logind=type("L", (), {"trackable_users": lambda self, **kw: set()})(),
                           static_dir=None, cookie_secure=False)
    client = TestClient(app)
    with caplog.at_level("WARNING", logger="familypc.panel"):
        r = client.post("/api/login", json={"username": "parent", "password": "falsch123"})
    assert r.status_code == 401
    assert "falsch123" not in caplog.text  # Passwort nie im Log


# ---------- FAM-10 API (angemeldet) ----------

def test_status_live_restzeiten(tmp_path):
    client, _, _, _ = make_panel(tmp_path)
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["day"] == "2026-11-15"
    kind1 = next(a for a in data["accounts"] if a["user"] == "kind1")
    assert kind1["active"] is True
    assert kind1["pc"]["remaining_seconds"] == pytest.approx(120 * 60 - 300)
    assert kind1["internet"]["remaining_seconds"] == pytest.approx(60 * 60 - 60)
    assert kind1["internet"]["blocked_now"] is False
    assert kind1["window"]["allowed_now"] is True
    assert kind1["window"]["current_end"] == "19:00"


def test_put_account_aendert_config_datei(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    body = {
        "daily_budget_minutes": 5,
        "internet_enabled": False,
        "internet_daily_budget_minutes": None,
        "windows": {"6": [{"start": "16:00", "end": "18:00"}]},
    }
    r = client.put("/api/accounts/kind1", json=body, headers=csrf(client))
    assert r.status_code == 200, r.text
    reloaded = load_config(path)
    assert reloaded.accounts["kind1"].daily_budget_minutes == 5
    assert reloaded.accounts["kind1"].internet_enabled is False


def test_put_ohne_csrf_header_403(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    before = path.read_text()
    r = client.put("/api/accounts/kind1", json={"daily_budget_minutes": 5})  # kein X-CSRF-Token
    assert r.status_code == 403
    assert path.read_text() == before


def test_put_ungueltig_422_und_datei_unveraendert(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    before = path.read_text()
    r = client.put("/api/accounts/kind1", json={"windows": {"6": [{"start": "19:00", "end": "15:00"}]}}, headers=csrf(client))
    assert r.status_code == 422
    assert path.read_text() == before


def test_put_legt_neues_konto_an_und_reset(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    r = client.put("/api/accounts/kind9", json={"daily_budget_minutes": 45}, headers=csrf(client))
    assert r.status_code == 200
    assert load_config(path).accounts["kind9"].daily_budget_minutes == 45
    # Reset auf Standard
    r = client.put("/api/accounts/kind9", json={}, headers=csrf(client))
    assert r.status_code == 200
    acct = load_config(path).accounts["kind9"]
    assert acct.daily_budget_minutes is None and acct.windows == {}


def test_delete_account(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    assert client.delete("/api/accounts/kind1", headers=csrf(client)).status_code == 200
    assert "kind1" not in load_config(path).accounts
    assert client.delete("/api/accounts/kind1", headers=csrf(client)).status_code == 404


def test_api_users_liste(tmp_path):
    client, _, _, _ = make_panel(tmp_path)
    r = client.get("/api/users")
    assert r.status_code == 200
    assert r.json() == {"users": ["kind1", "kind2", "parent"]}


def test_logout_entwertet_session(tmp_path):
    client, _, _, _ = make_panel(tmp_path)
    assert client.get("/api/status").status_code == 200
    assert client.post("/api/logout", headers=csrf(client)).status_code == 200
    assert client.get("/api/status").status_code == 401


# ---------- FAM-12: Rate-Limit / Sperre / Session ----------

def test_rate_limit_sperrt_nach_5_fehlversuchen(tmp_path):
    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    clock = FakeClock()
    auth = PanelAuth(tmp_path / "panel.db", hasher=FakeHasher(), now_fn=clock, max_fails=5, lockout_seconds=900)
    auth.add_user("parent", "geheim")
    app = create_panel_app(path, tmp_path, auth, store=UsageStore(tmp_path / "u.db"),
                           logind=type("L", (), {"trackable_users": lambda self, **kw: set()})(),
                           static_dir=None, cookie_secure=False)
    client = TestClient(app)
    for i in range(5):
        r = client.post("/api/login", json={"username": "parent", "password": "falsch"})
        assert r.status_code == 401
    # jetzt gesperrt: auch das richtige Passwort -> 423
    r = client.post("/api/login", json={"username": "parent", "password": "geheim"})
    assert r.status_code == 423
    # nach Ablauf der Sperre geht es wieder
    clock.advance(901)
    r = client.post("/api/login", json={"username": "parent", "password": "geheim"})
    assert r.status_code == 200


def test_session_ablauf(tmp_path):
    client, _, auth, clock = make_panel(tmp_path)
    assert client.get("/api/whoami").json()["user"] == "parent"
    clock.advance(13 * 3600)  # Session 12 h
    assert client.get("/api/status").status_code == 401


def test_uvicorn_config_tls_kwarg(tmp_path):
    # Regression: uvicorn >= 0.54 kennt 'ssl=' nicht mehr — ssl_certfile/ssl_keyfile nutzen
    import uvicorn
    from fastapi import FastAPI

    cfg = uvicorn.Config(
        FastAPI(), host="127.0.0.1", port=0,
        ssl_certfile=str(tmp_path / "panel.crt"), ssl_keyfile=str(tmp_path / "panel.key"),
    )
    assert cfg.ssl_certfile.endswith("panel.crt")
    assert cfg.ssl_keyfile.endswith("panel.key")


# ---------- Daemon-Config-Reload (unveraendert aus FAM-10) ----------

def test_daemon_reload_ohne_neustart(tmp_path):
    import os

    cfg = make_config()
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    state = RuntimeState(cfg)
    tracker = type("T", (), {"last_active_users": set(), "update": lambda self, c, iu: setattr(self, "updated", True)})()
    enforcer = type("E", (), {"last_internet_blocked": set(), "update": lambda self, c, a: setattr(self, "updated", True)})()
    internet = type("I", (), {"update": lambda self, a, p: setattr(self, "updated", True)})()
    daemon = Daemon(cfg, tracker=tracker, enforcer=enforcer, internet=internet, config_path=path, state=state)

    cfg.accounts["kind1"].daily_budget_minutes = 5
    save_config(cfg, path)
    t = time.time() + 5
    os.utime(path, (t, t))
    daemon._maybe_reload_config()
    assert daemon.config.accounts["kind1"].daily_budget_minutes == 5
    assert state.get_config().accounts["kind1"].daily_budget_minutes == 5
    assert tracker.updated and enforcer.updated and internet.updated

    path.write_text("accounts: [kaputt\n")
    t = time.time() + 10
    os.utime(path, (t, t))
    daemon._maybe_reload_config()
    assert daemon.config.accounts["kind1"].daily_budget_minutes == 5
