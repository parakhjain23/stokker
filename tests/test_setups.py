import numpy as np
import pandas as pd

from stockkk import db, setups


def _walk(highs, lows, closes=None, opens=None, **kw):
    h, l = np.array(highs, float), np.array(lows, float)
    c = np.array(closes if closes else [(a + b) / 2 for a, b in zip(highs, lows)], float)
    o = np.array(opens if opens else c, float)
    dates = np.arange(len(h))
    args = dict(direction="BUY", entry=100, stop=95, target=110, hold_days=10) | kw
    return setups.walk(o, h, l, c, dates, **args)


def test_target_hit_before_stop():  # Covers AE4
    status, day, price, r = _walk([102, 105, 110, 104], [98, 97, 101, 90])
    assert status == "TARGET_HIT" and day == 2 and price == 110 and r == 2


def test_same_bar_assumes_stop():
    status, *_ = _walk([111], [94])
    assert status == "SL_HIT"


def test_expired_at_last_close():
    status, day, price, _ = _walk([103] * 3, [97] * 3, closes=[101, 102, 102.5], hold_days=3)
    assert status == "EXPIRED" and day == 2 and price == 102.5


def test_open_when_not_enough_bars():
    assert _walk([103, 103], [97, 97]) is None


def test_gap_down_fills_at_open():
    status, _, price, r = _walk([99, 95], [97, 90], opens=[98, 92])
    assert status == "SL_HIT" and price == 92 and r == -1.6


def test_sell_target_next_day_only():
    # a triggered order's target is never credited on the entry day (bar order unknown), but is on day 2
    kw = dict(direction="SELL", entry=100, stop=105, target=90, trigger=True)
    assert _walk([101], [89], opens=[100], closes=[95], hold_days=1, **kw)[0] == "EXPIRED"
    status, day, _, r = _walk([101, 96], [89, 88], opens=[100, 95], closes=[95, 90], hold_days=2, **kw)
    assert status == "TARGET_HIT" and day == 1 and r == 2


def test_limit_order_needs_trade_through():
    # BUY limit at 98 (below the 100 open): a low of 98 is a touch, not a fill; 97 fills
    kw = dict(entry=98, stop=93, target=108, trigger=True, hold_days=3, opens=[100, 100, 100])
    assert _walk([101, 101, 101], [98, 98, 98], **kw)[0] == "NOT_TRIGGERED"
    status, day, price, _ = _walk([101, 109, 101], [97, 98, 98], **kw)
    assert status == "TARGET_HIT" and day == 1 and price == 108


def test_trigger_not_reached():
    status, *_ = _walk([99], [96], trigger=True, hold_days=1)
    assert status == "NOT_TRIGGERED"


def test_live_auto_disable():  # Covers AE5
    con = db.connect(":memory:")
    con.execute("INSERT INTO setup_stats (setup, horizon, trades, enabled) VALUES ('volume_breakout-old-str1','swing',100,1)")
    for i in range(30):
        status, r = ("TARGET_HIT", 2.0) if i < 6 else ("SL_HIT", -1.0)
        con.execute("INSERT INTO recommendations (setup, symbol, status, result_r) VALUES ('volume_breakout-old-str1','X',?,?)",
                    (status, r))
    setups.update_live_stats(con)
    row = con.execute("SELECT enabled, disabled_reason FROM setup_stats").fetchone()
    assert row["enabled"] == 0 and "live hit rate 20%" in row["disabled_reason"]


def test_backtest_produces_stats():
    from stockkk import indicators
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 800)))
    idx = pd.date_range("2023-01-01", periods=800, freq="B")
    df = pd.DataFrame({"open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes,
                       "volume": rng.integers(1000, 3000, 800).astype(float)}, index=idx)
    frames = {"X": indicators.add_all(df)}
    res = setups.backtest_setup(setups.BY_NAME["ema20_pullback-old-str1"], frames)
    st = setups.summarize(res)
    assert st["trades"] > 0 and 0 <= st["hit_rate"] <= 1


def test_no_target_and_exit_rule():
    # no fixed target: exits on the rule bar's close, net of a 0.2% cost on a 5-point risk (0.04R)
    status, day, price, r = _walk([103, 104, 105], [99, 100, 101], closes=[102, 103, 104], target=None,
                                  exit_rule=[False, True, False], cost_pct=0.002)
    assert status == "EXIT_RULE" and day == 1 and price == 103 and abs(r - (0.6 - 0.04)) < 1e-9


def test_backtest_gate_needs_both_windows(monkeypatch):
    """A setup profitable only in the early years is NOT enabled."""
    import numpy as np
    import pandas as pd
    from stockkk import config, indicators
    monkeypatch.setattr(config, "MIN_BACKTEST_TRADES", 5)
    monkeypatch.setattr(config, "MIN_OOS_TRADES", 5)
    idx = pd.date_range("2020-01-01", periods=1500, freq="B")
    up = np.linspace(100, 300, 1000)
    down = np.linspace(300, 150, 500)
    c = np.concatenate([up, down])
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6}, index=idx)
    frame = indicators.add_all(df)
    frame["breadth"], frame["breadth_sma"], frame["rs_rank"] = 0.6, 0.5, 0.95
    every10 = pd.Series(np.arange(len(frame)) % 10 == 0, index=frame.index)
    s = setups.Setup("t", "swing", "", lambda d: every10, lambda r: setups._trade("BUY", r.close, r.close - 3 * r.atr, None, 10))
    monkeypatch.setattr(setups, "SETUPS", [s])
    con = db.connect(":memory:")
    rows = setups.run_backtest(con, {"X": frame})
    st = con.execute("SELECT * FROM setup_stats").fetchone()
    assert st["is_avg_r"] > 0 and st["oos_avg_r"] < 0 and st["enabled"] == 0 and "hold-out" in st["disabled_reason"]
