"""FAM-14: Quick-Actions (extend/terminate/internet) + SSE-Live-Stream — Unit-Tests."""

import pytest
from fastapi.testclient import TestClient

from test_fam10 import csrf, make_panel
from familypc.config import load_config


def test_extend_erhoeht_budget(tmp_path):
    client, path, _, _ = make_panel(tmp_path)  # kind1 budget=120
    r = client.post("/api/accounts/kind1/extend", json={"minutes": 15}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert load_config(path).accounts["kind1"].daily_budget_minutes == 135


def test_extend_ab_jetzt_wenn_unbegrenzt(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    # kind2 neu anlegen ohne Budget, 300 s verbraucht -> ceil=5 min -> +30 = 35
    client.put("/api/accounts/kind2", json={}, headers=csrf(client))
    from familypc.usage import usage_day
    from datetime import datetime
    from familypc.usage import UsageStore

    # Store der App beschreiben: ueber status-Endpunkt nicht direkt — wir nutzen denselben DB-Pfad
    import test_fam10 as t

    store = UsageStore(tmp_path / "usage.db")
    store.add("kind2", usage_day(datetime(2026, 11, 15, 16, 0)), 300.0)
    r = client.post("/api/accounts/kind2/extend", json={"minutes": 30}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert load_config(path).accounts["kind2"].daily_budget_minutes == 35


def test_extend_ungeeignet_422_und_404(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    assert client.post("/api/accounts/kind1/extend", json={"minutes": 0}, headers=csrf(client)).status_code == 422
    assert client.post("/api/accounts/kind9/extend", json={"minutes": 15}, headers=csrf(client)).status_code == 404
    assert load_config(path).accounts["kind1"].daily_budget_minutes == 120  # unveraendert


def test_terminate_ruft_terminate_fn(tmp_path):
    called = []
    import test_fam10 as t
    from familypc.config import Config, TrackingConfig, EnforcementConfig, UiConfig, save_config
    from familypc.panel import PanelAuth, create_panel_app
    from familypc.usage import UsageStore

    cfg = Config(tracking=TrackingConfig(), enforcement=EnforcementConfig(), accounts={}, ui=UiConfig())
    path = tmp_path / "config.yaml"
    save_config(cfg, path)
    auth = PanelAuth(tmp_path / "panel.db", hasher=t.FakeHasher())
    auth.add_user("parent", "geheim")
    app = create_panel_app(path, tmp_path, auth, store=UsageStore(tmp_path / "u.db"),
                           logind=type("L", (), {"trackable_users": lambda self, **kw: set()})(),
                           static_dir=None, cookie_secure=False, terminate_fn=lambda u: called.append(u))
    client = TestClient(app)
    client.post("/api/login", json={"username": "parent", "password": "geheim"})
    r = client.post("/api/accounts/kind1/terminate", headers=csrf(client))
    assert r.status_code == 200
    assert called == ["kind1"]


def test_internet_toggle_schreibt_config(tmp_path):
    client, path, _, _ = make_panel(tmp_path)
    r = client.post("/api/accounts/kind1/internet", json={"enabled": False}, headers=csrf(client))
    assert r.status_code == 200
    assert load_config(path).accounts["kind1"].internet_enabled is False
    r = client.post("/api/accounts/kind1/internet", json={"enabled": True}, headers=csrf(client))
    assert load_config(path).accounts["kind1"].internet_enabled is True


def test_sse_events_stream(tmp_path):
    client, _, _, _ = make_panel(tmp_path)
    with client.stream("GET", "/api/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        chunk = next(r.iter_text())
        assert chunk.startswith("data: ")
        import json

        payload = json.loads(chunk[len("data: "):])
        assert payload["accounts"][0]["user"] == "kind1"


def test_quick_actions_ohne_login_401(tmp_path):
    client, _, _, _ = make_panel(tmp_path)
    client.post("/api/logout", headers=csrf(client))
    assert client.post("/api/accounts/kind1/extend", json={"minutes": 15}).status_code == 401
    assert client.post("/api/accounts/kind1/terminate").status_code == 401
    assert client.post("/api/accounts/kind1/internet", json={"enabled": False}).status_code == 401
    assert client.get("/api/events").status_code == 401
