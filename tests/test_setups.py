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


def test_sell_target():
    status, _, _, r = _walk([101], [89], direction="SELL", entry=100, stop=105, target=90, hold_days=1, trigger=True)
    assert status == "TARGET_HIT" and r == 2


def test_trigger_not_reached():
    status, *_ = _walk([99], [96], trigger=True, hold_days=1)
    assert status == "NOT_TRIGGERED"


def test_live_auto_disable():  # Covers AE5
    con = db.connect(":memory:")
    con.execute("INSERT INTO setup_stats (setup, horizon, trades, enabled) VALUES ('volume_breakout','swing',100,1)")
    for i in range(30):
        status, r = ("TARGET_HIT", 2.0) if i < 6 else ("SL_HIT", -1.0)
        con.execute("INSERT INTO recommendations (setup, symbol, status, result_r) VALUES ('volume_breakout','X',?,?)",
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
    res = setups.backtest_setup(setups.BY_NAME["ema20_pullback"], frames)
    st = setups.summarize(res)
    assert st["trades"] > 0 and 0 <= st["hit_rate"] <= 1
