"""Streamlit dashboard. Run: streamlit run stockkk/dashboard.py"""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stockkk import config, db, diary  # noqa: E402

st.set_page_config(page_title="Stockkk Research", page_icon="📈", layout="wide")
LABEL = {"intraday": "Intraday plan", "swing": "Swing", "longterm": "Long-term"}
GREEN, RED, AMBER = "color:#22c55e;font-weight:600", "color:#ef4444;font-weight:600", "color:#f59e0b;font-weight:600"
STATUS = {"TARGET_HIT": "Target hit", "SL_HIT": "Stop-loss hit", "EXPIRED": "Time up, sold",
          "EXIT_RULE": "Exit rule, sold", "NOT_TRIGGERED": "Order not filled", "OPEN": "Open"}
WORDS = {"BUY": GREEN, "TAKE": GREEN, "Target hit": GREEN, "Open": GREEN, "yes": GREEN, "ok": GREEN,
         "SELL": RED, "SKIP": RED, "Stop-loss hit": RED, "no": RED, "Time up, sold": AMBER, "Exit rule, sold": AMBER}
PER100 = "Profit per ₹100 risked"
MONEY, PCT = "₹{:,.2f}", "{:.0f}%"


def GAIN(v):  # noqa: N802 - used like the format constants above
    return f"+₹{v:,.0f}" if v >= 0 else f"−₹{-v:,.0f}"

PER100_HELP = ("Average profit for every ₹100 you could lose on the trade (entry to stop-loss). "
               "+₹21 means: risk ₹100, expect to make ₹21 on average.")


def ist(ts) -> str:
    """UTC timestamp string -> '16 Nov 2026, 06:35 PM IST'."""
    return pd.Timestamp(ts).tz_convert("Asia/Kolkata").strftime("%d %b %Y, %I:%M %p IST") if ts else ""


def color(df: pd.DataFrame, signed=(), fmt=None):
    """Green/red text for known words and for the sign of numbers in `signed`; numbers rounded via `fmt`."""
    def num(v):
        return "" if pd.isna(v) else GREEN if v > 0 else RED if v < 0 else ""
    st_ = df.style.map(lambda v: WORDS.get(v, "") if isinstance(v, str) else "")
    cols = [c for c in signed if c in df.columns]
    st_ = st_.map(num, subset=cols) if cols else st_
    return st_.format(precision=2, na_rep="—").format({k: v for k, v in (fmt or {}).items() if k in df.columns},
                                                       na_rep="—")


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


def cards(df):
    """Open/new recommendations as one compact table; reasons in a single expander below."""
    if df.empty:
        return
    t = pd.DataFrame({
        "Side": df.direction, "Symbol": df.symbol, "Company": df["name"], "Horizon": df.horizon.map(LABEL),
        "Entry": df.entry, "Stop-loss": df.stop, "Target": df.target, "Risk : Reward": df.rr,
        "Hold days": df.hold_days, "Chance to win": df.confidence, PER100: df.expected_r * 100,
        "Strategy": df.setup, "Exit": df.exit_note.fillna("fixed target and stop-loss"),
        "Data date": df.data_as_of, "Status": df.status.map(STATUS).fillna(df.status)})
    st.dataframe(color(t, [PER100], {"Entry": MONEY, "Stop-loss": MONEY, "Target": MONEY, "Risk : Reward": "1 : {:g}",
                                     "Chance to win": PCT, PER100: GAIN}),
                 hide_index=True, use_container_width=True, column_config={
        "Target": st.column_config.Column(help="— = no fixed target; sold by the exit rule or after the hold days"),
        "Risk : Reward": st.column_config.Column(help="Risk ₹1 to make this much. — = no fixed target"),
        "Chance to win": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
        PER100: st.column_config.Column(help=PER100_HELP)})
    with st.expander("Why, and what would cancel each one"):
        for _, r in df.iterrows():
            why = "\n".join(f"  - {p.strip()}" for p in str(r.reasoning).split(";") if p.strip())
            st.markdown(f"**{r.direction} {r.symbol}**\n- **Why:**\n{why}\n- **Chart:** {r.technical}\n"
                        f"- **Company:** {r.fundamental}\n- **News:** {r.news}\n"
                        f"- **Cancel the trade if:** {r.invalidation}")


