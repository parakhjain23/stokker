---
date: 2026-10-30
topic: indian-stock-research-app
---

# AI-Powered Indian Stock Research and Recommendation App

## Summary

A single Python application that, on a schedule, pulls delayed NSE/BSE data and news, runs coded, backtested technical setups, asks Gemini to rank and explain the survivors, records every recommendation, grades it against later prices, and shows everything on a simple dashboard. Paper trading only.

---

## Problem Frame

Scanning 500+ Indian stocks every day for clean technical setups, cross-checking news, results and global cues, and then honestly tracking whether past calls worked is hours of manual work and is rarely done consistently. Most "AI stock tip" tools hide their hit rate and invent confidence. The user wants a personal research desk that is explainable, measured, and honest about data quality and about saying NO TRADE.

---

## Actors

- A1. User (single trader/investor): reads the dashboard, acts manually on recommendations.
- A2. Research engine (scheduled jobs): fetches data, computes setups, calls Gemini, grades past calls.
- A3. Gemini (LLM): ranks candidate setups, writes reasoning, summarises news. Never invents prices.

---

## Key Flows

- F1. Daily research run
  - **Trigger:** Scheduler, after market close (EOD data available) and again pre-market; lighter news-only runs through the night.
  - **Actors:** A2, A3
  - **Steps:** Fetch EOD prices for the universe and global indices; compute indicators; run setup rules; backtest-derived stats attach to each candidate; fetch news/announcements per candidate; Gemini ranks and writes reasoning or returns NO TRADE; save recommendations with status OPEN.
  - **Outcome:** Dashboard shows today's recommendations or NO TRADE per horizon, each with a data timestamp.
  - **Covered by:** R1–R12

- F2. Grading past recommendations
  - **Trigger:** Every data refresh.
  - **Actors:** A2
  - **Steps:** For each OPEN recommendation, compare subsequent high/low against target and stop-loss; mark TARGET_HIT, SL_HIT, or EXPIRED after holding period; update per-setup live hit rate; disable setups below threshold.
  - **Outcome:** Performance page shows win rate, average RR achieved, equity curve of paper P&L.
  - **Covered by:** R13–R16

- F3. User reviews dashboard
  - **Trigger:** User opens the app.
  - **Actors:** A1
  - **Steps:** See market overview, best opportunities, per-horizon lists, news, performance. Open one recommendation to read full reasoning and invalidation conditions.
  - **Outcome:** User decides whether to trade manually.
  - **Covered by:** R17–R20

---

## Requirements

**Data and research**
- R1. Cover NSE/BSE equities in the Nifty 500 universe plus major indices (Nifty 50, Bank Nifty, sector indices) and global cues (US indices, crude, USD/INR, GIFT Nifty where available).
- R2. Use free delayed data for now. Every displayed value carries a fetch timestamp and a "delayed" label. Missing data is shown as unavailable, never estimated.
- R3. Compute RSI, MACD, EMA (20/50/200), VWAP (where intraday bars exist), volume averages, support/resistance, and sector relative strength.
- R4. Fetch news headlines and exchange announcements for the universe; fetch available fundamentals (PE, EPS growth, debt, ROE, recent quarterly results) per stock.
- R5. Research jobs run 24/7: heavy scans post-close and pre-market, news scans hourly.

**Setups and validation**
- R6. Technical setups are coded rules (e.g. breakout with volume, EMA pullback, RSI reversal, 52-week high momentum, long-term value+momentum). Each has a defined entry, stop, target and holding window per horizon.
- R7. Every setup is backtested on at least 3 years of daily data across the universe. Hit rate, average RR and max drawdown are stored and shown.
- R8. Gemini receives only pre-qualified candidates with their stats, indicators, news and fundamentals. It ranks, explains, and may reject. It cannot propose stocks outside the candidate list or quote prices not in its input.

**Recommendations**
- R9. Horizons: intraday (pre-market plan from prior-day data), swing (days to weeks), long-term (months+). Scalping is shown as unavailable until real-time data exists.
- R10. Each recommendation includes: symbol and name, direction, entry, stop-loss, target, RR, holding period, confidence score, reasoning, supporting technical/fundamental/news analysis, invalidation conditions, data timestamp.
- R11. Confidence = setup's backtested and live hit rate, adjusted within a bounded range by Gemini's news/fundamental assessment. Minimum RR of 1:2 for swing/intraday; recommendations below quality thresholds are not published.
- R12. If no candidate passes thresholds for a horizon, the app publishes NO TRADE for that horizon with a one-line reason.

**Performance tracking**
- R13. Every recommendation is stored and never edited after publication.
- R14. Open recommendations are graded automatically against later OHLC: TARGET_HIT, SL_HIT, EXPIRED.
- R15. Dashboard shows win rate, average achieved RR, paper P&L per horizon and per setup.
- R16. Setups whose live hit rate drops below a configurable threshold over a minimum sample are auto-disabled and flagged.

