"""Daily research run: setups -> candidates -> Gemini -> recommendations or NO TRADE."""
import json
import logging

import pandas as pd

from stockkk import ai, config, data, db, indicators, news, setups

log = logging.getLogger(__name__)


def liquid(d: pd.DataFrame) -> bool:
    return len(d) >= 60 and (d["close"] * d["volume"]).tail(20).mean() >= config.MIN_TRADED_VALUE


def build_frames(prices: dict[str, pd.DataFrame], symbols) -> dict[str, pd.DataFrame]:
    """Indicator frames for liquid stocks only (thinly traded stocks are hard to trade and easy to move).
    ponytail: liquidity is judged on today's volume, also for the backtest; fine for a screen, not for research."""
    return {s: indicators.add_all(prices[s]) for s in symbols if s in prices and liquid(prices[s])}


def latest_date(frames: dict[str, pd.DataFrame]):
    return max(d.index[-1] for d in frames.values())


def _pct(a, b):
    return None if not b else round((a / b - 1) * 100, 2)


def market_overview(prices: dict, frames: dict, uni: pd.DataFrame) -> dict:
    idx = {}
    for sym, name in config.INDICES.items():
        d = prices.get(sym)
        if d is None or len(d) < 6:
            idx[name] = {"status": "unavailable"}
            continue
        c = d["close"]
        idx[name] = {"close": round(c.iloc[-1], 2), "chg_1d_pct": _pct(c.iloc[-1], c.iloc[-2]),
                     "chg_5d_pct": _pct(c.iloc[-1], c.iloc[-6]), "as_of": str(d.index[-1].date())}
    idx["GIFT Nifty"] = {"status": "unavailable (not in free data)"}
    as_of = latest_date(frames)
    last = pd.DataFrame([{"symbol": s, "ret1": d["ret1"].iloc[-1], "ret20": d["ret20"].iloc[-1]}
                         for s, d in frames.items() if d.index[-1] == as_of])
    last = last.merge(uni, on="symbol")
    sectors = (last.groupby("industry")[["ret1", "ret20"]].median() * 100).round(2)
    return {
        "as_of": str(as_of.date()), "indices": idx,
        "breadth": {"advancers": int((last["ret1"] > 0).sum()), "decliners": int((last["ret1"] < 0).sum())},
        "sectors": sectors.sort_values("ret20", ascending=False).reset_index().to_dict("records"),
    }


def _win_stats(st: dict) -> tuple[float, float]:
    """Backtest win probability and expectancy, blended with live results once there are enough."""
    p, r = st["hit_rate"], st["avg_r"]
    if (st.get("live_trades") or 0) >= config.BLEND_AFTER:
        p, r = (p + st["live_hit_rate"]) / 2, (r + st["live_avg_r"]) / 2
    return p, r


def find_candidates(frames: dict, uni: pd.DataFrame, stats: dict, as_of) -> dict[str, list[dict]]:
    """Every stock matching any backtested setup on the latest bar. Stale symbols are excluded (AE1)."""
    info = uni.drop_duplicates("symbol").set_index("symbol")
    sector_ret = {}
    for s, d in frames.items():
        if s in info.index:
            sector_ret.setdefault(info.at[s, "industry"], []).append(d["ret20"].iloc[-1])
    sector_ret = {k: pd.Series(v).median() for k, v in sector_ret.items()}
    out = {h: [] for h in config.HORIZONS}
    for setup in setups.SETUPS:
        st = stats.get(setup.name)
        if not st or st["hit_rate"] is None:
            continue
        p, r = _win_stats(st)
        for sym, d in frames.items():
            if sym not in info.index or d.index[-1] != as_of or not bool(setup.signal(d).iloc[-1]):
                continue
            row = d.iloc[-1]
            lv = setup.levels(row)
            if not setups.valid_levels(lv):
                continue
            rr = round(abs(lv["target"] - lv["entry"]) / abs(lv["entry"] - lv["stop"]), 2)
            out[setup.horizon].append({
                "symbol": sym, "name": info.at[sym, "name"], "industry": info.at[sym, "industry"],
                "setup": setup.name, "setup_rule": setup.description, "setup_proven": bool(st["enabled"]),
                **lv, "rr": rr,
                "entry_type": "stop order: only if price trades through entry next session" if lv["trigger"]
                              else "near last close",
                "backtest_win_prob": round(p, 3), "backtest_avg_r": round(r, 3), "backtest_trades": st["trades"],
                "indicators": indicators.snapshot(row),
                "sector_ret20_pct": round(sector_ret.get(info.at[sym, "industry"], float("nan")) * 100, 2),
            })
    return out


def enrich(con, horizon: str, cands: list[dict]) -> list[dict]:
    """Attach fundamentals and news. Long-term needs a profitable company."""
    kept = []
    for c in cands:
        f = data.fundamentals(con, c["symbol"])
        if horizon == "longterm" and not (f.get("pe") and f["pe"] > 0):
            continue  # loss-making or P/E unavailable
        c["fundamentals"] = {k: f.get(k) for k in ("pe", "roe", "debt_to_equity", "earnings_growth",
                                                    "revenue_growth", "market_cap", "sector")}
        news.fetch_symbol_news(con, c["symbol"], c["name"])
        c["news"] = [f"{n['published_at'][:10]} [{n['source']}] {n['title']}" for n in news.recent(con, c["symbol"])]
        kept.append(c)
    return kept


