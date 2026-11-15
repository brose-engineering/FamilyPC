"""Admin-UI (FAM-10): FastAPI-Backend auf 127.0.0.1 + statisches React-Frontend.

Zugriff nur aus Admin-Sitzung: Die uid des Client-Prozesses wird ueber /proc
aus der TCP-Verbindung ermittelt (Loopback!) und gegen die Admin-Gruppen
(Default: sudo) geprueft. Kein Login-System, kein Netzwerkzugriff (Bind 127.0.0.1).

Aenderungen (PUT/DELETE /api/accounts/...) schreiben die Config-Datei atomar;
der Daemon laedt sie per mtime-Reload automatisch neu — kein Neustart nötig.
"""

from __future__ import annotations

import grp
import logging
import os
import pwd
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .config import AccountConfig, ConfigError, load_config, save_config
from .state import RuntimeState
from .status import build_status
from .usage import UsageStore

log = logging.getLogger("familypc.ui")

DEFAULT_ADMIN_GROUPS = ["sudo"]


# ---------- Peer-uid aus /proc (Loopback: Client laeuft auf derselben Maschine) ----------

def peer_uid_from_proc(
    client_port: int,
    server_port: int,
    proc_root: str = "/proc",
    uid_of_pid_fn=None,
) -> int | None:
    """Ermittelt die uid des Client-Prozesses ueber dessen socket (client-seitiger Eintrag!)."""
    if uid_of_pid_fn is None:
        uid_of_pid_fn = lambda pid: os.stat(Path(proc_root, pid)).st_uid
    inode = None
    for table in ("tcp", "tcp6"):
        try:
            lines = Path(proc_root, "net", table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "01":  # 01 = ESTABLISHED
                continue
            lport = int(parts[1].split(":")[1], 16)
            rport = int(parts[2].split(":")[1], 16)
            # client-seitiger Socket: local = client_port, remote = server_port
            # (die server-seitige Zeile wuerde auf den Daemon (root) zeigen)
            if lport == client_port and rport == server_port:
                inode = parts[9]
                break
        if inode is not None:
            break
    if inode is None:
        return None
    target = f"socket:[{inode}]"
    for pid in os.listdir(proc_root):
        if not pid.isdigit():
            continue
        fd_dir = Path(proc_root, pid, "fd")
        try:
            for fd in os.listdir(fd_dir):
                try:
                    if os.readlink(fd_dir / fd) == target:
                        return uid_of_pid_fn(pid)
                except OSError:
                    continue
        except OSError:
            continue
    return None


def local_human_users(min_uid: int = 1000) -> list[str]:
    """Lokale Benutzerkonten (uid >= 1000, keine System/NIS-Accounts) — fuer das Dropdown im UI."""
    users = [pw.pw_name for pw in pwd.getpwall() if pw.pw_uid >= min_uid and pw.pw_uid < 65534]
    return sorted(set(users))


def default_is_admin(uid: int, admin_groups: list[str]) -> bool:
    if uid == 0:
        return True
    try:
        user = pwd.getpwuid(uid).pw_name
    except KeyError:
        return False
    if user in admin_groups:
        return True
    primary = pwd.getpwuid(uid).pw_gid
    try:
        if grp.getgrgid(primary).gr_name in admin_groups:
            return True
    except KeyError:
        pass
    return any(user in g.gr_mem and g.gr_name in admin_groups for g in grp.getgrall())


# ---------- App ----------

def create_app(
    state: RuntimeState,
    config_path: Path,
    store: UsageStore,
    *,
    peer_uid_fn=None,
    is_admin_fn=None,
    users_fn=None,
    static_dir: Path | None = None,
    now_fn=datetime.now,
) -> FastAPI:
    """peer_uid_fn/is_admin_fn sind fuer Unit-Tests injizierbar."""
    app = FastAPI(title="FamilyPC Admin-UI", docs_url=None, redoc_url=None, openapi_url=None)
    server_port_holder = {"port": 0}

    @app.middleware("http")
    async def admin_only(request: Request, call_next):
        cfg = state.get_config()
        ui_cfg = cfg.ui
        admin_groups = ui_cfg.admin_groups if ui_cfg is not None else DEFAULT_ADMIN_GROUPS
        client = request.client
        uid = peer_uid_fn(client.port, server_port_holder["port"]) if peer_uid_fn else peer_uid_from_proc(
            client.port, server_port_holder["port"]
        )
        check = is_admin_fn or default_is_admin
        if uid is None or not check(uid, admin_groups):
            log.warning("UI-Zugriff verweigert: client=%s uid=%s path=%s", client, uid, request.url.path)
            return JSONResponse(status_code=403, content={"detail": "nur aus Admin-Sitzung (sudo-Gruppe) erreichbar"})
        return await call_next(request)

    @app.get("/api/status")
    def api_status():
        cfg = state.get_config()
        return build_status(cfg, store, state.tracker, state.enforcer, now_fn())

    @app.get("/api/config")
    def api_config():
        cfg = state.get_config()
        return {"accounts": {u: a.model_dump(mode="json") for u, a in cfg.accounts.items()}}

    @app.get("/api/users")
    def api_users():
        """Lokale Nutzerkonten fuer das Anlegen-Dropdown im UI."""
        list_users = users_fn or local_human_users
        return {"users": list_users()}

    def _write_accounts(mutator) -> JSONResponse:
        try:
            cfg = load_config(config_path)
            mutator(cfg)
            save_config(cfg, config_path)
        except ConfigError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Config ungueltig: {exc}"})
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Ungueltige Regeln: {exc}"})
        log.info("UI hat Config geaendert: %s (Daemon laedt neu)", config_path)
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

    # Server-Port fuer peer_uid_from_proc merken (Einmal-Init nach erstem Request nicht noetig: aus App-Config)
    def set_server_port(port: int) -> None:
        server_port_holder["port"] = port

    app.state.set_server_port = set_server_port
    return app


class UiServer:
    """Uvicorn in einem Daemon-Thread, damit der systemd-Service eine einzige Einheit bleibt."""

    def __init__(self, app: FastAPI, host: str, port: int) -> None:
        import uvicorn

        self._app = app
        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(self._config)
        self._thread: threading.Thread | None = None
        self.port = port

    def start(self) -> None:
        set_server_port = getattr(self._app.state, "set_server_port", None)
        if set_server_port is not None:
            set_server_port(self.port)
        self._thread = threading.Thread(target=self._server.run, name="familypc-ui", daemon=True)
        self._thread.start()
        log.info("Admin-UI aktiv: http://%s:%s", self._config.host, self.port)

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)
