"""Internet-Sperre pro Konto (FAM-5): rechnet accounts.internet_enabled in
nftables-Regeln um. Admin-/geschuetzte Konten und root werden niemals blockiert.
"""

from __future__ import annotations

import logging
import pwd

from .config import AccountConfig
from .nft import Nftables

log = logging.getLogger("familypc.internet")


def uid_of(user: str) -> int | None:
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return None


class InternetBlocker:
    def __init__(
        self,
        nft: Nftables,
        accounts: dict[str, AccountConfig],
        protected_users: set[str],
        uid_fn=uid_of,
    ) -> None:
        self.nft = nft
        self.accounts = accounts
        self.protected = protected_users
        self._uid_fn = uid_fn
        self._applied: set[int] | None = None  # None = noch nicht synchronisiert

    def desired_blocked_uids(self) -> set[int]:
        blocked: set[int] = set()
        for user, acct in self.accounts.items():
            if acct.internet_enabled is False and user not in self.protected:
                uid = self._uid_fn(user)
                if uid is None:
                    log.warning("internet: unbekannter User %r wird nicht blockiert", user)
                    continue
                if uid < 1000:
                    continue  # System-User nie blockieren
                blocked.add(uid)
        return blocked

    def sync(self, extra_blocked: set[int] | None = None) -> None:
        """Soll-Zustand = Config-Sperren (internet_enabled:false) + extra (FAM-9 Budget aufgebraucht)."""
        desired = self.desired_blocked_uids() | (extra_blocked or set())
        if desired == self._applied:
            return
        self.nft.apply(desired)
        self._applied = desired

    def clear(self) -> None:
        """Fail-open beim Daemon-Stop."""
        self.nft.clear()
        self._applied = None