def _insert(con, table: str, rec: dict) -> None:
    con.execute(f"INSERT INTO {table} ({','.join(rec)}) VALUES ({','.join('?' * len(rec))})", tuple(rec.values()))


def no_trade(con, horizon: str, reason: str, as_of: str) -> None:
    _insert(con, "recommendations", {"created_at": db.now(), "horizon": horizon, "status": "NO_TRADE",
                                     "reasoning": reason, "data_as_of": as_of})
    con.commit()


def score(c: dict, a) -> tuple[float, float]:
    """Final win probability (%) and expected R after the AI adjustment."""
    adj = a.confidence_adj if a else 0
    win = min(max(c["backtest_win_prob"] * 100 + adj, 0), 100)
    return round(win, 1), round(c["backtest_avg_r"] + adj / 100 * (c["rr"] + 1), 2)


def publish(con, horizon: str, cands: list[dict], assessed: dict, as_of: str) -> int:
    """Rank every candidate (1 = highest win chance) and store the list. Publish as tracked calls
    only those that clear the quality bar; if none do, publish NO TRADE (R11, R12)."""
    rows = []
    for c in cands:
        a = assessed.get(c["symbol"])
        win, exp_r = score(c, a)
        ok = (c["setup_proven"] and a is not None and a.verdict == "TAKE"
              and c["rr"] >= config.MIN_RR[horizon] and exp_r >= config.MIN_EXPECTED_R)
        rows.append((c, a, win, exp_r, ok))
    rows.sort(key=lambda x: (x[2], x[3]), reverse=True)
    n = 0
    for rank, (c, a, win, exp_r, ok) in enumerate(rows, 1):
        common = {"created_at": db.now(), "horizon": horizon, "symbol": c["symbol"], "name": c["name"],
                  "direction": c["direction"], "entry": c["entry"], "stop": c["stop"], "target": c["target"],
                  "rr": c["rr"], "hold_days": c["hold_days"], "trigger": int(c["trigger"]), "setup": c["setup"],
                  "reasoning": a.reasoning if a else "Not assessed by AI.",
                  "invalidation": a.invalidation if a else None, "data_as_of": as_of}
        _insert(con, "candidates", {**common, "rank": rank, "setup_proven": int(c["setup_proven"]),
                                    "win_prob": win, "expected_r": exp_r,
                                    "ai_verdict": a.verdict if a else "NOT ASSESSED", "recommended": int(ok)})
        if ok:
            _insert(con, "recommendations", {**common, "confidence": win, "expected_r": exp_r,
                                             "technical": a.technical, "fundamental": a.fundamental, "news": a.news})
            n += 1
    con.commit()
    if n == 0:
        proven = any(c["setup_proven"] for c in cands)
        no_trade(con, horizon, f"{len(cands)} stocks matched a pattern, but none cleared the quality bar."
                 if proven else f"{len(cands)} stocks matched a pattern, but no pattern for this horizon has a "
                 "proven backtested edge, so nothing is recommended. See the ranked list.", as_of)
    return n


def run(con, prices: dict | None = None) -> dict:
    uni = data.universe()
    prices = prices or data.load_prices(con)
    frames = build_frames(prices, uni["symbol"])
    if not frames:
        raise RuntimeError("no price data; run the EOD fetch first")
    as_of = latest_date(frames)
    as_of_s = str(as_of.date())
    overview = market_overview(prices, frames, uni)
    db.set_meta(con, "overview", json.dumps(overview, default=str))
    market = {"as_of": overview["as_of"], "indices": overview["indices"], "breadth": overview["breadth"],
              "top_sectors": overview["sectors"][:3], "bottom_sectors": overview["sectors"][-3:]}
    stats = {r["setup"]: dict(r) for r in con.execute("SELECT * FROM setup_stats")}
    cands = find_candidates(frames, uni, stats, as_of)
    summary = {}
    for h in config.HORIZONS:
        if con.execute("SELECT 1 FROM recommendations WHERE horizon=? AND data_as_of=?", (h, as_of_s)).fetchone():
            summary[h] = "already published"
            continue
        if not cands[h]:
            no_trade(con, h, "No stock matched any pattern on the latest data.", as_of_s)
            summary[h] = "NO TRADE (no matches)"
            continue
        top = enrich(con, h, cands[h])
        if not top:
            no_trade(con, h, "No candidate passed the fundamental filter.", as_of_s)
            summary[h] = "NO TRADE"
            continue
        try:
            assessed = ai.assess(h, top, market)
        except ai.AIUnavailable as e:
            db.set_meta(con, f"ai_status_{h}", f"AI unavailable: {e}")
            summary[h] = "AI unavailable"
            continue  # nothing stored; next run retries
        db.set_meta(con, f"ai_status_{h}", "ok")
        n = publish(con, h, top, assessed, as_of_s)
        summary[h] = f"{len(top)} ranked, {n} recommended"
    return summary


def refresh_brief(con) -> None:
    overview, _ = db.get_meta(con, "overview")
    if not overview:
        return
    heads = [n["title"] for n in news.recent(con, None, days=2, limit=25)]
    try:
        db.set_meta(con, "brief", ai.market_brief(json.loads(overview), heads))
    except ai.AIUnavailable as e:
        log.warning("market brief skipped: %s", e)
