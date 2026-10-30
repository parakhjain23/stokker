"""Streamlit dashboard. Run: streamlit run stockkk/dashboard.py"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockkk import config, db  # noqa: E402

st.set_page_config(page_title="Stockkk Research", page_icon="📈", layout="wide")
DISCLAIMER = ("Research and paper trading only, not investment advice. Prices are free end-of-day data "
              "and can be delayed or wrong. Past results do not guarantee future returns.")
LABEL = {"intraday": "Intraday plan", "swing": "Swing", "longterm": "Long-term"}


@st.cache_data(ttl=60)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with db.connect() as con:
        return pd.read_sql_query(sql, con, params=params)


def meta(key):
    df = q("SELECT value, updated_at FROM meta WHERE key=?", (key,))
    return (df.iloc[0]["value"], df.iloc[0]["updated_at"]) if len(df) else (None, None)


def latest_as_of():
    df = q("SELECT MAX(data_as_of) d FROM recommendations")
    return df.iloc[0]["d"]


def regime_banner():
    raw, _ = meta("overview")
    if not raw:
        return
    reg = json.loads(raw).get("regime")
    if not reg:
        return
    (st.success if reg["risk_on"] else st.warning)(
        f"**Market regime:** {reg['note']} Breadth {reg['breadth_pct']:.0f}% (20-day average {reg['breadth_20d_avg_pct']:.0f}%).")


def card(r):
    with st.container(border=True):
        color = "green" if r.direction == "BUY" else "red"
        st.markdown(f"**:{color}[{r.direction}] {r.symbol}** · {r['name']} · *{LABEL[r.horizon]}* · setup `{r.setup}`")
        c = st.columns(4)
        c[0].metric("Entry", f"₹{r.entry:,.2f}", help="Stop order: only if price trades through" if r.trigger else "Near last close")
        c[1].metric("Stop-loss", f"₹{r.stop:,.2f}")
        c[2].metric("Target", f"₹{r.target:,.2f}" if pd.notna(r.target) else "rule / time exit")
        c[3].metric("Risk:Reward", f"1:{r.rr:g}" if pd.notna(r.rr) else "open-ended")
        c = st.columns(4)
        c[0].metric("Hold", f"{r.hold_days} day{'s' if r.hold_days > 1 else ''}")
        c[1].metric("Win probability", f"{r.confidence:.0f}%", help="Chance the target is hit before the stop, from backtest + AI adjustment")
        c[2].metric("Expected", f"{r.expected_r:+.2f}R", help="Average result in multiples of risk, from backtest + AI adjustment")
        st.caption(f"Exit: {r.exit_note or 'fixed target and stop'} · Delayed EOD data as of {r.data_as_of} · status {r.status}")
        with st.expander("Why, and what would cancel it"):
            st.write(r.reasoning)
            st.markdown(f"**Technical:** {r.technical}\n\n**Fundamental:** {r.fundamental}\n\n**News:** {r.news}")
            st.warning(f"**Invalidated if:** {r.invalidation}")


def ranked_table(where: str, params: tuple, limit: int | None = None):
    show_all = st.checkbox(f"Also show matches with win probability under {config.MIN_WIN_PROB:.0%}",
                           value=False, key=f"all_{where}_{limit}")
    sql = ("SELECT rank AS Rank, symbol AS Symbol, name AS Company, horizon AS Horizon, direction AS Side, "
           "entry AS Entry, stop AS \"Stop-loss\", target AS Target, win_prob AS \"Win %\", "
           "expected_r AS \"Expected R\", setup AS Strategy, exit_note AS Exit, "
           "CASE setup_proven WHEN 1 THEN 'yes' ELSE 'no' END AS \"Proven\", ai_verdict AS \"AI verdict\", "
           "CASE recommended WHEN 1 THEN '✅' ELSE '' END AS Recommended, reasoning AS \"AI reason\" "
           f"FROM candidates WHERE {where}" + ("" if show_all else f" AND win_prob >= {config.MIN_WIN_PROB * 100}")
           + " ORDER BY win_prob DESC, expected_r DESC")
    df = q(sql + (f" LIMIT {limit}" if limit else ""), params)
    if df.empty:
        st.write("No stocks matched any pattern" + ("" if show_all else " with a high enough win probability") + ".")
        return
    if limit:  # overall list: re-number across horizons
        df["Rank"] = range(1, len(df) + 1)
    st.dataframe(df, hide_index=True, use_container_width=True,
                 column_config={"Win %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                                "AI reason": st.column_config.TextColumn(width="large")})
    st.caption("Rank 1 = highest win chance (backtest + AI adjustment). Only rows marked Recommended pass the "
               "quality bar: proven strategy, AI verdict TAKE, win probability above the minimum, positive expected return. "
               "Strategies ending in -old-str1 are the original patterns, kept for watching.")


def horizon_page(h):
    def page():
        st.header(LABEL[h])
        if h == "intraday":
            st.info("Built after the close from daily data, for the next session. Not a live signal.")
        status, _ = meta(f"ai_status_{h}")
        if status and status != "ok":
            st.error(status)
        as_of = latest_as_of()
        today = q("SELECT * FROM recommendations WHERE horizon=? AND data_as_of=? ORDER BY expected_r DESC", (h, as_of))
        if today.empty:
            st.write("No research run for the latest data yet.")
        elif (today.status == "NO_TRADE").all():
            st.subheader("NO TRADE")
            st.write(today.iloc[0].reasoning)
            st.caption(f"Data as of {as_of}")
        else:
            for _, r in today[today.status != "NO_TRADE"].iterrows():
                card(r)
        if as_of:
            st.subheader("All matching stocks, ranked")
            ranked_table("horizon=? AND data_as_of=?", (h, as_of))
        older = q("SELECT * FROM recommendations WHERE horizon=? AND status='OPEN' AND data_as_of<? ORDER BY data_as_of DESC",
                  (h, as_of or ""))
        if len(older):
            st.subheader("Still open from earlier")
            for _, r in older.iterrows():
                card(r)
    return page


def best():
    st.header("Today's best")
    regime_banner()
    as_of = latest_as_of()
    df = q("SELECT * FROM recommendations WHERE data_as_of=? AND status!='NO_TRADE' ORDER BY expected_r DESC LIMIT 5", (as_of,))
    if df.empty:
        st.subheader("NO TRADE")
        st.write("No setup met the quality bar on the latest data. Waiting is a position.")
    for _, r in df.iterrows():
        card(r)
    if as_of:
        st.subheader("Top 20 matches across all horizons")
        ranked_table("data_as_of=?", (as_of,), limit=20)
    brief, at = meta("brief")
    if brief:
        st.subheader("Market brief")
        st.markdown(brief)
        st.caption(f"AI summary of delayed data, written {at[:16]} UTC")


def scalping():
    st.header("Scalping")
    st.warning("Unavailable. Scalping needs real-time tick data, and this version uses free delayed end-of-day data. "
               "It can be added later with a broker API.")


def overview():
    st.header("Market overview")
    raw, at = meta("overview")
    if not raw:
        st.write("No data yet. Run the worker.")
        return
    o = json.loads(raw)
    regime_banner()
    st.caption(f"Delayed EOD data as of {o['as_of']} · computed {at[:16]} UTC")
    b = o["breadth"]
    st.write(f"Breadth (Nifty 500): **{b['advancers']}** advancers, **{b['decliners']}** decliners")
    pct = st.column_config.NumberColumn(format="%+.2f")
    idx = pd.DataFrame([{"Index": k, **v} for k, v in o["indices"].items()])
    idx["status"] = idx.get("status", pd.Series(dtype=str)).fillna("ok")
    idx = idx.rename(columns={"close": "Close", "chg_1d_pct": "1 day %", "chg_5d_pct": "5 days %",
                              "as_of": "As of", "status": "Status"})
    st.dataframe(idx, hide_index=True, use_container_width=True,
                 column_config={"1 day %": pct, "5 days %": pct})
    st.subheader("Sectors (median stock return, %)")
    sec = pd.DataFrame(o["sectors"]).rename(columns={"industry": "Sector", "ret1": "1 day", "ret20": "20 days"})
    st.dataframe(sec, hide_index=True, use_container_width=True, column_config={"1 day": pct, "20 days": pct})


def news_page():
    st.header("Latest market news")
    df = q("SELECT published_at, source, title, url FROM news WHERE symbol IS NULL ORDER BY published_at DESC LIMIT 60")
    if df.empty:
        st.write("No news yet.")
    for _, n in df.iterrows():
        st.markdown(f"- [{n.title}]({n.url})  \n  <small>{n.source} · {n.published_at[:16].replace('T', ' ')} UTC</small>",
                    unsafe_allow_html=True)


def performance():
    st.header("Performance (paper trading)")
    closed = q("SELECT * FROM recommendations WHERE status IN ('TARGET_HIT','SL_HIT','EXPIRED') ORDER BY closed_on")
    if closed.empty:
        st.info("No closed recommendations yet. Results appear here as targets, stops or hold periods are reached.")
    else:
        closed["pnl_pct"] = (closed.exit_price / closed.entry - 1) * 100 * closed.direction.map({"BUY": 1, "SELL": -1})
        c = st.columns(4)
        c[0].metric("Closed calls", len(closed))
        c[1].metric("Win rate", f"{(closed.status == 'TARGET_HIT').mean():.0%}")
        c[2].metric("Average result", f"{closed.result_r.mean():+.2f}R")
        c[3].metric("Average P&L per trade", f"{closed.pnl_pct.mean():+.2f}%")
        st.line_chart(closed.set_index("closed_on")["result_r"].cumsum().rename("Cumulative R"))
        g = closed.groupby("horizon").agg(calls=("id", "count"), win_rate=("status", lambda s: (s == "TARGET_HIT").mean()),
                                          avg_r=("result_r", "mean"), avg_pnl_pct=("pnl_pct", "mean"))
        st.dataframe(g.round(3), use_container_width=True)
        st.subheader("All closed calls")
        st.dataframe(closed[["closed_on", "horizon", "symbol", "direction", "entry", "exit_price", "status",
                             "result_r", "pnl_pct", "setup"]].round(2), hide_index=True, use_container_width=True)
    st.subheader("Strategies: 8-year backtest with a 2-year hold-out, and live results")
    stats = q("SELECT setup AS Strategy, generation AS Generation, horizon AS Horizon, trades AS Trades, "
              "hit_rate AS \"Win rate\", avg_r AS \"Avg R\", is_avg_r AS \"Avg R in-sample\", "
              "oos_trades AS \"Hold-out trades\", oos_hit_rate AS \"Hold-out win rate\", oos_avg_r AS \"Hold-out avg R\", "
              "max_dd_r AS \"Max drawdown R\", live_trades AS \"Live calls\", live_hit_rate AS \"Live win rate\", "
              "live_avg_r AS \"Live avg R\", CASE enabled WHEN 1 THEN 'yes' ELSE 'no' END AS Active, "
              "disabled_reason AS \"Why inactive\" FROM setup_stats ORDER BY enabled DESC, oos_avg_r DESC")
    st.dataframe(stats.round(3), hide_index=True, use_container_width=True)
    st.caption("A strategy is active only if it is profitable net of costs both in the first 6 years and in the last "
               "2 years (which it was not tuned on), and it is switched off if live results fall short. "
               "Trend strategies also stand aside when market breadth is weak. "
               "R = result as a multiple of the risk taken (entry to stop).")


with st.sidebar:
    st.caption(DISCLAIMER)
    runs = q("SELECT job, started_at, ok, message FROM runs ORDER BY id DESC LIMIT 1")
    if len(runs):
        r = runs.iloc[0]
        st.caption(f"Last job: {r.job} at {r.started_at[:16]} UTC · {'ok' if r.ok else 'FAILED'}")

pg = st.navigation([
    st.Page(best, title="Today's best", icon="⭐", default=True),
    st.Page(horizon_page("intraday"), title="Intraday", icon="⏱️", url_path="intraday"),
    st.Page(scalping, title="Scalping", icon="⚡"),
    st.Page(horizon_page("swing"), title="Swing", icon="📊", url_path="swing"),
    st.Page(horizon_page("longterm"), title="Long-term", icon="🌱", url_path="longterm"),
    st.Page(overview, title="Market overview", icon="🌍"),
    st.Page(news_page, title="News", icon="📰"),
    st.Page(performance, title="Performance", icon="🏁"),
])
st.warning(DISCLAIMER, icon="⚠️")
pg.run()
