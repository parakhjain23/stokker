"""Daily research run: setups -> candidates -> Gemini -> recommendations or NO TRADE."""
import json
import logging

import pandas as pd

from stockkk import ai, config, data, db, indicators, news, setups

log = logging.getLogger(__name__)


def build_frames(prices: dict[str, pd.DataFrame], symbols) -> dict[str, pd.DataFrame]:
    return {s: indicators.add_all(prices[s]) for s in symbols if s in prices and len(prices[s]) >= 60}


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
    """Signals on the latest bar from enabled setups. Symbols without a bar for as_of are excluded (AE1)."""
    info = uni.set_index("symbol")
    sector_ret = {}
    for s, d in frames.items():
        if s in info.index:
            sector_ret.setdefault(info.at[s, "industry"], []).append(d["ret20"].iloc[-1])
    sector_ret = {k: pd.Series(v).median() for k, v in sector_ret.items()}
    out = {h: [] for h in config.HORIZONS}
    for setup in setups.SETUPS:
        st = stats.get(setup.name)
        if not st:
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
                "setup": setup.name, "setup_rule": setup.description, **lv, "rr": rr,
                "entry_type": "stop order: only if price trades through entry next session" if lv["trigger"]
                              else "near last close",
                "backtest_win_prob": round(p, 3), "backtest_avg_r": round(r, 3), "backtest_trades": st["trades"],
                "indicators": indicators.snapshot(row),
                "sector_ret20_pct": round(sector_ret.get(info.at[sym, "industry"], float("nan")) * 100, 2),
            })
    for h in out:  # best setups first, then strongest stocks
        out[h].sort(key=lambda c: (c["backtest_avg_r"], c["indicators"]["ret20"] or 0), reverse=True)
    return out


def enrich(con, horizon: str, cands: list[dict]) -> list[dict]:
    """Attach fundamentals and news to the top candidates. Long-term needs a profitable company."""
    kept = []
    for c in cands:
        if len(kept) >= config.MAX_CANDIDATES:
            break
        f = data.fundamentals(con, c["symbol"])
        if horizon == "longterm" and not (f.get("pe") and f["pe"] > 0):
            continue  # loss-making or P/E unavailable
        c["fundamentals"] = {k: f.get(k) for k in ("pe", "roe", "debt_to_equity", "earnings_growth",
                                                    "revenue_growth", "market_cap", "sector")}
        news.fetch_symbol_news(con, c["symbol"], c["name"])
        c["news"] = [f"{n['published_at'][:10]} [{n['source']}] {n['title']}" for n in news.recent(con, c["symbol"])]
        kept.append(c)
    return kept


def _insert(con, rec: dict) -> None:
    cols = ",".join(rec)
    con.execute(f"INSERT INTO recommendations ({cols}) VALUES ({','.join('?' * len(rec))})", tuple(rec.values()))


def publish(con, horizon: str, cands: list[dict], picks: list, ai_reason: str, as_of: str) -> int:
    """Store picks that clear the thresholds, or one NO TRADE row (R11, R12)."""
    by_sym = {c["symbol"]: c for c in cands}
    n = 0
    for pk in picks:
        c = by_sym[pk.symbol]
        win = min(max(c["backtest_win_prob"] * 100 + pk.confidence_adj, 0), 100)
        exp_r = c["backtest_avg_r"] + pk.confidence_adj / 100 * (c["rr"] + 1)
        if c["rr"] < config.MIN_RR[horizon] or exp_r < config.MIN_EXPECTED_R:
            continue
        _insert(con, {
            "created_at": db.now(), "horizon": horizon, "symbol": c["symbol"], "name": c["name"],
            "direction": c["direction"], "entry": c["entry"], "stop": c["stop"], "target": c["target"],
            "rr": c["rr"], "hold_days": c["hold_days"], "trigger": int(c["trigger"]),
            "confidence": round(win, 1), "expected_r": round(exp_r, 2), "setup": c["setup"],
            "reasoning": pk.reasoning, "technical": pk.technical, "fundamental": pk.fundamental,
            "news": pk.news, "invalidation": pk.invalidation, "data_as_of": as_of})
        n += 1
    if n == 0:
        reason = ai_reason or "No setup met the quality threshold (risk-reward and expected return)."
        _insert(con, {"created_at": db.now(), "horizon": horizon, "status": "NO_TRADE",
                      "reasoning": reason, "data_as_of": as_of})
    con.commit()
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
    cands = find_candidates(frames, uni, setups.enabled_stats(con), as_of)
    summary = {}
    for h in config.HORIZONS:
        if con.execute("SELECT 1 FROM recommendations WHERE horizon=? AND data_as_of=?", (h, as_of_s)).fetchone():
            summary[h] = "already published"
            continue
        if not cands[h]:
            publish(con, h, [], [], "No setup triggered on the latest data.", as_of_s)
            summary[h] = "NO TRADE"
            continue
        top = enrich(con, h, cands[h])
        if not top:
            publish(con, h, [], [], "No candidate passed the fundamental filter.", as_of_s)
            summary[h] = "NO TRADE"
            continue
        try:
            picks, reason = ai.rank(h, top, market)
        except ai.AIUnavailable as e:
            db.set_meta(con, f"ai_status_{h}", f"AI unavailable: {e}")
            summary[h] = "AI unavailable"
            continue  # nothing published; next run retries
        db.set_meta(con, f"ai_status_{h}", "ok")
        n = publish(con, h, top, picks, reason, as_of_s)
        summary[h] = f"{n} published" if n else "NO TRADE"
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
