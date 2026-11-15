"""Helper fuer das Admin-Panel (FAM-10/13): Liste der lokalen Nutzerkonten.

Das Panel selbst (FastAPI-App, Auth, Service) liegt in familypc/panel.py.
"""

from __future__ import annotations

import pwd


def local_human_users(min_uid: int = 1000) -> list[str]:
    """Lokale Benutzerkonten (uid >= 1000, keine System/NIS-Accounts) — fuer das Dropdown im UI."""
    users = [pw.pw_name for pw in pwd.getpwall() if pw.pw_uid >= min_uid and pw.pw_uid < 65534]
    return sorted(set(users))
