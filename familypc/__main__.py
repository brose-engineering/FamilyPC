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
from .daemon import Daemon

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

    daemon = Daemon(config)
    signal.signal(signal.SIGTERM, daemon.request_stop)
    signal.signal(signal.SIGINT, daemon.request_stop)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
