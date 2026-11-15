"""Unit-Tests für nftables/Internet-Blocker (FAM-5) mit Fake-Runner und Fake-uids."""

from familypc.config import AccountConfig
from familypc.internet import InternetBlocker
from familypc.nft import Nftables, build_ruleset

UIDS = {"kind1": 1002, "kind2": 1003, "kind3": 1004, "parent": 1001, "root": 0}


def uid_fn(user):
    return UIDS.get(user)


class FakeNft:
    def __init__(self):
        self.calls = []  # (args, stdin)

    def __call__(self, args, stdin_text=None):
        self.calls.append((args, stdin_text))
        return ""


def test_ruleset_enthaelt_tabelle_chains_und_skuid_regeln():
    rs = build_ruleset({1002, 1003})
    assert "table inet familypc {" in rs
    assert "chain output { type filter hook output priority 0; policy accept; }" in rs
    assert "chain input" in rs
    assert "flush chain inet familypc output" in rs  # keine Doppel-Regeln
    # Loopback muss VOR dem Drop erlaubt sein (sonst schwarzer Screen beim Login)
    out_rules = [l for l in rs.splitlines() if "output" in l and "skuid 1002" in l]
    assert out_rules[0].endswith("ip daddr 127.0.0.0/8 accept")
    assert out_rules[1].endswith("drop")
    assert "add rule inet familypc input  meta skuid 1002 ip saddr 127.0.0.0/8 accept" in rs
    assert "add rule inet familypc input  meta skuid 1002 drop" in rs
    assert "meta skuid 1003" in rs


def test_ruleset_leer_bei_keinen_uids():
    rs = build_ruleset(set())
    assert "meta skuid" not in rs
    assert "flush chain inet familypc output" in rs


def test_apply_ruft_nft_f_aus():
    fake = FakeNft()
    Nftables(runner=fake).apply({1002})
    assert fake.calls[0][0] == ["nft", "-f", "-"]
    assert "meta skuid 1002 drop" in fake.calls[0][1]


def test_clear_loescht_tabelle_fail_open():
    fake = FakeNft()
    Nftables(runner=fake).clear()
    assert fake.calls[0][0] == ["nft", "delete", "table", "inet", "familypc"]

    def boom(args, stdin_text=None):
        raise RuntimeError("table gibts nicht")

    Nftables(runner=boom).clear()  # darf nicht werfen


def test_blocker_baut_soll_zustand_aus_config():
    accounts = {
        "kind1": AccountConfig(internet_enabled=False),
        "kind2": AccountConfig(internet_enabled=True),
        "kind3": AccountConfig(),  # nicht gesetzt = Feature aus
    }
    fake = FakeNft()
    blocker = InternetBlocker(Nftables(runner=fake), accounts, protected_users={"parent"}, uid_fn=uid_fn)
    assert blocker.desired_blocked_uids() == {1002}  # nur kind1 blockiert


def test_blocker_protected_und_system_user_nie_blockiert():
    accounts = {
        "parent": AccountConfig(internet_enabled=False),  # protected -> nie
        "root": AccountConfig(internet_enabled=False),    # uid 0 -> nie
        "kind1": AccountConfig(internet_enabled=False),
    }
    fake = FakeNft()
    blocker = InternetBlocker(Nftables(runner=fake), accounts, protected_users={"parent"}, uid_fn=uid_fn)
    assert blocker.desired_blocked_uids() == {1002}


def test_sync_nur_bei_aenderung():
    accounts = {"kind1": AccountConfig(internet_enabled=False)}
    fake = FakeNft()
    blocker = InternetBlocker(Nftables(runner=fake), accounts, protected_users=set(), uid_fn=uid_fn)
    blocker.sync()
    blocker.sync()
    assert len(fake.calls) == 1  # zweiter sync ohne Aenderung -> kein nft-Aufruf
    accounts["kind2"] = AccountConfig(internet_enabled=False)
    blocker.sync()
    assert len(fake.calls) == 2
    assert "meta skuid 1003 drop" in fake.calls[1][1]
    blocker.clear()
    assert fake.calls[-1][0] == ["nft", "delete", "table", "inet", "familypc"]
