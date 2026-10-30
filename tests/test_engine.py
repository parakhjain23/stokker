import numpy as np
import pandas as pd
import pytest

from stockkk import ai, data, db, engine, news, setups


def _a(sym, adj=0, verdict="TAKE"):
    return ai.Assessment(symbol=sym, verdict=verdict, confidence_adj=adj, reasoning="r", technical="t",
                         fundamental="f", news="n", invalidation="i")


def _cand(sym="TCS", rr=2.0, p=0.45, r=0.3, proven=True):
    return {"symbol": sym, "name": sym, "direction": "BUY", "entry": 100, "stop": 95, "target": 110, "rr": rr,
            "hold_days": 10, "trigger": False, "backtest_win_prob": p, "backtest_avg_r": r, "setup": "x",
            "setup_proven": proven, "exit_note": "Fixed target and stop."}


def test_no_trade_when_threshold_fails():  # Covers AE2
    con = db.connect(":memory:")
    assert engine.publish(con, "swing", [_cand(r=0.05)], {"TCS": _a("TCS", -15)}, "2026-10-30") == 0
    row = con.execute("SELECT status, reasoning FROM recommendations").fetchone()
    assert row["status"] == "NO_TRADE" and "quality bar" in row["reasoning"]
    assert con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1  # still ranked


def test_ranks_all_by_win_chance_and_publishes_passing():
    con = db.connect(":memory:")
    cands = [_cand("A", p=0.40), _cand("B", p=0.50), _cand("C", p=0.45, proven=False), _cand("D", p=0.30)]
    assessed = {"A": _a("A", 5), "B": _a("B", 0), "C": _a("C", 0), "D": _a("D", 0, "SKIP")}
    assert engine.publish(con, "swing", cands, assessed, "2026-10-30") == 2  # A, B (C unproven, D skipped)
    ranked = [tuple(r) for r in con.execute("SELECT rank, symbol, win_prob, recommended FROM candidates ORDER BY rank")]
    assert ranked == [(1, "B", 50, 1), (2, "A", 45, 1), (3, "C", 45, 0), (4, "D", 30, 0)]
    row = dict(con.execute("SELECT * FROM recommendations WHERE symbol='A'").fetchone())
    assert row["confidence"] == 45 and row["expected_r"] == 0.45
    for k in ("direction", "entry", "stop", "target", "rr", "hold_days", "reasoning", "invalidation"):
        assert row[k] not in (None, "")


def test_low_rr_excluded():
    con = db.connect(":memory:")
    assert engine.publish(con, "swing", [_cand(rr=0.3)], {"TCS": _a("TCS")}, "2026-10-30") == 0


def test_unproven_only_says_why():
    con = db.connect(":memory:")
    engine.publish(con, "swing", [_cand(proven=False)], {"TCS": _a("TCS")}, "2026-10-30")
    assert "unproven strategies" in con.execute("SELECT reasoning FROM recommendations").fetchone()[0]


@pytest.fixture
def world(monkeypatch):
    """Two synthetic liquid stocks, one always-on test setup, mocked network."""
    idx = pd.date_range("2025-01-01", periods=300, freq="B")
    prices = {}
    for s in ("AAA", "BBB"):
        c = np.linspace(100, 200, 300)
        prices[s] = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1e6}, index=idx)
    uni = pd.DataFrame({"symbol": ["AAA", "BBB"], "name": ["Aaa Ltd.", "Bbb Ltd."], "industry": ["IT", "IT"]})
    test_setup = setups.Setup("always", "swing", "test", lambda d: pd.Series(True, index=d.index),
                              lambda r: setups._trade("BUY", r.close, r.close - 5, 2.0, 5))
    monkeypatch.setattr(setups, "SETUPS", [test_setup])
    monkeypatch.setattr(data, "universe", lambda: uni)
    monkeypatch.setattr(data, "fundamentals", lambda con, s: {"pe": 20})
    monkeypatch.setattr(news, "fetch_symbol_news", lambda con, s, n: 0)
    con = db.connect(":memory:")
    con.execute("INSERT INTO setup_stats (setup, horizon, trades, hit_rate, avg_r, enabled) "
                "VALUES ('always','swing',100,0.5,0.4,1)")
    return con, prices


def test_full_run_then_grading(world, monkeypatch):
    con, prices = world
    monkeypatch.setattr(ai, "assess", lambda h, c, m: {"AAA": _a("AAA"), "BBB": _a("BBB", 0, "SKIP")})
    summary = engine.run(con, prices)
    assert summary["swing"] == "2 ranked, 1 recommended"
    assert summary["intraday"].startswith("NO TRADE")
    assert engine.run(con, prices)["swing"] == "already published"
    more = pd.date_range(prices["AAA"].index[-1] + pd.offsets.BDay(), periods=5, freq="B")
    c = np.linspace(205, 215, 5)
    prices["AAA"] = pd.concat([prices["AAA"], pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1e6}, index=more)])
    assert setups.grade_open(con, prices) == 1
    assert con.execute("SELECT status FROM recommendations WHERE symbol='AAA'").fetchone()[0] == "TARGET_HIT"


def test_ai_unavailable_publishes_nothing(world, monkeypatch):
    con, prices = world
    monkeypatch.setattr(ai, "assess", lambda h, c, m: (_ for _ in ()).throw(ai.AIUnavailable("timeout")))
    assert engine.run(con, prices)["swing"] == "AI unavailable"
    assert con.execute("SELECT COUNT(*) FROM recommendations WHERE horizon='swing'").fetchone()[0] == 0
    assert db.get_meta(con, "ai_status_swing")[0].startswith("AI unavailable")


def test_stale_and_illiquid_excluded(world, monkeypatch):  # Covers AE1
    con, prices = world
    prices["BBB"] = prices["BBB"].iloc[:-1]  # missing latest bar
    prices["CCC"] = prices["AAA"].assign(volume=10.0)  # trades far under ₹1 crore a day
    monkeypatch.setattr(data, "universe", lambda: pd.DataFrame(
        {"symbol": ["AAA", "BBB", "CCC"], "name": ["A", "B", "C"], "industry": ["IT"] * 3}))
    seen = {}

    def fake(h, cands, market):
        seen[h] = [c["symbol"] for c in cands]
        return {}
    monkeypatch.setattr(ai, "assess", fake)
    engine.run(con, prices)
    assert seen["swing"] == ["AAA"]