def ranked_table(where: str, params: tuple, limit: int | None = None):
    show_all = st.checkbox(f"Also show matches with win probability under {config.MIN_WIN_PROB:.0%}",
                           value=False, key=f"all_{where}_{limit}")
    sql = ("SELECT rank AS Rank, symbol AS Symbol, name AS Company, horizon AS Horizon, direction AS Side, "
           "entry AS Entry, stop AS \"Stop-loss\", target AS Target, win_prob AS \"Chance to win\", "
           "expected_r * 100 AS \"Profit per ₹100 risked\", setup AS Strategy, exit_note AS Exit, "
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
    st.dataframe(color(df, [PER100], {"Entry": MONEY, "Stop-loss": MONEY, "Target": MONEY, PER100: GAIN}),
                 hide_index=True, use_container_width=True,
                 column_config={"Chance to win": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                                PER100: st.column_config.Column(help=PER100_HELP),
                                "AI reason": st.column_config.TextColumn(width="large")})
    st.caption("Rank 1 = highest chance to win (past results + AI check). Only rows marked Recommended pass every test: "
               "a proven strategy, AI says TAKE, a high enough chance to win, and a positive profit per ₹100 risked. "
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
            cards(today[today.status != "NO_TRADE"])
        if as_of:
            st.subheader("All matching stocks, ranked")
            ranked_table("horizon=? AND data_as_of=?", (h, as_of))
        older = q("SELECT * FROM recommendations WHERE horizon=? AND status='OPEN' AND data_as_of<? ORDER BY data_as_of DESC",
                  (h, as_of or ""))
        if len(older):
            st.subheader("Still open from earlier")
            cards(older)
    return page


def best():
    st.header("Today's best")
    regime_banner()
    as_of = latest_as_of()
    df = q("SELECT * FROM recommendations WHERE data_as_of=? AND status!='NO_TRADE' ORDER BY expected_r DESC LIMIT 5", (as_of,))
    if df.empty:
        st.subheader("NO TRADE")
        st.write("No setup met the quality bar on the latest data. Waiting is a position.")
    cards(df)
    if as_of:
        st.subheader("Top 20 matches across all horizons")
        ranked_table("data_as_of=?", (as_of,), limit=20)
    brief, at = meta("brief")
    if brief:
        st.subheader("Market brief")
        st.markdown(brief)
        st.caption(f"AI summary of delayed data, written {ist(at)}")


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
    st.caption(f"Delayed end-of-day data as of {o['as_of']} · computed {ist(at)}")
    b = o["breadth"]
    st.write(f"Breadth (Nifty 500): **{b['advancers']}** advancers, **{b['decliners']}** decliners")
    pct = st.column_config.NumberColumn(format="%+.2f")
    idx = pd.DataFrame([{"Index": k, **v} for k, v in o["indices"].items()])
    idx["status"] = idx.get("status", pd.Series(dtype=str)).fillna("ok")
    idx = idx.rename(columns={"close": "Close", "chg_1d_pct": "1 day %", "chg_5d_pct": "5 days %",
                              "as_of": "As of", "status": "Status"})
    st.dataframe(color(idx, ["1 day %", "5 days %"]), hide_index=True, use_container_width=True,
                 column_config={"1 day %": pct, "5 days %": pct})
    st.subheader("Sectors (median stock return, %)")
    sec = pd.DataFrame(o["sectors"]).rename(columns={"industry": "Sector", "ret1": "1 day", "ret20": "20 days"})
    st.dataframe(color(sec, ["1 day", "20 days"]), hide_index=True, use_container_width=True, column_config={"1 day": pct, "20 days": pct})


def news_page():
    st.header("Latest market news")
    df = q("SELECT published_at, source, title, url FROM news WHERE symbol IS NULL ORDER BY published_at DESC LIMIT 60")
    if df.empty:
        st.write("No news yet.")
    for _, n in df.iterrows():
        st.markdown(f"- [{n.title}]({n.url})  \n  <small>{n.source} · {ist(n.published_at)}</small>",
                    unsafe_allow_html=True)


def diary_page():
    st.header("Trade diary (paper trading)")
    per = config.PAPER_PER_TRADE
    st.caption(f"Every stock the app suggests is written here on the day it is suggested, with a pretend ₹{per:,} "
               "put into each one. Nothing is ever edited or deleted afterwards. Open trades are valued at the latest "
               "closing price; closed trades at their real exit, after costs.")
    recs = q("SELECT * FROM recommendations WHERE status!='NO_TRADE' ORDER BY data_as_of DESC, id DESC")
    rejected = q("SELECT *, win_prob AS confidence FROM candidates WHERE recommended=0 ORDER BY data_as_of DESC, id DESC")
    counts = recs.horizon.value_counts()
    views = {f"All ({len(recs)})": None, **{f"{LABEL[h]} ({counts.get(h, 0)})": h for h in LABEL},
             f"Not recommended ({len(rejected)})": "rejected"}
    view = views[st.radio("Show diary for", list(views), horizontal=True, key="diary_view")]
    if view == "rejected":
        recs = rejected
        st.warning("These are matches the app did NOT recommend (unproven strategy, AI said SKIP, or a low chance to win). "
                   "They are followed only to check that rejecting them was right. They never count in the real diary.")
        split = st.radio("Horizon", ["All", *LABEL.values()], horizontal=True, key="diary_rejected_horizon")
        if split != "All":
            recs = recs[recs.horizon.map(LABEL) == split]
    elif view:
        recs = recs[recs.horizon == view]
    if recs.empty:
        st.info("Nothing here yet. Entries appear automatically after the daily run.")
        return
    before = len(recs)
    recs = diary.drop_repeats(recs).sort_values(["data_as_of", "id"], ascending=False)
    if before > len(recs):
        st.caption(f"{before - len(recs):,} repeat entries left out: the same stock matched again while its earlier "
                   "entry was still open, so it is counted once.")
    live_rows = recs[recs.status == "OPEN"]
    prices = pd.DataFrame(columns=["symbol", "date", "close"])
    if len(live_rows):
        marks = ",".join("?" * live_rows.symbol.nunique())
        prices = q(f"SELECT symbol, date, close FROM prices WHERE symbol IN ({marks}) AND date>?",
                   (*live_rows.symbol.unique(), live_rows.data_as_of.min()))
    nifty = q("SELECT date, close FROM prices WHERE symbol='^NSEI' AND date>=? ORDER BY date", (recs.data_as_of.min(),))
    d = diary.build(recs, prices, nifty)
    m = diary.summary(d)
    pc = lambda v: "—" if v is None or pd.isna(v) else f"{v:+.2f}%"  # noqa: E731
    c = st.columns(6)
    c[0].metric("Matches followed" if view == "rejected" else "Stocks suggested", m["calls"],
                help="Every entry since the app started")
    c[1].metric("Open now", m["open"] + m["waiting"], help="Still running, or waiting for the next session to enter")
    c[2].metric("Closed", m["closed"])
    c[3].metric("Accuracy", "—" if m["accuracy"] is None else f"{m['accuracy']:.0f}%",
                help="Closed trades that ended in profit ÷ all closed trades")
    c[4].metric("Target hit", m["target_hit"])
    c[5].metric("Stop-loss hit", m["stop_hit"])
    rs = lambda v: f"₹{v:,.0f}"  # noqa: E731
    dl = lambda v: GAIN(v).replace("−", "-")  # noqa: E731 - Streamlit colours a delta red only on a plain minus
    c = st.columns(6)
    c[0].metric("Total money put in", rs(m["invested"]), help=f"₹{per:,} for every trade that was entered, open or closed")
    c[1].metric("In the market now", rs(m["open_money"]), help=f"₹{per:,} × {m['open']} open trades")
    c[2].metric("Worth today", rs(m["open_value"]), delta=dl(m["running"]) if m["open"] else None,
                help="What the open trades are worth at the latest closing price")
    c[3].metric("Open trades in profit", m["open_up"], delta=dl(m["open_up_rs"]) if m["open_up"] else None)
    c[4].metric("Open trades in loss", m["open_down"], delta=dl(m["open_down_rs"]) if m["open_down"] else None)
    c[5].metric("Closed: won / lost", f"{m['won']} / {m['lost']}",
                help=f"Won {GAIN(m['won_rs'])}, lost {GAIN(m['lost_rs'])}")
    c = st.columns(6)
    c[0].metric("Total profit / loss", GAIN(m["total"]), delta=f"{m['total'] / m['invested'] * 100:+.2f}%" if m["invested"] else None,
                help=f"Booked + running, on ₹{m['invested']:,} of pretend money")
    c[1].metric("Booked (closed trades)", GAIN(m["booked"]))
    c[2].metric("Running (open trades)", GAIN(m["running"]))
    c[3].metric("Average winning trade", pc(m["avg_win"]))
    c[4].metric("Average losing trade", pc(m["avg_loss"]))
    c[5].metric("Best / worst trade", f"{pc(m['best'])} / {pc(m['worst'])}")
    if m["invested"] and pd.notna(m["nifty"]):
        c = st.columns(6)
        c[0].metric("Same money in Nifty 50", GAIN(m["nifty"]), delta=f"{m['nifty'] / m['invested'] * 100:+.2f}%",
                    help="If each ₹10,000 had simply been put in the Nifty 50 index for the same days instead")
        c[1].metric("Beat Nifty 50 by", GAIN(m["beat"]), delta="ahead" if m["beat"] >= 0 else "-behind",
                    help="Total profit / loss minus what the Nifty 50 made. Below zero = just buying the index was better")
        c[2].metric("Trades that beat Nifty 50", f"{m['beat_share']:.0f}%")
    st.caption(f"Sold by time or exit rule: {m['other_exit']} · order never filled: {m['not_filled']} · "
               f"average days held: {'—' if m['avg_days'] is None else round(m['avg_days'], 1)}")

    names = {"open": "Open", "waiting": "Enters next session", "not filled": "Order not filled"}
    d["Result"] = d.state.map(names).where(d.state != "closed", d.status.map(STATUS))
    fmt = {"Entry": MONEY, "Stop-loss": MONEY, "Target": MONEY, "Price now": MONEY, "Exit price": MONEY,
           "Profit / loss %": "{:+.2f}%", "Profit / loss ₹": GAIN, PER100: GAIN, "Days held": "{:.0f}",
           "Days in trade": "{:.0f}", "To stop-loss": "{:.1f}%", "To target": "{:.1f}%", "Accuracy": PCT}
    fmt |= {"Shares": "{:,.1f}", "Nifty 50 same days %": "{:+.2f}%", "Beat Nifty 50 by ₹": GAIN}
    signed = ["Profit / loss %", "Profit / loss ₹", PER100, "Nifty 50 same days %", "Beat Nifty 50 by ₹"]

    live = d[d.state.isin(["open", "waiting"])]
    st.subheader(f"Open trades ({len(live)})")
    if live.empty:
        st.write("No open trades right now.")
    else:
        sign = live.direction.map({"BUY": 1, "SELL": -1})
        t = pd.DataFrame({"Suggested on": live.data_as_of, "Side": live.direction, "Symbol": live.symbol,
                          "Company": live["name"], "Horizon": live.horizon.map(LABEL), "Entry": live.entry,
                          "Shares": per / live.entry,
                          "Price now": live.last_price, "Profit / loss %": live.pnl_pct, "Profit / loss ₹": live.pnl_rs,
                          "Nifty 50 same days %": live.nifty_pct, "Beat Nifty 50 by ₹": live.beat_rs,
                          "Stop-loss": live.stop, "To stop-loss": sign * (live.last_price / live.stop - 1) * 100,
                          "Target": live.target, "To target": sign * (live.target / live.last_price - 1) * 100,
                          "Days in trade": live.days, "Hold days": live.hold_days, "Result": live.Result,
                          "Strategy": live.setup})
        if len(t) > 1000:
            st.caption(f"Showing the newest 1,000 of {len(t):,} open trades.")
        st.dataframe(color(t.head(1000), signed, fmt), hide_index=True, use_container_width=True, column_config={
            "To stop-loss": st.column_config.Column(help="How far the price can still fall before the stop-loss sells it"),
            "To target": st.column_config.Column(help="How far the price still has to go. — = no fixed target")})

    done = d[d.state == "closed"].sort_values("closed_on")
    if len(done):
        st.subheader("Money over time")
        by_day = done.groupby("closed_on")[["pnl_rs", "nifty_rs"]].sum().cumsum()
        st.line_chart(by_day.rename(columns={"pnl_rs": "Diary: booked profit / loss (₹)",
                                             "nifty_rs": "Same money in Nifty 50 (₹)"}))
        st.subheader("Where the results come from")
        band = (done.confidence < config.MIN_WIN_PROB * 100).map(
            {True: f"Under {config.MIN_WIN_PROB:.0%}", False: f"{config.MIN_WIN_PROB:.0%} and above"})
        groups = [(done.horizon.map(LABEL), "Horizon"), (done.setup, "Strategy"), (done.closed_on.str[:7], "Month closed"),
                  (band, "Chance to win when suggested")]
        if "ai_verdict" in done:
            groups.append((done.ai_verdict, "AI verdict"))
        for col, label in groups:
            g = done.groupby(col.rename(label)).agg(
                **{"Closed trades": ("id", "count"), "Accuracy": ("pnl_pct", lambda x: (x > 0).mean() * 100),
                   "Target hit": ("status", lambda x: (x == "TARGET_HIT").sum()),
                   "Stop-loss hit": ("status", lambda x: (x == "SL_HIT").sum()),
                   "Profit / loss ₹": ("pnl_rs", "sum"), "Profit / loss %": ("pnl_pct", "mean"),
                   "Beat Nifty 50 by ₹": ("beat_rs", "sum")})
            st.dataframe(color(g, signed, fmt), use_container_width=True,
                         column_config={"Profit / loss %": st.column_config.Column(help="Average per trade")})

    st.subheader(f"Full diary, newest first ({len(d)})")
    pick = st.multiselect("Show", sorted(d.Result.dropna().unique()), key="diary_filter", placeholder="All results")
    v = d[d.Result.isin(pick)] if pick else d
    if len(v) > 1000:  # the table shows the newest 1,000; the download has everything
        st.caption(f"Showing the newest 1,000 of {len(v):,}. Use the download for all of them.")
    t = pd.DataFrame({"Suggested on": v.data_as_of, "Side": v.direction, "Symbol": v.symbol, "Company": v["name"],
                      "Horizon": v.horizon.map(LABEL), "Entry": v.entry, "Shares": per / v.entry,
                      "Stop-loss": v.stop, "Target": v.target,
                      "Result": v.Result, "Closed on": v.closed_on, "Exit price": v.exit_price,
                      "Price now": v.last_price.where(v.state == "open"), "Days held": v.days,
                      "Profit / loss %": v.pnl_pct, "Profit / loss ₹": v.pnl_rs, PER100: v.per100,
                      "Nifty 50 same days %": v.nifty_pct, "Beat Nifty 50 by ₹": v.beat_rs,
                      "Chance to win (at suggestion)": v.confidence, "Strategy": v.setup})
    st.dataframe(color(t.head(1000), signed, {**fmt, "Chance to win (at suggestion)": PCT}), hide_index=True,
                 use_container_width=True, column_config={PER100: st.column_config.Column(help=PER100_HELP)})
    st.download_button("Download diary (CSV)", t.to_csv(index=False), "trade_diary.csv", "text/csv")


def strategies():
    st.header("Strategies")
    st.subheader("Strategies: tested on 8 years of past prices (last 2 years kept unseen), and live results")
    stats = q("SELECT setup AS Strategy, generation AS Generation, horizon AS Horizon, trades AS Trades, "
              "hit_rate * 100 AS \"Win rate\", avg_r * 100 AS \"Profit per ₹100 risked\", "
              "is_avg_r * 100 AS \"Profit per ₹100 (first 6 years)\", oos_trades AS \"Trades (last 2 years)\", "
              "oos_hit_rate * 100 AS \"Win rate (last 2 years)\", oos_avg_r * 100 AS \"Profit per ₹100 (last 2 years)\", "
              "max_dd_r * 100 AS \"Worst losing run (₹ per ₹100 risked)\", live_trades AS \"Live calls\", "
              "live_hit_rate * 100 AS \"Live win rate\", live_avg_r * 100 AS \"Profit per ₹100 (live)\", CASE enabled WHEN 1 THEN 'yes' ELSE 'no' END AS Active, "
              "disabled_reason AS \"Why inactive\" FROM setup_stats ORDER BY enabled DESC, oos_avg_r DESC")
    gain_cols = [PER100, "Profit per ₹100 (first 6 years)", "Profit per ₹100 (last 2 years)", "Profit per ₹100 (live)"]
    st.dataframe(color(stats, gain_cols, {**{c: GAIN for c in gain_cols}, "Worst losing run (₹ per ₹100 risked)": "₹{:,.0f}",
                                          "Win rate": PCT, "Win rate (last 2 years)": PCT, "Live win rate": PCT}),
                 hide_index=True, use_container_width=True)
    st.caption("A strategy is active only if it is profitable net of costs both in the first 6 years and in the last "
               "2 years (which it was not tuned on), and it is switched off if live results fall short. "
               "Trend strategies also stand aside when most stocks are falling. "
               "Profit per ₹100 risked: if the stop-loss would cost you ₹100, this is what the strategy made on average.")


IST = "Asia/Kolkata"


def _cron_today(cron: str, now: pd.Timestamp):
    """(label, today's scheduled time or None) for the simple 'M H * * D' crons in embarko.json."""
    m, h, _, _, days = cron.split()[:5]
    if h == "*":
        return f"every hour at :{int(m):02d}", None
    wd = (now.day_of_week + 1) % 7  # cron: 0 = Sunday
    on = days == "*" or (wd in range(int(days.split("-")[0]), int(days.split("-")[-1]) + 1))
    names = {"*": "daily", "1-5": "Mon-Fri", "0": "Sun"}
    label = f"{int(h):02d}:{int(m):02d} {names.get(days, days)}"
    return label, now.normalize() + pd.Timedelta(hours=int(h), minutes=int(m)) if on else None


def system_status():
    st.header("Background jobs")
    now = pd.Timestamp.now(tz=IST)
    sched = json.loads((Path(__file__).resolve().parent.parent / "embarko.json").read_text())["schedules"]
    runs = q("SELECT job, started_at, ok, message FROM runs WHERE id IN (SELECT MAX(id) FROM runs GROUP BY job)")
    last = {r.job: r for r in runs.itertuples()}
    running = getattr(sys.modules.get("__main__"), "_running", {})  # set by main.py's worker thread
    rows = []
    for s in sched:
        job = s["path"].rsplit("/", 1)[-1]
        label, due = _cron_today(s["cron"], now)
        r = last.get(job)
        at = pd.Timestamp(r.started_at).tz_convert(IST) if r else None
        if job in running:
            status = "🔵 running"
        elif at is not None and at.date() == now.date():
            status = "✅ done" if r.ok else "❌ failed"
        elif due is None and label.startswith("every"):
            status = "⚠️ late" if at is None or now - at > pd.Timedelta(hours=2) else "✅ done"
        elif due is None:
            status = "— not today"
        else:
            status = "⚠️ missed" if now > due + pd.Timedelta(minutes=15) else "⏳ waiting"
        rows.append({"Schedule (IST)": label, "Job": job, "Today": status,
                     "Last run (IST)": at.strftime("%d %b %Y, %I:%M %p") if at is not None else "never",
                     "Last result": ("ok · " if r.ok else "failed · ") + str(r.message)[:120] if r else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                 column_config={"Last result": st.column_config.TextColumn(width="large")})
    st.caption(f"Checked {now.strftime('%d %b, %I:%M %p')} IST. A job takes a few minutes after its schedule; "
               "a full end-of-day run can take up to an hour.")


pg = st.navigation([
    st.Page(best, title="Today's best", icon="⭐", default=True),
    st.Page(horizon_page("intraday"), title="Intraday", icon="⏱️", url_path="intraday"),
    st.Page(scalping, title="Scalping", icon="⚡"),
    st.Page(horizon_page("swing"), title="Swing", icon="📊", url_path="swing"),
    st.Page(horizon_page("longterm"), title="Long-term", icon="🌱", url_path="longterm"),
    st.Page(overview, title="Market overview", icon="🌍"),
    st.Page(news_page, title="News", icon="📰"),
    st.Page(diary_page, title="Trade diary", icon="📒"),
    st.Page(strategies, title="Strategies", icon="🏁"),
    st.Page(system_status, title="Background jobs", icon="⚙️"),
])
pg.run()
