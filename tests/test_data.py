import pandas as pd

from stockkk import data, db


def _df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes)).date
    return pd.DataFrame({"open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "volume": 1000}, index=idx)


def test_clean_keeps_good_rows():
    df, reason = data.clean(_df([100, 101, 102]))
    assert len(df) == 3 and reason is None


def test_clean_drops_big_gap_when_index_calm():
    df = _df([100, 101, 131])  # +30% with a flat index
    index_ret = pd.Series(0.001, index=df.index)
    out, reason = data.clean(df, index_ret)
    assert len(out) == 2 and "dropped 1" in reason


def test_clean_keeps_big_gap_when_index_crashes():
    df = _df([100, 101, 75])
    index_ret = pd.Series([0, 0, -0.10], index=df.index)
    out, _ = data.clean(df, index_ret)
    assert len(out) == 3


def test_clean_drops_impossible_rows():
    df = _df([100, 0, 102])
    out, _ = data.clean(df)
    assert len(out) == 2


def test_empty_fetch_marks_unavailable(monkeypatch):  # Covers AE1
    con = db.connect(":memory:")
    monkeypatch.setattr(data, "_download", lambda t, p: pd.DataFrame())
    monkeypatch.setattr(data, "_fallback_nse", lambda s, p: (_ for _ in ()).throw(RuntimeError("down")))
    res = data.fetch_prices(con, ["FOO"], "1mo")
    assert res["failed"] == ["FOO"]
    row = con.execute("SELECT ok, reason FROM data_status WHERE symbol='FOO'").fetchone()
    assert row["ok"] == 0


def test_fallback_used_when_yahoo_empty(monkeypatch):
    con = db.connect(":memory:")
    monkeypatch.setattr(data, "_download", lambda t, p: pd.DataFrame())
    monkeypatch.setattr(data, "_fallback_nse", lambda s, p: _df([100, 101]))
    data.fetch_prices(con, ["FOO"], "1mo")
    src = con.execute("SELECT DISTINCT source FROM prices WHERE symbol='FOO'").fetchone()[0]
    assert src.startswith("nse")
