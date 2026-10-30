"""Coded trade setups, the backtest, and live grading.

One function, `walk`, decides how a trade ended. Backtests and live grading both use it,
so backtest stats and live results are measured the same way.
"""
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from stockkk import config, db


@dataclass(frozen=True)
class Setup:
    name: str
    horizon: str
    description: str
    signal: Callable[[pd.DataFrame], pd.Series]   # bool per bar (on indicator frame)
    levels: Callable[[pd.Series], dict]           # bar -> direction, entry, stop, target, hold_days, trigger


def _trade(direction, entry, stop, rr, hold, trigger=False):
    risk = abs(entry - stop)
    target = entry + rr * risk if direction == "BUY" else entry - rr * risk
    return {"direction": direction, "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(target, 2), "hold_days": hold, "trigger": trigger}


def _nr7_levels(r):
    # Next-session plan: buy above today's high in an uptrend, sell below today's low in a downtrend.
    if r.close > r.ema50:
        return _trade("BUY", r.high, r.low, 2.0, 1, trigger=True)
    return _trade("SELL", r.low, r.high, 2.0, 1, trigger=True)


SETUPS = [
    Setup("volume_breakout", "swing",
          "Close above 20-day high on 1.5x average volume, above 50 EMA",
          lambda d: (d.close > d.resistance) & (d.volume > 1.5 * d.vol20) & (d.close > d.ema50),
          lambda r: _trade("BUY", r.close, r.close - 1.5 * r.atr, 2.0, 15)),
    Setup("ema20_pullback", "swing",
          "Uptrend (close > 50 EMA > 200 EMA), dip to 20 EMA and close back above it, RSI 40-60",
          lambda d: (d.close > d.ema50) & (d.ema50 > d.ema200) & (d.low <= d.ema20 * 1.01)
          & (d.close > d.ema20) & d.rsi.between(40, 60),
          lambda r: _trade("BUY", r.close, min(r.low, r.ema20) - 0.5 * r.atr, 2.0, 10)),
    Setup("rsi_reversal", "swing",
          "RSI crosses back above 30 while price holds above 200 EMA",
          lambda d: (d.rsi > 30) & (d.rsi.shift(1) <= 30) & (d.close > d.ema200),
          lambda r: _trade("BUY", r.close, min(r.low, r.support) - 0.5 * r.atr, 2.0, 10)),
    Setup("macd_momentum", "swing",
          "MACD crosses above signal below zero line, close above 20 EMA, volume above average",
          lambda d: (d.macd_hist > 0) & (d.macd_hist.shift(1) <= 0) & (d.macd < 0)
          & (d.close > d.ema20) & (d.volume > d.vol20),
          lambda r: _trade("BUY", r.close, r.close - 1.5 * r.atr, 2.0, 15)),
    Setup("nr7_breakout", "intraday",
          "Narrowest range of 7 days: trade the break of today's range next session, with the 50 EMA trend",
          lambda d: d.nr7 & d.ema50.notna() & (d.volume > 0.5 * d.vol20),
          _nr7_levels),
    Setup("high52_momentum", "longterm",
          "Within 2% of 52-week high, 50 EMA above 200 EMA (fundamental filter applied live)",
          lambda d: (d.close >= 0.98 * d.high52) & (d.ema50 > d.ema200),
          lambda r: _trade("BUY", r.close, r.close - 4 * r.atr, 2.0, 120)),
]
BY_NAME = {s.name: s for s in SETUPS}


def walk(o, h, l, c, dates, direction, entry, stop, target, hold_days, trigger=False):
    """How did a trade end? Bars start the session AFTER the signal.

    Returns (status, date, exit_price, result_r), or None while the trade is still open.
    If stop and target fall in the same bar we assume the stop hit first (conservative).
    Gaps through a level fill at the open.
    """
    n = min(hold_days, len(c))
    if n == 0:
        return None
    buy = direction == "BUY"
    sign, risk = (1 if buy else -1), abs(entry - stop)
    if trigger and not (h[0] >= entry if buy else l[0] <= entry):
        return ("NOT_TRIGGERED", dates[0], None, 0.0)
    o, h, l, c = o[:n], h[:n], l[:n], c[:n]
    stop_hit = (l <= stop) if buy else (h >= stop)
    tgt_hit = (h >= target) if buy else (l <= target)
    si = int(np.argmax(stop_hit)) if stop_hit.any() else n
    ti = int(np.argmax(tgt_hit)) if tgt_hit.any() else n
    entered_intrabar = trigger  # a triggered entry happens mid-bar on day 0, so day-0 open is not a fill
    if si < n and si <= ti:
        fill = stop if (entered_intrabar and si == 0) else (min(o[si], stop) if buy else max(o[si], stop))
        return ("SL_HIT", dates[si], float(fill), sign * (fill - entry) / risk)
    if ti < n:
        fill = target if (entered_intrabar and ti == 0) else (max(o[ti], target) if buy else min(o[ti], target))
        return ("TARGET_HIT", dates[ti], float(fill), sign * (fill - entry) / risk)
    if n == hold_days:
        return ("EXPIRED", dates[n - 1], float(c[n - 1]), sign * (c[n - 1] - entry) / risk)
    return None


def valid_levels(lv: dict) -> bool:
    vals = [lv["entry"], lv["stop"], lv["target"]]
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
        o, h, l, c, dates = _arrays(d)
        free_from = 0
        for i in np.flatnonzero(sig):
            if i < free_from or i + 1 >= len(d):
                continue
            lv = setup.levels(d.iloc[i])
            if not valid_levels(lv):
                continue
            res = walk(o[i + 1:], h[i + 1:], l[i + 1:], c[i + 1:], dates[i + 1:], **lv)
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
    hits = sum(1 for x in results if x[2] == "TARGET_HIT")
    equity = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.maximum(equity, 0)) - equity).max())
    return {"trades": len(r), "hit_rate": hits / len(r), "avg_r": float(r.mean()), "max_dd_r": dd}


