# Stockkk: Indian stock research (paper trading only)

Scans the Nifty 500 every evening with coded, backtested setups. Gemini ranks and explains
the candidates, and the dashboard shows each call, or NO TRADE, plus how past calls did.

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

1. Six coded setups are backtested on 3 years of data for all 500 stocks. A setup is used only if
   its average result is at least +0.05R, where R is the risk from entry to stop.
2. Stocks that trigger an enabled setup on the latest bar become candidates.
3. Fundamentals and news are attached, and Gemini picks, explains, and may move the win probability by ±15 points.
4. A call is published only if risk-reward and expected result clear the thresholds in `stockkk/config.py`.
   Otherwise the horizon shows NO TRADE.
5. Open calls are graded each evening against real prices. A setup that underperforms live is switched off.

Tests: `.venv/bin/python -m pytest -q`
