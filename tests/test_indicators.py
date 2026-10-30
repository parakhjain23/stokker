import numpy as np
import pandas as pd

from stockkk import indicators as ind


def test_rsi_hand_computed():
    r = ind.rsi(pd.Series([1.0, 2, 1, 2]), n=2)
    assert np.isnan(r[1]) and r[2] == 50 and r[3] == 75


def test_rsi_all_up_is_100():
    assert ind.rsi(pd.Series(np.arange(1, 40, dtype=float))).iloc[-1] == 100


def _bars(closes):
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000.0})


def test_short_series_gives_nan_not_error():
    d = ind.add_all(_bars(range(100, 150)))
    assert d["ema200"].isna().all() and not np.isnan(d["ema20"].iloc[-1])


def test_macd_crossover_detected():
    closes = list(np.linspace(200, 100, 60)) + list(np.linspace(100, 160, 30))
    d = ind.add_all(_bars(closes))
    cross = (d["macd_hist"] > 0) & (d["macd_hist"].shift(1) <= 0)
    assert cross.iloc[60:].any()


def test_snapshot_has_vwap_unavailable():
    d = ind.add_all(_bars(range(100, 130)))
    snap = ind.snapshot(d.iloc[-1])
    assert snap["vwap"] is None and snap["ema200"] is None and snap["close"] == 129
