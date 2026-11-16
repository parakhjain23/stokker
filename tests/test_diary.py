import pandas as pd

from stockkk import diary


def test_diary_values_open_closed_and_unfilled():
    base = dict(direction="BUY", entry=100.0, stop=90.0, data_as_of="2026-11-02", closed_on=None, exit_price=None, result_r=None)
    recs = pd.DataFrame([
        dict(base, symbol="WIN", status="TARGET_HIT", closed_on="2026-11-05", exit_price=120.0, result_r=2.0),
        dict(base, symbol="LOSS", status="SL_HIT", closed_on="2026-11-04", exit_price=90.0, result_r=-1.0),
        dict(base, symbol="OPEN", status="OPEN"),
        dict(base, symbol="SHORT", status="OPEN", direction="SELL", stop=110.0),
        dict(base, symbol="NEW", status="OPEN", data_as_of="2026-11-06"),
        dict(base, symbol="SKIP", status="NOT_TRIGGERED", closed_on="2026-11-03", result_r=0.0),
    ])
    prices = pd.DataFrame([("OPEN", "2026-11-02", 100.0), ("OPEN", "2026-11-03", 103.0), ("OPEN", "2026-11-04", 105.0),
                           ("SHORT", "2026-11-03", 95.0), ("NEW", "2026-11-06", 100.0)], columns=["symbol", "date", "close"])
    nifty = pd.DataFrame([("2026-11-02", 1000.0), ("2026-11-04", 1020.0), ("2026-11-05", 1050.0), ("2026-11-06", 1100.0)],
                         columns=["date", "close"])
    recs["horizon"], recs["id"] = "swing", range(len(recs))
    d = diary.build(recs, prices, nifty).set_index("symbol")
    assert round(d.loc["WIN", "nifty_pct"], 6) == 5 and round(d.loc["WIN", "beat_rs"], 6) == 1500  # +20% vs Nifty +5%
    assert round(d.loc["OPEN", "nifty_pct"], 6) == 10 and d.loc["SKIP", "nifty_pct"] == 0  # open: Nifty till its last day
    assert d.loc["WIN", "pnl_pct"] == 20 and d.loc["WIN", "pnl_rs"] == 2000 and d.loc["WIN", "days"] == 3
    assert d.loc["LOSS", "pnl_pct"] == -10
    assert round(d.loc["OPEN", "pnl_pct"], 6) == 5 and d.loc["OPEN", "days"] == 2 and d.loc["OPEN", "last_price"] == 105
    assert round(d.loc["SHORT", "pnl_pct"], 6) == 5  # a short gains when price falls
    assert d.loc["NEW", "state"] == "waiting" and d.loc["SKIP", "state"] == "not filled"
    s = diary.summary(d.reset_index())
    assert (s["closed"], s["open"], s["accuracy"], s["target_hit"], s["stop_hit"]) == (2, 2, 50, 1, 1)
    assert s["booked"] == 1000 and round(s["running"], 6) == 1000 and s["invested"] == 40_000
    assert (s["open_up"], s["open_down"], s["won"], s["lost"]) == (2, 0, 1, 1)
    assert s["open_money"] == 20_000 and round(s["open_value"], 6) == 21_000 and s["lost_rs"] == -1000
    assert round(s["nifty"], 6) == 500 + 200 + 1000 + 1000 and round(s["beat"], 6) == 2000 - 2700


def test_repeat_suggestions_count_once():
    r = pd.DataFrame([
        dict(id=1, symbol="A", horizon="swing", data_as_of="2026-11-02", closed_on="2026-11-10"),
        dict(id=2, symbol="A", horizon="swing", data_as_of="2026-11-03", closed_on="2026-11-11"),  # A still open: repeat
        dict(id=3, symbol="A", horizon="longterm", data_as_of="2026-11-03", closed_on=None),       # other horizon: kept
        dict(id=4, symbol="A", horizon="swing", data_as_of="2026-11-10", closed_on=None),          # first one closed: new
        dict(id=5, symbol="A", horizon="swing", data_as_of="2026-11-12", closed_on=None),          # id 4 still open: repeat
        dict(id=6, symbol="B", horizon="swing", data_as_of="2026-11-03", closed_on=None),
    ])
    assert list(diary.drop_repeats(r).id) == [1, 3, 4, 6]
