"""Entry-Point: python -m familypc [--config PATH] [--check-config].

Exit-Codes: 0 = OK, 2 = Config-Fehler (systemd wertet 2 als sauberes Ende,
 damit bei Config-Fehlern kein Restart-Loop entsteht — siehe familypc.service).
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, ConfigError, load_config
from .control import ControlServer
from .daemon import Daemon
from .enforce import Enforcer
from .internet import InternetBlocker
from .nft import Nftables
from .sessions import Logind
from .state import RuntimeState
from .tracker import SessionTracker
from .usage import UsageStore

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="familypc",
        description="FamilyPC-Daemon: Nutzungszeiten & Internet-Sperre pro Nutzerkonto",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Pfad zur Config (Default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Config nur laden/validieren und beenden (Exit 0 = OK, 2 = Fehler)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    # Frühes Logging auf stderr: landet unter systemd im journald.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("familypc")

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        log.error("Config-Fehler: %s", exc)
        return EXIT_CONFIG_ERROR

    if args.check_config:
        log.info("Config OK: %s", args.config)
        return EXIT_OK

    logging.getLogger().setLevel(config.daemon.log_level)

    store = None
    tracker = None
    if config.tracking is not None and config.tracking.enabled:
        store = UsageStore(config.daemon.state_dir / "usage.db")
        # FAM-9: Internet-Verbrauch nur fuer Konten mit Internet-Budget mitzaehlen
        internet_users = {
            u for u, a in config.accounts.items() if a.internet_daily_budget_minutes
        }
        tracker = SessionTracker(config.tracking, store, Logind(), internet_users=internet_users)

    enforcer = None
    control = None
    if config.enforcement is not None and config.enforcement.enabled:
        if store is None:
            store = UsageStore(config.daemon.state_dir / "usage.db")
        reset_hour = config.tracking.reset_hour if config.tracking else 0
        enforcer = Enforcer(
            config.enforcement,
            config.accounts,
            store,
            reset_hour=reset_hour,
        )
        control = ControlServer(enforcer)

    protected = set(config.enforcement.protected_users) if config.enforcement else {"parent"}
    internet = InternetBlocker(Nftables(), config.accounts, protected)

    # FAM-10: gemeinsamer Runtime-State (Daemon schreibt Config-Reloads rein, UI liest mit)
    state = RuntimeState(config)
    state.tracker = tracker
    state.enforcer = enforcer

    daemon = Daemon(
        config,
        tracker=tracker,
        enforcer=enforcer,
        control=control,
        internet=internet,
        config_path=args.config,
        state=state,
    )
    signal.signal(signal.SIGTERM, daemon.request_stop)
    signal.signal(signal.SIGINT, daemon.request_stop)

    # FAM-10: Admin-UI im selben Prozess (uvicorn-Thread), Bind default 127.0.0.1
    ui_server = None
    if config.ui is not None and config.ui.enabled:
        if store is None:
            store = UsageStore(config.daemon.state_dir / "usage.db")
            state.tracker = tracker
        from .ui import UiServer, create_app

        static_candidates = [
            Path(__file__).resolve().parent / "ui_static",
            Path("/opt/familypc/ui_static"),
            Path("/opt/familypc/familypc/ui_static"),
        ]
        static_dir = next((p for p in static_candidates if p.is_dir()), None)
        app = create_app(state, args.config, store, static_dir=static_dir)
        ui_server = UiServer(app, config.ui.host, config.ui.port)
        ui_server.start()
    try:
        return daemon.run()
    finally:
        if ui_server is not None:
            ui_server.stop()


if __name__ == "__main__":
    sys.exit(main())
