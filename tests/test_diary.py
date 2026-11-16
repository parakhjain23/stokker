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
    d = diary.build(recs, prices).set_index("symbol")
    assert d.loc["WIN", "pnl_pct"] == 20 and d.loc["WIN", "pnl_rs"] == 2000 and d.loc["WIN", "days"] == 3
    assert d.loc["LOSS", "pnl_pct"] == -10
    assert round(d.loc["OPEN", "pnl_pct"], 6) == 5 and d.loc["OPEN", "days"] == 2 and d.loc["OPEN", "last_price"] == 105
    assert round(d.loc["SHORT", "pnl_pct"], 6) == 5  # a short gains when price falls
    assert d.loc["NEW", "state"] == "waiting" and d.loc["SKIP", "state"] == "not filled"
    s = diary.summary(d.reset_index())
    assert (s["closed"], s["open"], s["accuracy"], s["target_hit"], s["stop_hit"]) == (2, 2, 50, 1, 1)
    assert s["booked"] == 1000 and round(s["running"], 6) == 1000 and s["invested"] == 40_000
