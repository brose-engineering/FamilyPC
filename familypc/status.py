"""Live-Status pro Konto (FAM-10 Admin-UI): Restzeiten, Fenster, Internet.

Wird von der UI-API gelesen; Logik spiegelt Enforcer/Config (gleiche Tageslogik via usage_day).
Uhr ist injizierbar für Unit-Tests.
"""

from __future__ import annotations

from datetime import datetime

from .config import AccountConfig, Config, _parse_hhmm
from .internet import uid_of
from .usage import UsageStore, usage_day


def _to_min(hhmm: str) -> int:
    h, m = _parse_hhmm(hhmm, "time")
    return h * 60 + m


def _fmt_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def account_status(
    user: str,
    acct: AccountConfig,
    store: UsageStore,
    now: datetime,
    reset_hour: int,
    active_users: set[str],
    internet_blocked_uids: set[int],
    protected: bool,
) -> dict:
    day = usage_day(now, reset_hour)
    t = now.hour * 60 + now.minute

    # PC-Budget (FAM-7)
    pc_used = store.get(user, day)
    pc_budget = acct.daily_budget_minutes or None  # 0/None = unbegrenzt
    if pc_budget is not None:
        pc_remaining = max(0.0, pc_budget * 60 - pc_used)
        pc_exhausted = pc_remaining <= 0
    else:
        pc_remaining = None
        pc_exhausted = False

    # Internet (FAM-5 + FAM-9)
    inet_used = store.get_internet(user, day)
    inet_budget = acct.internet_daily_budget_minutes or None
    if inet_budget is not None:
        inet_remaining = max(0.0, inet_budget * 60 - inet_used)
    else:
        inet_remaining = None
    uid = uid_of(user)
    blocked_now = acct.internet_enabled is False or (uid is not None and uid in internet_blocked_uids)

    # Fenster (FAM-8)
    windows_today = [{"start": w.start, "end": w.end} for w in acct.windows.get(now.weekday(), [])]
    minutes = [(_to_min(w["start"]), _to_min(w["end"])) for w in windows_today]
    inside = [e for s, e in minutes if s <= t <= e]
    allowed_now: bool | None = None
    if acct.windows:
        allowed_now = bool(minutes) and any(s <= t <= e for s, e in minutes)
    return {
        "user": user,
        "protected": protected,
        "active": user in active_users,
        "pc": {
            "used_seconds": round(pc_used, 1),
            "budget_minutes": pc_budget,
            "remaining_seconds": None if pc_remaining is None else round(pc_remaining, 1),
            "exhausted": pc_exhausted,
        },
        "internet": {
            "enabled": acct.internet_enabled,
            "used_seconds": round(inet_used, 1),
            "budget_minutes": inet_budget,
            "remaining_seconds": None if inet_remaining is None else round(inet_remaining, 1),
            "blocked_now": blocked_now,
        },
        "window": {
            "configured": bool(acct.windows),
            "allowed_now": allowed_now,
            "today": windows_today,
            "current_end": _fmt_hhmm(max(inside)) if inside else None,
        },
    }


def build_status(config: Config, store: UsageStore, tracker, enforcer, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    reset_hour = config.tracking.reset_hour if config.tracking else 0
    protected = set(config.enforcement.protected_users) if config.enforcement else {"parent"}
    active_users = tracker.last_active_users if tracker is not None else set()
    internet_blocked = enforcer.last_internet_blocked if enforcer is not None else set()
    users = set(config.accounts) | active_users
    return {
        "now": now.isoformat(timespec="seconds"),
        "day": usage_day(now, reset_hour).isoformat(),
        "accounts": [
            account_status(u, config.accounts.get(u, AccountConfig()), store, now, reset_hour, active_users, internet_blocked, u in protected)
            for u in sorted(users)
        ],
    }
