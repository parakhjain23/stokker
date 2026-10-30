import numpy as np
import pandas as pd
import pytest

from stockkk import ai, data, db, engine, news, setups

GOOD = dict(reasoning="r", technical="t", fundamental="f", news="n", invalidation="i")


def _cand(sym="TCS", rr=2.0, p=0.45, r=0.3):
    return {"symbol": sym, "name": sym, "direction": "BUY", "entry": 100, "stop": 95, "target": 110, "rr": rr,
            "hold_days": 10, "trigger": False, "backtest_win_prob": p, "backtest_avg_r": r, "setup": "x"}


def test_no_trade_when_threshold_fails():  # Covers AE2
    con = db.connect(":memory:")
    pick = ai.Pick(symbol="TCS", confidence_adj=-15, **GOOD)  # 0.05 + (-0.15*3) < 0.10
    assert engine.publish(con, "swing", [_cand(r=0.05)], [pick], "", "2026-10-30") == 0
    row = con.execute("SELECT status, reasoning FROM recommendations").fetchone()
    assert row["status"] == "NO_TRADE" and "quality threshold" in row["reasoning"]


def test_publishes_all_fields():
    con = db.connect(":memory:")
    picks = [ai.Pick(symbol=s, confidence_adj=5, **GOOD) for s in ("A", "B", "C")]
    assert engine.publish(con, "swing", [_cand(s) for s in "ABC"], picks, "", "2026-10-30") == 3
    row = dict(con.execute("SELECT * FROM recommendations").fetchone())
    assert row["confidence"] == 50 and row["expected_r"] == 0.45 and row["status"] == "OPEN"
    for k in ("symbol", "direction", "entry", "stop", "target", "rr", "hold_days", "reasoning", "invalidation"):
        assert row[k] not in (None, "")


def test_low_rr_excluded():
    con = db.connect(":memory:")
    pick = ai.Pick(symbol="TCS", confidence_adj=0, **GOOD)
    assert engine.publish(con, "swing", [_cand(rr=1.8)], [pick], "", "2026-10-30") == 0


@pytest.fixture
def world(monkeypatch):
    """Two synthetic stocks, one always-on test setup, mocked network."""
    idx = pd.date_range("2025-01-01", periods=300, freq="B")
    prices = {}
    for s in ("AAA", "BBB"):
        c = np.linspace(100, 200, 300)
        prices[s] = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0}, index=idx)
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
    monkeypatch.setattr(ai, "rank", lambda h, c, m: ([ai.Pick(symbol="AAA", confidence_adj=0, **GOOD)], ""))
    summary = engine.run(con, prices)
    assert summary["swing"] == "1 published"
    assert summary["intraday"] == "NO TRADE" and summary["longterm"] == "NO TRADE"
    assert engine.run(con, prices)["swing"] == "already published"
    # five more rising bars: price climbs past the target (entry + 10)
    more = pd.date_range(prices["AAA"].index[-1] + pd.offsets.BDay(), periods=5, freq="B")
    c = np.linspace(205, 215, 5)
    prices["AAA"] = pd.concat([prices["AAA"], pd.DataFrame(
        {"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0}, index=more)])
    assert setups.grade_open(con, prices) == 1
    assert con.execute("SELECT status FROM recommendations WHERE symbol='AAA'").fetchone()[0] == "TARGET_HIT"


def test_ai_unavailable_publishes_nothing(world, monkeypatch):
    con, prices = world
    monkeypatch.setattr(ai, "rank", lambda h, c, m: (_ for _ in ()).throw(ai.AIUnavailable("timeout")))
    assert engine.run(con, prices)["swing"] == "AI unavailable"
    assert con.execute("SELECT COUNT(*) FROM recommendations WHERE horizon='swing'").fetchone()[0] == 0
    assert db.get_meta(con, "ai_status_swing")[0].startswith("AI unavailable")


def test_stale_symbol_excluded(world, monkeypatch):  # Covers AE1
    con, prices = world
    prices["BBB"] = prices["BBB"].iloc[:-1]  # missing latest bar
    seen = {}

    def fake_rank(h, cands, market):
        seen[h] = [c["symbol"] for c in cands]
        return [], ""
    monkeypatch.setattr(ai, "rank", fake_rank)
    engine.run(con, prices)
    assert seen["swing"] == ["AAA"]
