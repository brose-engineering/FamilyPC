"""Unix-Socket-Control-Server für den PAM-Hook.

Pro Verbindung eine Zeile Username -> Antwort "ALLOW" oder "DENY <grund>".
Läuft im Daemon als root; Socket 0666 (pam_exec läuft mit seteuid als User).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("familypc.control")

DEFAULT_SOCKET_PATH = "/run/familypc/control.sock"


class ControlServer:
    def __init__(self, enforcer, socket_path: str = DEFAULT_SOCKET_PATH, now_fn=datetime.now) -> None:
        self.enforcer = enforcer
        self.socket_path = socket_path
        self._now = now_fn
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._stopping = threading.Event()

    def start(self) -> None:
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.socket_path)
        os.chmod(self.socket_path, 0o666)
        self._sock.listen(16)
        self._sock.settimeout(0.5)
        self._thread = threading.Thread(target=self._serve, name="familypc-control", daemon=True)
        self._thread.start()
        log.info("Control-Socket aktiv: %s", self.socket_path)

    def _serve(self) -> None:
        while not self._stopping.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with conn:
                    conn.settimeout(2.0)
                    data = conn.makefile("r").readline().strip()
                    user = data.split()[0] if data else ""
                    if not user:
                        conn.sendall(b"DENY empty-user\n")
                        continue
                    allowed, reason = self.enforcer.may_login(user, self._now())
                    verdict = "ALLOW" if allowed else f"DENY {reason}"
                    conn.sendall(f"{verdict}\n".encode())
                    log.info("PAM-Check %s -> %s", user, verdict)
            except Exception as exc:
                log.warning("Control-Verbindung fehlgeschlagen: %s", exc)

    def stop(self) -> None:
        self._stopping.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
