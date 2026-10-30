"""Technical indicators on daily bars. Plain pandas, no TA library.

VWAP needs intraday bars, which free delayed data does not give, so it is not computed.
"""
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn)


def add_all(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, l = d["close"], d["high"], d["low"]
    for n in (20, 50, 200):
        d[f"ema{n}"] = ema(c, n)
    d["rsi"] = rsi(c)
    d["macd"] = ema(c, 12) - ema(c, 26)
    d["macd_signal"] = d["macd"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = d["macd"] - d["macd_signal"]
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    d["vol20"] = d["volume"].rolling(20).mean().shift(1)
    # Support / resistance: prior 20-day low / high, plus classic floor pivots for the next session
    d["resistance"] = h.rolling(20).max().shift(1)
    d["support"] = l.rolling(20).min().shift(1)
    d["high52"] = h.rolling(250, min_periods=200).max()
    d["low52"] = l.rolling(250, min_periods=200).min()
    pivot = (h + l + c) / 3
    d["pivot"], d["r1"], d["s1"] = pivot, 2 * pivot - l, 2 * pivot - h
    rng = h - l
    d["nr7"] = rng == rng.rolling(7).min()
    d["ret1"] = c.pct_change()
    d["ret20"] = c.pct_change(20)
    return d


def snapshot(row: pd.Series) -> dict:
    """Latest indicator values for the AI prompt and the dashboard. NaN becomes None."""
    keys = ["close", "ema20", "ema50", "ema200", "rsi", "macd", "macd_signal", "macd_hist", "atr",
            "volume", "vol20", "support", "resistance", "high52", "low52", "pivot", "r1", "s1", "ret20"]
    out = {k: (None if pd.isna(row.get(k)) else round(float(row[k]), 2)) for k in keys}
    out["vwap"] = None  # needs intraday data
    return out
