"""Admin-Panel (FAM-11/12/13): eigenes systemd-Unit `familypc-panel.service`.

FAM-12: Panel-eigene Accounts in SQLite (Argon2-Hashes), Login mit Session-Cookies
(HttpOnly, Secure, SameSite=Strict) + CSRF-Double-Submit, Rate-Limiting (Sperre nach
max_login_fails Fehlversuchen). Ohne Login kein API-Zugriff — auch nicht von localhost.
Passwoerter landen nie im Klartext oder im Log.

FAM-13: Bindung ans LAN (ui.host), HTTPS mit selbstsigniertem Zertifikat,
HTTP-zu-HTTPS-Redirect auf ui.http_port, Erreichbarkeit via familypc.local (Avahi).

Das Panel ist stateless gegenueber dem Daemon: Config-Datei + usage.db + logind werden
pro Request gelesen; Config-Aenderungen uebernimmt der Daemon per mtime-Reload.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .config import AccountConfig, Config, ConfigError, load_config, save_config
from .sessions import Logind
from .status import build_status
from .usage import UsageStore, usage_day

log = logging.getLogger("familypc.panel")

SESSION_COOKIE = "familypc_session"
CSRF_COOKIE = "familypc_csrf"

PANEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS panel_users (
    username    TEXT PRIMARY KEY,
    pw_hash     TEXT NOT NULL,
    fail_count  INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS panel_sessions (
    token    TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    csrf     TEXT NOT NULL,
    created  REAL NOT NULL,
    expires  REAL NOT NULL
);
"""


class PanelAuth:
    """Panel-Accounts + Sessions + Rate-Limiting (FAM-12). Uhr/Hasher injizierbar fuer Tests."""

    def __init__(self, db_path: str | Path, *, hasher=None, now_fn=time.time, max_fails: int = 5, lockout_seconds: int = 900) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now_fn
        self._max_fails = max_fails
        self._lockout = lockout_seconds
        if hasher is None:
            from argon2 import PasswordHasher

            hasher = PasswordHasher()
        self._hasher = hasher
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        with self._lock:
            self._conn.executescript(PANEL_SCHEMA)
            self._conn.commit()

    # ---------- Accounts ----------

    def add_user(self, username: str, password: str) -> None:
        if not username or not password:
            raise ValueError("Username und Passwort duerfen nicht leer sein")
        pw_hash = self._hasher.hash(password)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO panel_users(username, pw_hash) VALUES (?, ?) "
                "ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash, fail_count=0, locked_until=0",
                (username, pw_hash),
            )

    def remove_user(self, username: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM panel_users WHERE username = ?", (username,))
            return cur.rowcount > 0

    def list_users(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT username FROM panel_users ORDER BY username").fetchall()
        return [r[0] for r in rows]

    # ---------- Login / Rate-Limit ----------

    def check_login(self, username: str, password: str, client_ip: str = "-") -> tuple[bool, str]:
        """Prueft Login; zaehlt Fehlversuche, sperrt nach max_fails. Loggt niemals das Passwort."""
        with self._lock:
            row = self._conn.execute(
                "SELECT pw_hash, fail_count, locked_until FROM panel_users WHERE username = ?", (username,)
            ).fetchone()
        now = self._now()
        if row is None:
            log.warning("Panel-Login fehlgeschlagen: unbekannter Benutzer %r ip=%s", username, client_ip)
            return False, "unbekannter Benutzer"
        pw_hash, fail_count, locked_until = row
        if locked_until and now < locked_until:
            log.warning("Panel-Login verweigert: %r gesperrt bis %s ip=%s", username, datetime.fromtimestamp(locked_until), client_ip)
            return False, "zu viele Fehlversuche — temporaer gesperrt"
        try:
            ok = self._hasher.verify(pw_hash, password)
        except Exception:
            ok = False
        if ok:
            with self._lock, self._conn:
                self._conn.execute(
                    "UPDATE panel_users SET fail_count=0, locked_until=0 WHERE username = ?", (username,)
                )
            return True, "ok"
        fail_count += 1
        locked_until = now + self._lockout if fail_count >= self._max_fails else 0.0
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE panel_users SET fail_count=?, locked_until=? WHERE username = ?",
                (fail_count, locked_until, username),
            )
        log.warning("Panel-Login fehlgeschlagen: %r ip=%s (%s/%s)%s", username, client_ip, fail_count, self._max_fails, " — GESPERRT" if locked_until else "")
        # Der Sperr-ausloesende Versuch selbst antwortet noch 401; erst danach greift die Sperre (423).
        return False, "falsches Passwort"

    # ---------- Sessions ----------

    def create_session(self, username: str, session_hours: int = 12) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = self._now()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO panel_sessions(token, username, csrf, created, expires) VALUES (?, ?, ?, ?, ?)",
                (token, username, csrf, now, now + session_hours * 3600),
            )
        return token, csrf

    def check_session(self, token: str | None) -> dict | None:
        """Liefert {username, csrf} bei gueltiger Session, sonst None (abgelaufen wird aufgeraeumt)."""
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT username, csrf, expires FROM panel_sessions WHERE token = ?", (token,)
            ).fetchone()
        if row is None:
            return None
        username, csrf, expires = row
        if self._now() > expires:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM panel_sessions WHERE token = ?", (token,))
            return None
        return {"username": username, "csrf": csrf}

    def destroy_session(self, token: str | None) -> None:
        if not token:
            return
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM panel_sessions WHERE token = ?", (token,))

    def close(self) -> None:
        self._conn.close()