def run_backtest(con, frames: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    for s in SETUPS:
        st = summarize(backtest_setup(s, frames))
        enabled = st["trades"] >= config.MIN_BACKTEST_TRADES and (st["avg_r"] or 0) >= config.MIN_BACKTEST_AVG_R
        reason = None if enabled else ("too few backtest trades" if st["trades"] < config.MIN_BACKTEST_TRADES
                                       else f"backtest edge {st['avg_r']:+.3f}R below {config.MIN_BACKTEST_AVG_R}R")
        con.execute(
            """INSERT INTO setup_stats (setup, horizon, trades, hit_rate, avg_r, max_dd_r, enabled, disabled_reason, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(setup) DO UPDATE SET trades=excluded.trades, hit_rate=excluded.hit_rate,
                 avg_r=excluded.avg_r, max_dd_r=excluded.max_dd_r, enabled=excluded.enabled,
                 disabled_reason=excluded.disabled_reason, updated_at=excluded.updated_at""",
            (s.name, s.horizon, st["trades"], st["hit_rate"], st["avg_r"], st["max_dd_r"], int(enabled), reason, db.now()))
        rows.append({"setup": s.name, **st, "enabled": enabled})
    con.commit()
    update_live_stats(con)  # a live auto-disable must survive a weekly backtest refresh
    return rows


def grade_open(con, prices: dict[str, pd.DataFrame]) -> int:
    """Close OPEN recommendations whose target, stop, trigger window or hold period is resolved."""
    n = 0
    for rec in con.execute("SELECT * FROM recommendations WHERE status='OPEN'").fetchall():
        d = prices.get(rec["symbol"])
        if d is None:
            continue
        after = d[d.index > pd.Timestamp(rec["data_as_of"])]
        res = walk(*_arrays(after), rec["direction"], rec["entry"], rec["stop"], rec["target"],
                   rec["hold_days"], bool(rec["trigger"]))
        if res:
            status, end, price, r = res
            con.execute("UPDATE recommendations SET status=?, closed_on=?, exit_price=?, result_r=? WHERE id=?",
                        (status, str(pd.Timestamp(end).date()), price, r, rec["id"]))
            n += 1
    con.commit()
    return n


def update_live_stats(con) -> None:
    """Live hit rate per setup; auto-disable a setup that underperforms over enough calls (R16)."""
    for s in SETUPS:
        rows = con.execute("SELECT status, result_r FROM recommendations WHERE setup=? AND status IN "
                           "('TARGET_HIT','SL_HIT','EXPIRED')", (s.name,)).fetchall()
        if not rows:
            continue
        n = len(rows)
        hit = sum(r["status"] == "TARGET_HIT" for r in rows) / n
        avg = sum(r["result_r"] for r in rows) / n
        con.execute("UPDATE setup_stats SET live_trades=?, live_hit_rate=?, live_avg_r=? WHERE setup=?",
                    (n, hit, avg, s.name))
        if n >= config.MIN_LIVE_TRADES and hit < config.MIN_LIVE_HIT_RATE:
            con.execute("UPDATE setup_stats SET enabled=0, disabled_reason=? WHERE setup=?",
                        (f"live hit rate {hit:.0%} below {config.MIN_LIVE_HIT_RATE:.0%} over {n} calls", s.name))
    con.commit()


def enabled_stats(con) -> dict[str, dict]:
    return {r["setup"]: dict(r) for r in con.execute("SELECT * FROM setup_stats WHERE enabled=1")}