**Dashboard**
- R17. Pages: Today's best, Intraday, Swing, Long-term, Market overview, News, Performance.
- R18. A recommendation detail view shows full reasoning and invalidation conditions.
- R19. A visible disclaimer on every page: research only, no guaranteed returns, delayed data.
- R20. Clean, modern, readable on a laptop. No login.

---

## Acceptance Examples

- AE1. **Covers R2.** Given yfinance returns no data for a symbol, when the dashboard renders, that symbol shows "data unavailable" and is excluded from recommendations.
- AE2. **Covers R11, R12.** Given no swing candidate reaches minimum confidence and RR 1:2, when the daily run completes, the Swing page shows NO TRADE with the reason "no setup met quality threshold".
- AE3. **Covers R8.** Given Gemini's reply names a stock not in the candidate list, when parsed, that item is discarded and logged.
- AE4. **Covers R14.** Given an open swing call with target 110 and SL 95, when a later day's high reaches 110 before any low reaches 95, status becomes TARGET_HIT on that date.
- AE5. **Covers R16.** Given a setup with 30 live calls and hit rate under threshold, when grading runs, the setup is disabled and shown as disabled on the Performance page.

---

## Success Criteria

- User opens the dashboard each morning and gets actionable, explained calls or an honest NO TRADE in under a minute of reading.
- Every published call can be traced to its data timestamp, setup stats and Gemini reasoning.
- After 60 days, the Performance page shows a measured win rate and P&L for each horizon and setup.
- Planning can start from this doc without inventing product behaviour.

---

## Scope Boundaries

### Deferred for later
- Real-time data via broker API; scalping; true intraday monitoring.
- Alerts (Telegram/email), mobile layout.
- Options/futures.
- Deep parsing of quarterly result PDFs and concall transcripts.

### Outside this product's identity
- Trade execution or broker order placement.
- Multi-user SaaS, auth, subscriptions.
- ML model training or "self-learning" beyond hit-rate feedback.
- Portfolio management or accounting.

---

## Key Decisions

- Free delayed data now: user chose to defer real-time. Scalping dropped, intraday becomes a pre-market plan.
- Gemini (cheapest capable model, free tier): user's choice for cost.
- Rule-based setups + backtester, Gemini ranks/explains (approach C): makes confidence measurable and keeps LLM from inventing picks.
- Nifty 500 universe: breadth vs. scan cost.
- Single user, single process, no microservices: user's explicit constraint.

---

## Proposed Architecture

The brainstorm is inherently technical, so the stack is recorded here.

- **Language:** Python 3.12, one repo, one process.
- **Data:** `yfinance` for NSE/BSE OHLCV, indices, global cues, basic fundamentals. NSE bhavcopy/announcements and ET/Moneycontrol RSS for news. All free and delayed.
- **Indicators:** `pandas` + `pandas-ta`.
- **Backtesting:** `vectorbt` or `backtesting.py` (planning decides; one library only).
- **AI:** Gemini Flash via `google-genai` SDK; structured JSON output; strict schema validation of replies.
- **Storage:** SQLite via SQLAlchemy. Tables: prices, recommendations, grades, setup_stats, news.
- **Scheduler:** APScheduler inside the same process.
- **Dashboard:** Streamlit reading SQLite.
- **Deploy:** runs on the user's Mac or one small VPS with a single `python main.py`.

```
yfinance / RSS ──> fetch jobs ──> SQLite <──> Streamlit dashboard
                       │
                indicators + setup rules + backtest stats
                       │
                 Gemini rank + explain ──> recommendations
                       │
                 grading job (target / SL / expiry)
```

---

## Development Plan

1. **Data + indicators (week 1):** universe list, price fetch, indicator computation, SQLite schema, timestamps and delayed labels.
2. **Setups + backtester (week 2):** 4–5 coded setups, 3-year backtest, stats stored.
3. **Gemini layer + recommendations (week 3):** candidate packaging, prompt, JSON schema, NO TRADE logic, thresholds.
4. **Grading + performance (week 4):** auto-grading, hit-rate feedback, auto-disable.
5. **Dashboard + scheduler (week 5):** Streamlit pages, APScheduler, disclaimer, run end to end for a week of paper trading.

---

## Dependencies / Assumptions

- yfinance remains usable for NSE/BSE symbols (unofficial; may break, so fetch layer is isolated).
- Gemini free tier rate limits are enough for a few hundred calls/day; batching candidates per call keeps it low.
- NSE announcement endpoints may block scrapers; news falls back to RSS only.

---

## Outstanding Questions

### Deferred to Planning

- [Affects R7][Technical] vectorbt vs backtesting.py.
- [Affects R4][Needs research] Most reliable free source for NSE corporate announcements in 2026.
- [Affects R11][Technical] Exact confidence formula and thresholds per horizon.