# ---------- zertrifikats- helper (FAM-13) ----------

def ensure_selfsigned_cert(cert_path: Path, key_path: Path, cn: str = "familypc.local", runner=None) -> None:
    """Erzeugt ein selbstsigniertes Zertifikat, falls nicht vorhanden (openssl)."""
    cert_path = Path(cert_path)
    key_path = Path(key_path)
    if cert_path.is_file() and key_path.is_file():
        return
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    run = runner or (lambda args: __import__("subprocess").run(args, check=True, capture_output=True))
    run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key_path), "-out", str(cert_path), "-days", "3650",
        "-subj", f"/CN={cn}",
        "-addext", f"subjectAltName=DNS:{cn},DNS:localhost,IP:127.0.0.1",
    ])
    import os

    os.chmod(key_path, 0o600)
    log.info("Selbstsigniertes Panel-Zertifikat erzeugt: %s (CN=%s)", cert_path, cn)


# ---------- App ----------

def create_panel_app(
    config_path: Path,
    state_dir: Path,
    auth: PanelAuth,
    *,
    store: UsageStore | None = None,
    logind=None,
    users_fn=None,
    static_dir: Path | None = None,
    now_fn=datetime.now,
    session_hours: int = 12,
    cookie_secure: bool = True,
    terminate_fn=None,
) -> FastAPI:
    """Panel-App mit FAM-12-Auth. Ohne gueltige Session kein API-Zugriff (401)."""
    from .ui import local_human_users  # FAM-10 Dropdown

    app = FastAPI(title="FamilyPC Admin-Panel", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.auth = auth
    app.state.config_path = Path(config_path)
    app.state.store = store or UsageStore(Path(state_dir) / "usage.db")
    app.state.logind = logind or Logind()
    app.state.now_fn = now_fn
    app.state.session_hours = session_hours
    app.state.cookie_secure = cookie_secure
    if terminate_fn is None:
        from .notify import terminate_user

        terminate_fn = terminate_user
    app.state.terminate_fn = terminate_fn

    def _load_cfg() -> Config:
        return load_config(app.state.config_path)

    def _active_users(cfg: Config) -> set[str]:
        t = cfg.tracking
        try:
            return app.state.logind.trackable_users(
                excluded_users=set(t.excluded_users) if t else {"root", "lightdm"},
                count_remote=t.count_remote_sessions if t else False,
                count_inactive=t.count_inactive_sessions if t else True,
            )
        except Exception as exc:
            log.warning("logind-Abfrage im Panel fehlgeschlagen: %s", exc)
            return set()

    def _internet_blocked(cfg: Config, store: UsageStore, now: datetime) -> set[int]:
        from .internet import uid_of

        day = usage_day(now, cfg.tracking.reset_hour if cfg.tracking else 0)
        blocked = set()
        for user, acct in cfg.accounts.items():
            uid = uid_of(user)
            if uid is None or uid < 1000:
                continue
            if acct.internet_enabled is False:
                blocked.add(uid)
            elif acct.internet_daily_budget_minutes and store.has_alert(user, day, "internet_exhausted"):
                blocked.add(uid)
        return blocked

    @app.middleware("http")
    async def auth_and_csrf(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/login":
            session = auth.check_session(request.cookies.get(SESSION_COOKIE))
            if session is None:
                return JSONResponse(status_code=401, content={"detail": "Login erforderlich"})
            request.state.session = session
            if request.method != "GET":
                csrf_cookie = request.cookies.get(CSRF_COOKIE)
                csrf_header = request.headers.get("X-CSRF-Token")
                if not csrf_cookie or csrf_header != session["csrf"] or csrf_header != csrf_cookie:
                    return JSONResponse(status_code=403, content={"detail": "CSRF-Token ungueltig"})
        return await call_next(request)

    def _set_session_cookies(response: JSONResponse, token: str, csrf: str) -> JSONResponse:
        secure = "; Secure" if app.state.cookie_secure else ""
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/", max_age=app.state.session_hours * 3600, secure=app.state.cookie_secure)
        response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="strict", path="/", max_age=app.state.session_hours * 3600, secure=app.state.cookie_secure)
        return response

    @app.post("/api/login")
    def api_login(body: dict, request: Request):
        username = str(body.get("username") or "")
        password = str(body.get("password") or "")
        client_ip = request.client.host if request.client else "-"
        ok, reason = auth.check_login(username, password, client_ip)
        if not ok:
            status = 423 if "gesperrt" in reason else 401
            return JSONResponse(status_code=status, content={"detail": reason})
        token, csrf = auth.create_session(username, app.state.session_hours)
        log.info("Panel-Login ok: %s ip=%s", username, client_ip)
        resp = JSONResponse({"ok": True, "user": username})
        return _set_session_cookies(resp, token, csrf)

    @app.post("/api/logout")
    def api_logout(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        auth.destroy_session(token)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        resp.delete_cookie(CSRF_COOKIE, path="/")
        return resp

    @app.get("/api/whoami")
    def api_whoami(request: Request):
        return {"user": request.state.session["username"]}

    @app.get("/api/status")
    def api_status():
        cfg = _load_cfg()
        now = app.state.now_fn()
        return build_status(
            cfg,
            app.state.store,
            now=now,
            active_users=_active_users(cfg),
            internet_blocked_uids=_internet_blocked(cfg, app.state.store, now),
        )

    @app.get("/api/config")
    def api_config():
        cfg = _load_cfg()
        return {"accounts": {u: a.model_dump(mode="json") for u, a in cfg.accounts.items()}}

    @app.get("/api/users")
    def api_users():
        list_users = users_fn or local_human_users
        return {"users": list_users()}

    @app.get("/api/events")
    async def api_events(request: Request):
        """FAM-14: Live-Restzeiten per Server-Sent-Events (ohne Reload)."""

        async def gen():
            while True:
                if await request.is_disconnected():
                    break
                try:
                    cfg = _load_cfg()
                    now = app.state.now_fn()
                    payload = build_status(
                        cfg,
                        app.state.store,
                        now=now,
                        active_users=_active_users(cfg),
                        internet_blocked_uids=_internet_blocked(cfg, app.state.store, now),
                    )
                    import json as _json

                    yield f"data: {_json.dumps(payload)}\n\n"
                except Exception as exc:
                    log.warning("SSE-Status fehlgeschlagen: %s", exc)
                await asyncio.sleep(3)

        return StreamingResponse(gen(), media_type="text/event-stream")

    # ---------- FAM-14: Quick-Actions ----------

    @app.post("/api/accounts/{user}/extend")
    def api_extend(user: str, body: dict):
        """+X Minuten Tagesbudget (ab jetzt, wenn bisher unbegrenzt)."""
        try:
            minutes = int(body.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if minutes <= 0:
            return JSONResponse(status_code=422, content={"detail": "minutes muss > 0 sein"})

        def mutator(cfg):
            if user not in cfg.accounts:
                raise KeyError(user)
            acct = cfg.accounts[user]
            now = app.state.now_fn()
            day = usage_day(now, cfg.tracking.reset_hour if cfg.tracking else 0)
            used_min = math.ceil(app.state.store.get(user, day) / 60)
            base = acct.daily_budget_minutes if acct.daily_budget_minutes else used_min
            acct.daily_budget_minutes = base + minutes

        try:
            return _write_accounts(mutator)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": f"kein Konto {user!r} konfiguriert"})

    @app.post("/api/accounts/{user}/terminate")
    def api_terminate(user: str):
        """Aktive Session sofort beenden (loginctl terminate-user)."""
        app.state.terminate_fn(user)
        log.info("Panel: Session von %s manuell beendet", user)
        return {"ok": True, "user": user}

    @app.post("/api/accounts/{user}/internet")
    def api_internet(user: str, body: dict):
        """Internet an/aus schalten (schreibt Config, Daemon uebernimmt sofort)."""
        enabled = bool(body.get("enabled"))

        def mutator(cfg):
            if user not in cfg.accounts:
                raise KeyError(user)
            cfg.accounts[user].internet_enabled = enabled

        try:
            return _write_accounts(mutator)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": f"kein Konto {user!r} konfiguriert"})

    def _write_accounts(mutator) -> JSONResponse:
        try:
            cfg = load_config(app.state.config_path)
            mutator(cfg)
            save_config(cfg, app.state.config_path)
        except ConfigError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Config ungueltig: {exc}"})
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Ungueltige Regeln: {exc}"})
        log.info("Panel hat Config geaendert: %s (Daemon laedt neu)", app.state.config_path)
        return JSONResponse({"ok": True, "accounts": {u: a.model_dump(mode="json") for u, a in cfg.accounts.items()}})

    @app.put("/api/accounts/{user}")
    def api_put_account(user: str, body: dict):
        try:
            acct = AccountConfig.model_validate(body)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Ungueltige Regeln: {exc}"})

        def mutator(cfg):
            cfg.accounts[user] = acct

        return _write_accounts(mutator)

    @app.delete("/api/accounts/{user}")
    def api_delete_account(user: str):
        def mutator(cfg):
            if user not in cfg.accounts:
                raise KeyError(user)
            del cfg.accounts[user]

        try:
            return _write_accounts(mutator)
        except KeyError:
            return JSONResponse(status_code=404, content={"detail": f"kein Konto {user!r} konfiguriert"})

    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")

    return app


# ---------- HTTP -> HTTPS Redirect (FAM-13) ----------

class HttpRedirect(threading.Thread):
    """Leitet HTTP-Anfragen auf https://<host>:<port> um (301)."""

    def __init__(self, http_port: int, https_port: int, host: str = "0.0.0.0") -> None:
        super().__init__(name="familypc-panel-http-redirect", daemon=True)
        from http.server import BaseHTTPRequestHandler, HTTPServer

        https_port_ = https_port

        class Handler(BaseHTTPRequestHandler):
            def _redirect(self):
                target = f"https://{self.headers.get('Host', 'localhost').split(':')[0]}:{https_port_}{self.path}"
                self.send_response(301)
                self.send_header("Location", target)
                self.end_headers()

            do_GET = do_POST = do_PUT = do_DELETE = _redirect

            def log_message(self, *args):
                pass

        self._server = HTTPServer((host, http_port), Handler)

    def run(self):
        log.info("HTTP-Redirect aktiv: :%s -> HTTPS", self._server.server_port)
        self._server.serve_forever()

    def stop(self):
        self._server.shutdown()


# ---------- main (systemd-Unit familypc-panel.service) ----------

def main(argv=None) -> int:
    import logging as _l
    import sys

    _l.basicConfig(stream=sys.stderr, level=_l.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="familypc-panel", description="FamilyPC Admin-Panel (FAM-11/12/13)")
    parser.add_argument("--config", type=Path, default=Path("/etc/familypc/config.yaml"))
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("Config-Fehler: %s", exc)
        return 2
    ui = config.ui
    if ui is None or not ui.enabled:
        log.info("ui-Sektion fehlt/deaktiviert — Panel startet nicht.")
        return 0

    import uvicorn

    state_dir = config.daemon.state_dir
    auth = PanelAuth(
        state_dir / "panel.db",
        max_fails=ui.max_login_fails,
        lockout_seconds=ui.lockout_minutes * 60,
    )
    if not auth.list_users():
        log.warning("Noch keine Panel-Accounts angelegt — Initial-Account: sudo familypc-panel-admin --config %s add <name>", args.config)

    if ui.tls_enabled:
        ensure_selfsigned_cert(ui.tls_cert, ui.tls_key)

    static_candidates = [
        Path(__file__).resolve().parent / "ui_static",
        Path("/opt/familypc/ui_static"),
        Path("/opt/familypc/familypc/ui_static"),
    ]
    static_dir = next((p for p in static_candidates if p.is_dir()), None)

    app = create_panel_app(
        args.config,
        state_dir,
        auth,
        static_dir=static_dir,
        session_hours=ui.session_hours,
        cookie_secure=ui.tls_enabled,
    )

    # uvicorn >= 0.54: kein ssl= mehr, sondern ssl_certfile/ssl_keyfile
    ssl_kwargs = {}
    if ui.tls_enabled:
        ssl_kwargs = {"ssl_certfile": str(ui.tls_cert), "ssl_keyfile": str(ui.tls_key)}

    redirect = None
    if ui.http_port and ui.http_port != ui.port:
        redirect = HttpRedirect(ui.http_port, ui.port, host=ui.host)
        redirect.start()

    log.info("Admin-Panel startet: %s://%s:%s (TLS=%s)", "https" if ssl_kwargs else "http", ui.host, ui.port, ui.tls_enabled)
    server = uvicorn.Server(uvicorn.Config(app, host=ui.host, port=ui.port, log_level="warning", access_log=False, **ssl_kwargs))
    try:
        server.run()
    finally:
        if redirect is not None:
            redirect.stop()
        auth.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
