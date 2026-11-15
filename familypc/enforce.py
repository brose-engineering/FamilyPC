"""Policy-Engine (FAM-7 Tagesbudget + FAM-8 Nutzungsfenster).

tick(): pro Daemon-Tick Budget/Warnungen/Fenster pruefen, ggf. Notification
(D-Bus) + Logout (loginctl terminate-user).
may_login(): Entscheid fuer den PAM-Hook (Login verweigern).
Uhr/Notify/Terminate sind injizierbar — Unit-Tests mit simulierter Uhr.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .config import AccountConfig, EnforcementConfig
from .internet import uid_of
from .notify import send_notification, terminate_user
from .usage import UsageStore, usage_day

log = logging.getLogger("familypc.enforce")


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class Enforcer:
    def __init__(
        self,
        cfg: EnforcementConfig,
        accounts: dict[str, AccountConfig],
        store: UsageStore,
        *,
        now_fn=datetime.now,
        reset_hour: int = 0,
        notify_fn=None,
        terminate_fn=None,
        uid_fn=uid_of,
    ) -> None:
        self.cfg = cfg
        self.accounts = accounts
        self.store = store
        self._now = now_fn
        self._reset_hour = reset_hour
        self._notify = notify_fn or (lambda user, s, b: send_notification(user, s, b))
        self._terminate = terminate_fn or terminate_user
        self._uid_fn = uid_fn
        self.last_internet_blocked: set[int] = set()  # FAM-9: uids mit aufgebrauchtem Internet-Budget

    # ---------- Fenster-Logik ----------

    def _windows_today(self, acct: AccountConfig, now: datetime) -> list[tuple[int, int]]:
        return [(_to_min(w.start), _to_min(w.end)) for w in acct.windows.get(now.weekday(), [])]

    @staticmethod
    def _inside(windows: list[tuple[int, int]], t: int) -> bool:
        return any(s <= t <= e for s, e in windows)

    # ---------- Login-Entscheid (PAM) ----------

    def may_login(self, user: str, now: datetime | None = None) -> tuple[bool, str]:
        now = now or self._now()
        if user in self.cfg.protected_users:
            return True, "geschuetztes Konto"
        acct = self.accounts.get(user)
        if acct is None:
            return True, "kein Konto konfiguriert"
        day = usage_day(now, self._reset_hour)
        budget = acct.daily_budget_minutes
        if budget and self.store.get(user, day) >= budget * 60:
            return False, "Tagesbudget aufgebraucht"
        if acct.windows:  # Fenster konfiguriert -> nur innerhalb erlaubt
            windows = self._windows_today(acct, now)
            t = now.hour * 60 + now.minute
            if not windows:
                return False, "heute kein Nutzungsfenster konfiguriert"
            if not self._inside(windows, t):
                return False, "ausserhalb des Nutzungsfensters"
        return True, "ok"

    # ---------- Täglicher Tick ----------

    def tick(self, active_users: set[str], now: datetime | None = None) -> None:
        now = now or self._now()
        day = usage_day(now, self._reset_hour)
        t = now.hour * 60 + now.minute
        internet_blocked: set[int] = set()
        for user, acct in self.accounts.items():
            if user in self.cfg.protected_users:
                continue
            if not self._tick_budget(user, acct, day):
                continue  # wurde gerade abgemeldet
            self._tick_windows(user, acct, now, t, day, active_users)
            if self._tick_internet_budget(user, acct, day):
                uid = self._uid_fn(user)
                if uid is not None and uid >= 1000:
                    internet_blocked.add(uid)
        self.last_internet_blocked = internet_blocked

    def _tick_internet_budget(self, user: str, acct: AccountConfig, day) -> bool:
        """FAM-9: True = Internet-Budget aufgebraucht -> Konto sperren."""
        budget = acct.internet_daily_budget_minutes
        if not budget:
            return False
        used = self.store.get_internet(user, day)
        if used < budget * 60:
            return False
        if not self.store.has_alert(user, day, "internet_exhausted"):
            self._notify(
                user,
                "FamilyPC: Internet-Zeit aufgebraucht",
                f"Das Internet-Tagesbudget von {budget} Minuten ist aufgebraucht — der Internetzugang wird gesperrt. Der PC bleibt nutzbar.",
            )
            self.store.add_alert(user, day, "internet_exhausted")
            log.info("Internet-Budget %s aufgebraucht (%.0fs/%smin)", user, used, budget)
        return True

    def _tick_budget(self, user: str, acct: AccountConfig, day) -> bool:
        """True = Session darf weiterlaufen."""
        budget = acct.daily_budget_minutes
        if not budget:
            return True
        used = self.store.get(user, day)
        remaining = budget * 60 - used
        if remaining <= 0:
            if not self.store.has_alert(user, day, "budget_exhausted"):
                self._notify(
                    user,
                    "FamilyPC: Zeit aufgebraucht",
                    f"Das Tagesbudget von {budget} Minuten ist aufgebraucht — du wirst abgemeldet.",
                )
                self.store.add_alert(user, day, "budget_exhausted")
                log.info("Budget %s aufgebraucht (%.0fs/%smin)", user, used, budget)
            if not self.store.has_alert(user, day, "budget_logout"):
                self._terminate(user)
                self.store.add_alert(user, day, "budget_logout")
            return False
        for w in sorted(self.cfg.warn_minutes, reverse=True):
            if remaining <= w * 60 and not self.store.has_alert(user, day, f"warn_{w}"):
                self._notify(
                    user,
                    f"FamilyPC: noch {w} Minuten",
                    f"Dein Tagesbudget ({budget} Minuten) ist in {w} Minuten aufgebraucht.",
                )
                self.store.add_alert(user, day, f"warn_{w}")
                log.info("Warnung an %s: noch %s min", user, w)
                break
        return True

    def _tick_windows(self, user: str, acct: AccountConfig, now: datetime, t: int, day, active_users: set[str]) -> None:
        if not acct.windows:
            return
        windows = self._windows_today(acct, now)
        if self._inside(windows, t):
            # Vorwarnung vor Ende des laufenden Fensters
            end = max(e for s, e in windows if s <= t <= e)
            pre = self.cfg.window_prewarning_minutes
            if end - pre <= t and not self.store.has_alert(user, day, "window_end_warn"):
                self._notify(
                    user,
                    "FamilyPC: Nutzungsfenster endet bald",
                    f"Das Fenster endet um {_to_hhmm(end)} — die Session wird dann beendet.",
                )
                self.store.add_alert(user, day, "window_end_warn")
                log.info("Fenster-Vorwarnung an %s (endet %s)", user, _to_hhmm(end))
            return
        # Ausserhalb des Fensters: laufende Session sofort beenden
        if user in active_users:
            if not self.store.has_alert(user, day, "window_logout"):
                self._notify(
                    user,
                    "FamilyPC: Nutzungsfenster beendet",
                    "Du wurdest abgemeldet, weil das Nutzungsfenster abgelaufen ist.",
                )
                self.store.add_alert(user, day, "window_logout")
            if not self.store.has_alert(user, day, "window_terminated"):
                self._terminate(user)
                self.store.add_alert(user, day, "window_terminated")
                log.info("Fenster abgelaufen: %s abgemeldet", user)
