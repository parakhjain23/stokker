"""Paper-trading diary: every published call with its profit or loss so far, in pretend money."""
import pandas as pd

from stockkk import config

DONE = ("TARGET_HIT", "SL_HIT", "EXPIRED", "EXIT_RULE")


def build(recs: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """recs: recommendations rows (no NO_TRADE). prices: symbol, date, close for those symbols.
    Adds: state (open / closed / not filled / waiting), last_price, days, pnl_pct, pnl_rs, per100, won.
    Closed trades use the graded result (after costs); open trades are valued at the latest close.
    ponytail: every trade gets the same pretend amount, fractional shares; add real position sizing if needed."""
    out = recs.copy()
    sign = out.direction.map({"BUY": 1, "SELL": -1})
    risk_pct = (out.entry - out.stop).abs() / out.entry * 100
    by_symbol = {s: g.sort_values("date") for s, g in prices.groupby("symbol")}
    none = prices.iloc[:0]
    bars = [g[g.date > d] if st == "OPEN" and (g := by_symbol.get(s)) is not None else none
            for s, d, st in zip(out.symbol, out.data_as_of, out.status)]  # only open trades need current prices
    last = pd.Series([b.close.iloc[-1] if len(b) else None for b in bars], index=out.index, dtype=float)
    n_bars = pd.Series([len(b) for b in bars], index=out.index)
    closed = out.status.isin(DONE)
    out["state"] = "open"
    out.loc[closed, "state"] = "closed"
    out.loc[out.status == "NOT_TRIGGERED", "state"] = "not filled"
    out.loc[(out.status == "OPEN") & (n_bars == 0), "state"] = "waiting"
    out["last_price"] = out.exit_price.where(closed, last)
    out["pnl_pct"] = (out.result_r * risk_pct).where(closed, sign * (last / out.entry - 1) * 100)
    out.loc[out.state.isin(["not filled", "waiting"]), "pnl_pct"] = 0.0
    out["pnl_rs"] = out.pnl_pct / 100 * config.PAPER_PER_TRADE
    out["per100"] = out.pnl_pct / risk_pct * 100
    out["days"] = (pd.to_datetime(out.closed_on) - pd.to_datetime(out.data_as_of)).dt.days.where(closed, n_bars)
    out["won"] = (out.pnl_pct > 0).where(out.state.isin(["closed", "open"]))
    return out


def summary(d: pd.DataFrame) -> dict:
    c, o = d[d.state == "closed"], d[d.state == "open"]
    wins, losses = c[c.pnl_pct > 0], c[c.pnl_pct <= 0]
    n = len(c)
    return {"calls": len(d), "open": len(o), "closed": n, "waiting": int((d.state == "waiting").sum()),
            "not_filled": int((d.state == "not filled").sum()),
            "accuracy": len(wins) / n * 100 if n else None,
            "target_hit": int((c.status == "TARGET_HIT").sum()), "stop_hit": int((c.status == "SL_HIT").sum()),
            "other_exit": int(c.status.isin(["EXPIRED", "EXIT_RULE"]).sum()),
            "booked": c.pnl_rs.sum(), "running": o.pnl_rs.sum(), "total": c.pnl_rs.sum() + o.pnl_rs.sum(),
            "invested": (n + len(o)) * config.PAPER_PER_TRADE,
            "avg_win": wins.pnl_pct.mean() if len(wins) else None,
            "avg_loss": losses.pnl_pct.mean() if len(losses) else None,
            "best": c.pnl_pct.max() if n else None, "worst": c.pnl_pct.min() if n else None,
            "avg_days": c.days.mean() if n else None}
