"""Coded trade setups, the backtest with a hold-out window, and live grading.

One function, `walk`, decides how a trade ended. Backtests and live grading both use it,
so backtest stats and live results are measured the same way, net of costs.

Generations:
  v2       regime-gated trend following and mean reversion (research: docs/research.md)
  old-str1 the original chart patterns, kept for watching, never proven
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

import numpy as np
import pandas as pd

from stockkk import config, db

LIMIT_MARGIN = 0.003  # a resting limit order fills only if price trades 0.3% through it
FAR = None            # no fixed target: exit by rule or time


@dataclass(frozen=True)
class Setup:
    name: str
    horizon: str
    description: str
    signal: Callable[[pd.DataFrame], pd.Series]   # bool per bar (on indicator frame)
    levels: Callable[[pd.Series], dict]           # bar -> direction, entry, stop, target, hold_days, trigger
    exit_rule: Callable[[pd.DataFrame], pd.Series] | None = None  # bool per bar: exit at that close
    exit_note: str = ""                           # shown with the recommendation
    cost_pct: float = 0.002                       # round-trip cost as a fraction of entry
    generation: str = "v2"


def _trade(direction, entry, stop, rr, hold, trigger=False):
    risk = abs(entry - stop)
    if rr is None:
        target = None
    else:
        target = entry + rr * risk if direction == "BUY" else entry - rr * risk
    return {"direction": direction, "entry": round(entry, 2), "stop": round(stop, 2),
            "target": None if target is None else round(target, 2), "hold_days": hold, "trigger": trigger}


def _nr7_levels(r):
    if r.close > r.ema50:
        return _trade("BUY", r.high, r.low, 2.0, 1, trigger=True)
    return _trade("SELL", r.low, r.high, 2.0, 1, trigger=True)


# Regime gate for trend strategies: most stocks in uptrends, and that share rising.
def risk_on(d):
    return (d.breadth > config.BREADTH_MIN) & (d.breadth > d.breadth_sma)


SETUPS = [
    # ---- v2: regime-gated relative strength (validated 2018-2026, every 2-year window positive) ----
    Setup("rs_leader_swing", "swing",
          "Top 10% 3-month strength vs Nifty, above 50 EMA, RSI < 70, market breadth > 40% and rising. "
          "Hold about 4 weeks, stop 3 ATR.",
          lambda d: (d.rs_rank > 0.9) & (d.close > d.ema50) & (d.rsi < 70) & risk_on(d),
          lambda r: _trade("BUY", r.close, r.close - 3 * r.atr, FAR, 21),
          exit_note="Time exit: sell at the close of the 21st trading day (or at the stop)."),
    Setup("rs_leader_position", "longterm",
          "Same leaders, held about 2 months, stop 3 ATR.",
          lambda d: (d.rs_rank > 0.9) & (d.close > d.ema50) & (d.rsi < 70) & risk_on(d),
          lambda r: _trade("BUY", r.close, r.close - 3 * r.atr, FAR, 42),
          exit_note="Time exit: sell at the close of the 42nd trading day (or at the stop)."),
    Setup("high52_trend", "longterm",
          "Within 2% of the 52-week high, 50 EMA above 200 EMA, RSI < 75, breadth > 40% and rising. "
          "Ride the trend until a close below the 50 EMA, up to 6 months.",
          lambda d: (d.close >= 0.98 * d.high52) & (d.ema50 > d.ema200) & (d.rsi < 75) & risk_on(d),
          lambda r: _trade("BUY", r.close, r.close - 3 * r.atr, FAR, 126),
          exit_rule=lambda d: d.close < d.ema50,
          exit_note="Exit on the first close below the 50-day EMA, or after 6 months."),
    Setup("oversold_bounce", "swing",
          "2-day RSI below 5 in an uptrend (above 50 EMA, 50 EMA above 200 EMA). Target 1 ATR, stop 2 ATR, 5 days. "
          "High win rate, small edge.",
          lambda d: (d.rsi2 < 5) & (d.close > d.ema50) & (d.ema50 > d.ema200),
          lambda r: _trade("BUY", r.close, r.close - 2 * r.atr, 0.5, 5)),
    Setup("leader_dip_intraday", "intraday",
          "Top 10% strength stock, 2-day RSI < 30: limit buy 0.5 ATR below the last close for the next session, "
          "exit at the close. Cannot be proven with daily data; shown for watching only.",
          lambda d: (d.rs_rank > 0.9) & (d.rsi2 < 30),
          lambda r: _trade("BUY", r.close - 0.5 * r.atr, r.close - 1.5 * r.atr, 1.0, 1, True),
          exit_note="Square off at the close of the session.", cost_pct=0.0005),
    # ---- old-str1: original patterns, kept for watching ----
    Setup("volume_breakout-old-str1", "swing",
          "Close above 20-day high on 1.5x average volume, above 50 EMA",
          lambda d: (d.close > d.resistance) & (d.volume > 1.5 * d.vol20) & (d.close > d.ema50),
          lambda r: _trade("BUY", r.close, r.close - 1.5 * r.atr, 2.0, 15), generation="old-str1"),
    Setup("ema20_pullback-old-str1", "swing",
          "Uptrend (close > 50 EMA > 200 EMA), dip to 20 EMA and close back above it, RSI 40-60",
          lambda d: (d.close > d.ema50) & (d.ema50 > d.ema200) & (d.low <= d.ema20 * 1.01)
          & (d.close > d.ema20) & d.rsi.between(40, 60),
          lambda r: _trade("BUY", r.close, min(r.low, r.ema20) - 0.5 * r.atr, 2.0, 10), generation="old-str1"),
    Setup("rsi_reversal-old-str1", "swing",
          "RSI crosses back above 30 while price holds above 200 EMA",
          lambda d: (d.rsi > 30) & (d.rsi.shift(1) <= 30) & (d.close > d.ema200),
          lambda r: _trade("BUY", r.close, min(r.low, r.support) - 0.5 * r.atr, 2.0, 10), generation="old-str1"),
    Setup("macd_momentum-old-str1", "swing",
          "MACD crosses above signal below zero line, close above 20 EMA, volume above average",
          lambda d: (d.macd_hist > 0) & (d.macd_hist.shift(1) <= 0) & (d.macd < 0)
          & (d.close > d.ema20) & (d.volume > d.vol20),
          lambda r: _trade("BUY", r.close, r.close - 1.5 * r.atr, 2.0, 15), generation="old-str1"),
    Setup("nr7_breakout-old-str1", "intraday",
          "Narrowest range of 7 days: trade the break of today's range next session, with the 50 EMA trend",
          lambda d: d.nr7 & d.ema50.notna() & (d.volume > 0.5 * d.vol20),
          _nr7_levels, cost_pct=0.0005, generation="old-str1"),
    Setup("high52_momentum-old-str1", "longterm",
          "Within 2% of 52-week high, 50 EMA above 200 EMA, fixed 2:1 target",
          lambda d: (d.close >= 0.98 * d.high52) & (d.ema50 > d.ema200),
          lambda r: _trade("BUY", r.close, r.close - 4 * r.atr, 2.0, 120), generation="old-str1"),
]
BY_NAME = {s.name: s for s in SETUPS}


def walk(o, h, l, c, dates, direction, entry, stop, target, hold_days, trigger=False, exit_rule=None,
         cost_pct=0.0):
    """How did a trade end? Bars start the session AFTER the signal.

    Returns (status, date, exit_price, result_r), or None while the trade is still open.
    trigger=True means a pending order at `entry`: a BUY above the first open is a stop order
    (fills on a touch), a BUY below it is a limit order (fills only if price trades through by
    LIMIT_MARGIN); SELL is mirrored. On the entry day of a triggered order the target is never
    credited, because daily bars cannot say whether the high came before or after the fill.
    target=None means no fixed target. exit_rule: bool per bar, True exits at that close.
    If stop and target fall in the same bar we assume the stop hit first (conservative).
    Gaps through a level fill at the open. Costs (round trip, % of entry) are subtracted in R.
    """
    n = min(hold_days, len(c))
    if n == 0:
        return None
    buy = direction == "BUY"
    sign = 1 if buy else -1
    if trigger:
        above = entry > o[0]
        m = entry * LIMIT_MARGIN
        if buy:
            filled = (h[0] >= entry) if above else (l[0] <= entry - m)
            fill_in = max(o[0], entry) if above else min(o[0], entry)
        else:
            filled = (l[0] <= entry) if not above else (h[0] >= entry + m)
            fill_in = min(o[0], entry) if not above else max(o[0], entry)
        if not filled:
            return ("NOT_TRIGGERED", dates[0], None, 0.0)
        entry = float(fill_in)
    risk = abs(entry - stop)
    if risk <= 0:
        return ("NOT_TRIGGERED", dates[0], None, 0.0)
    cost_r = cost_pct * entry / risk
    o, h, l, c = o[:n], h[:n], l[:n], c[:n]
    stop_hit = (l <= stop) if buy else (h >= stop)
    if target is None:
        tgt_hit = np.zeros(n, dtype=bool)
    else:
        tgt_hit = ((h >= target) if buy else (l <= target)).copy()
        if trigger:
            tgt_hit[0] = False
    si = int(np.argmax(stop_hit)) if stop_hit.any() else n
    ti = int(np.argmax(tgt_hit)) if tgt_hit.any() else n
    ei = n
    if exit_rule is not None:
        ex = np.asarray(exit_rule[:n], dtype=bool)
        ei = int(np.argmax(ex)) if ex.any() else n
    r = lambda px: sign * (px - entry) / risk - cost_r
    if si < n and si <= ti and si <= ei:
        fill = stop if (trigger and si == 0) else (min(o[si], stop) if buy else max(o[si], stop))
        return ("SL_HIT", dates[si], float(fill), r(fill))
    if ti < n and ti <= ei:
        fill = max(o[ti], target) if buy else min(o[ti], target)
        return ("TARGET_HIT", dates[ti], float(fill), r(fill))
    if ei < n:
        return ("EXIT_RULE", dates[ei], float(c[ei]), r(c[ei]))
    if n == hold_days:
        return ("EXPIRED", dates[n - 1], float(c[n - 1]), r(c[n - 1]))
    return None


def valid_levels(lv: dict) -> bool:
    vals = [lv["entry"], lv["stop"]] + ([lv["target"]] if lv["target"] is not None else [])
    return all(np.isfinite(v) and v > 0 for v in vals) and abs(lv["entry"] - lv["stop"]) > 0


def _arrays(d):
    return (d["open"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy(),
            d.index.to_numpy())


def backtest_setup(setup: Setup, frames: dict[str, pd.DataFrame]) -> list[tuple]:
    """frames: symbol -> indicator frame. Returns [(date, result_r, status)] for closed trades.
    One open trade per symbol at a time, so overlapping signals are not double counted."""
    out = []
    for d in frames.values():
        sig = setup.signal(d).fillna(False).to_numpy()
        ex = setup.exit_rule(d).fillna(False).to_numpy() if setup.exit_rule else None
        o, h, l, c, dates = _arrays(d)
        free_from = 0
        for i in np.flatnonzero(sig):
            if i < free_from or i + 1 >= len(d):
                continue
            lv = setup.levels(d.iloc[i])
            if not valid_levels(lv):
                continue
            res = walk(o[i + 1:], h[i + 1:], l[i + 1:], c[i + 1:], dates[i + 1:], **lv,
                       exit_rule=None if ex is None else ex[i + 1:], cost_pct=setup.cost_pct)
            if res is None:
                break
            status, end, _, r = res
            if status != "NOT_TRIGGERED":
                out.append((dates[i], r, status))
            free_from = int(np.searchsorted(dates, end)) + 1
    return out


def summarize(results: list[tuple]) -> dict:
    if not results:
        return {"trades": 0, "hit_rate": None, "avg_r": None, "max_dd_r": None}
    results = sorted(results, key=lambda x: x[0])
    r = np.array([x[1] for x in results])
    equity = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.maximum(equity, 0)) - equity).max())
    return {"trades": len(r), "hit_rate": float((r > 0).mean()), "avg_r": float(r.mean()), "max_dd_r": dd}


def run_backtest(con, frames: dict[str, pd.DataFrame]) -> list[dict]:
    """Backtest every setup. A setup is enabled only if it is profitable net of costs in BOTH the
    in-sample years and the final hold-out window (config.OOS_YEARS), with enough trades in each."""
    last = max(d.index[-1] for d in frames.values())
    split = (last - timedelta(days=365 * config.OOS_YEARS)).to_datetime64()
    rows = []
    for s in SETUPS:
        res = backtest_setup(s, frames)
        full, ins, oos = summarize(res), summarize([x for x in res if x[0] < split]), summarize([x for x in res if x[0] >= split])
        ok_n = ins["trades"] >= config.MIN_BACKTEST_TRADES and oos["trades"] >= config.MIN_OOS_TRADES
        ok_edge = (ins["avg_r"] or -1) >= config.MIN_BACKTEST_AVG_R and (oos["avg_r"] or -1) >= config.MIN_BACKTEST_AVG_R
        enabled = ok_n and ok_edge
        reason = None if enabled else ("too few backtest trades" if not ok_n else
                                       f"edge in-sample {ins['avg_r']:+.3f}R, hold-out {oos['avg_r']:+.3f}R; "
                                       f"both must be >= {config.MIN_BACKTEST_AVG_R}R")
        con.execute(
            """INSERT INTO setup_stats (setup, horizon, generation, trades, hit_rate, avg_r, max_dd_r,
                 is_avg_r, oos_trades, oos_hit_rate, oos_avg_r, enabled, disabled_reason, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(setup) DO UPDATE SET horizon=excluded.horizon, generation=excluded.generation,
                 trades=excluded.trades, hit_rate=excluded.hit_rate, avg_r=excluded.avg_r, max_dd_r=excluded.max_dd_r,
                 is_avg_r=excluded.is_avg_r, oos_trades=excluded.oos_trades, oos_hit_rate=excluded.oos_hit_rate,
                 oos_avg_r=excluded.oos_avg_r, enabled=excluded.enabled, disabled_reason=excluded.disabled_reason,
                 updated_at=excluded.updated_at""",
            (s.name, s.horizon, s.generation, full["trades"], full["hit_rate"], full["avg_r"], full["max_dd_r"],
             ins["avg_r"], oos["trades"], oos["hit_rate"], oos["avg_r"], int(enabled), reason, db.now()))
        rows.append({"setup": s.name, **full, "oos_avg_r": oos["avg_r"], "enabled": enabled})
    con.commit()
    update_live_stats(con)  # a live auto-disable must survive a weekly backtest refresh
    return rows


def grade_open(con, prices: dict[str, pd.DataFrame]) -> int:
    """Close OPEN recommendations whose stop, target, exit rule, trigger window or hold period is resolved."""
    from stockkk import indicators
    n = 0
    by_name = {s.name: s for s in SETUPS}
    for rec in con.execute("SELECT * FROM recommendations WHERE status='OPEN'").fetchall():
        d = prices.get(rec["symbol"])
        setup = by_name.get(rec["setup"])
        if d is None or setup is None:
            continue
        frame = indicators.add_all(d)
        after = frame[frame.index > pd.Timestamp(rec["data_as_of"])]
        ex = setup.exit_rule(after).fillna(False).to_numpy() if setup.exit_rule else None
        res = walk(*_arrays(after), rec["direction"], rec["entry"], rec["stop"], rec["target"],
                   rec["hold_days"], bool(rec["trigger"]), exit_rule=ex, cost_pct=setup.cost_pct)
        if res:
            status, end, price, r = res
            con.execute("UPDATE recommendations SET status=?, closed_on=?, exit_price=?, result_r=? WHERE id=?",
                        (status, str(pd.Timestamp(end).date()), price, r, rec["id"]))
            n += 1
    con.commit()
    return n


CLOSED = "('TARGET_HIT','SL_HIT','EXPIRED','EXIT_RULE')"


def update_live_stats(con) -> None:
    """Live hit rate per setup; auto-disable a setup that underperforms over enough calls (R16)."""
    for s in SETUPS:
        rows = con.execute(f"SELECT status, result_r FROM recommendations WHERE setup=? AND status IN {CLOSED}",
                           (s.name,)).fetchall()
        if not rows:
            continue
        n = len(rows)
        hit = sum((r["result_r"] or 0) > 0 for r in rows) / n
        avg = sum(r["result_r"] for r in rows) / n
        con.execute("UPDATE setup_stats SET live_trades=?, live_hit_rate=?, live_avg_r=? WHERE setup=?",
                    (n, hit, avg, s.name))
        if n >= config.MIN_LIVE_TRADES and hit < config.MIN_LIVE_HIT_RATE:
            con.execute("UPDATE setup_stats SET enabled=0, disabled_reason=? WHERE setup=?",
                        (f"live hit rate {hit:.0%} below {config.MIN_LIVE_HIT_RATE:.0%} over {n} calls", s.name))
    con.commit()
