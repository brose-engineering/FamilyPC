"""nftables-Verwaltung (FAM-5): eigene Tabelle `familypc`, Regeln per meta skuid.

Idempotent: apply() schreibt die komplette Tabelle per `nft -f` (Deklarationen
sind idempotent, Chains werden geflusht, dann Regeln neu gesetzt — keine Doppel-Regeln).
Fail-open: clear() loescht die Tabelle (Daemon-Stop, ExecStopPost).
Runner injizierbar für Tests.
"""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("familypc.nft")

TABLE = "familypc"
FAMILY = "inet"


def _default_runner(args: list[str], stdin_text: str | None = None) -> str:
    proc = subprocess.run(
        args, input=stdin_text, capture_output=True, text=True, timeout=15, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} rc={proc.returncode}: {proc.stderr.strip()}")
    return proc.stdout


def build_ruleset(blocked_uids: set[int]) -> str:
    lines = [
        f"table {FAMILY} {TABLE} {{",
        f"  chain output {{ type filter hook output priority 0; policy accept; }}",
        f"  chain input  {{ type filter hook input  priority 0; policy accept; }}",
        "}",
        f"flush chain {FAMILY} {TABLE} output",
        f"flush chain {FAMILY} {TABLE} input",
    ]
    for uid in sorted(blocked_uids):
        # Loopback explizit erlauben (sonst haengt z. B. Cinnamon beim Session-Start)
        lines.append(f"add rule {FAMILY} {TABLE} output meta skuid {uid} ip daddr 127.0.0.0/8 accept")
        lines.append(f"add rule {FAMILY} {TABLE} input  meta skuid {uid} ip saddr 127.0.0.0/8 accept")
        lines.append(f"add rule {FAMILY} {TABLE} output meta skuid {uid} drop")
        lines.append(f"add rule {FAMILY} {TABLE} input  meta skuid {uid} drop")
    return "\n".join(lines) + "\n"


class Nftables:
    def __init__(self, runner=None) -> None:
        self._run = runner or _default_runner

    def apply(self, blocked_uids: set[int]) -> None:
        ruleset = build_ruleset(blocked_uids)
        self._run(["nft", "-f", "-"], stdin_text=ruleset)
        log.info("nftables Tabelle %s gesetzt: blockierte uids=%s", TABLE, sorted(blocked_uids) or "keine")

    def clear(self) -> None:
        """Fail-open: Tabelle komplett entfernen (idempotent, Fehler ignoriert)."""
        try:
            self._run(["nft", "delete", "table", FAMILY, TABLE])
            log.info("nftables Tabelle %s entfernt (fail-open)", TABLE)
        except Exception as exc:
            log.warning("nft delete table %s fehlgeschlagen (evtl. nicht vorhanden): %s", TABLE, exc)
