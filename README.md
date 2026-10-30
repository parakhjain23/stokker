# Stockkk: Indian stock research (paper trading only)

Scans every NSE stock trading over ₹1 crore a day, each evening, with coded, backtested setups.
Gemini judges every match. The dashboard ranks all matches by win chance, shows the calls that
pass the quality bar (or NO TRADE), and tracks how past calls did.

Not investment advice. It uses free, delayed end-of-day data (Yahoo Finance, with NSE as fallback).
On Gemini's free tier, Google may use your prompts for training. Only public market data is sent.

## Setup

    python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
    cp .env.example .env        # then add your GEMINI_API_KEY

## Run

    .venv/bin/python -m stockkk.worker              # 24/7 schedule (IST); catches up on start
    .venv/bin/streamlit run stockkk/dashboard.py    # dashboard at http://localhost:8501

Run one job now: `.venv/bin/python -m stockkk.worker --once eod`. The other jobs are `premarket`, `news` and `backtest`.

Schedule:
- 16:30 Mon–Fri: end-of-day scan, grading and recommendations.
- 08:30 Mon–Fri: global cues and the market brief.
- Hourly: news.
- Sunday 10:00: backtest refresh.

## How a recommendation is made

1. Six coded setups are backtested on 3 years of data across all liquid NSE stocks.
2. Every stock matching any setup on the latest bar becomes a candidate. There is no limit.
3. Fundamentals and news are attached. Gemini judges every candidate (TAKE or SKIP), explains it,
   and may move the win probability by ±15 points.
4. All candidates are ranked, with 1 being the highest win chance.
5. A candidate becomes a tracked call only if all of these hold:
   - its setup has a proven backtested edge of at least +0.05R, where R is the risk from entry to stop;
   - Gemini says TAKE;
   - risk-reward and expected result clear the thresholds in `stockkk/config.py`.
   Otherwise the horizon shows NO TRADE.
6. Open calls are graded each evening against real prices. A setup that underperforms live is switched off.

Tests: `.venv/bin/python -m pytest -q`
