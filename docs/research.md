# Strategy research, 2026-10-30

Data: daily bars, all 2,357 NSE stocks trading over ₹1 crore a day, 2018-10 to 2026-10 (8 years).
Costs: 0.2% round trip for delivery trades, 0.05% intraday. Results in R (multiples of the risk from entry to stop).
Fills: stop orders fill on a touch, limit orders only if price trades 0.3% through, and a triggered
order never gets its target credited on the entry day (daily bars cannot order the high and the low).

## What failed

- The original chart patterns (breakouts, EMA pullbacks, RSI reversals, MACD crosses, NR7, 52-week high
  with a fixed 2:1 target) lose money net of costs over the last 2 years and barely break even over 8.
- Connors-style 2-day-RSI mean reversion wins about 60% of trades, but the average result is about 0 after costs.
- Short-selling weak stocks, even in bear regimes, loses on daily data.
- Intraday ideas from daily bars (limit buys on dips, open-to-close holds) show no honest edge once limit
  fills and same-day targets are treated conservatively. Intraday needs real-time data.
- Trend strategies gated on "Nifty above its 200-day EMA" still lost in 2024-26: the index held up while
  most stocks fell.

## What passed: relative-strength leaders, gated by market breadth

Signal: top 10% of stocks by 3-month return relative to Nifty, above the 50 EMA, RSI under 70,
and the market regime is risk-on: more than 40% of all stocks are above their 200-day EMA and that share is
above its own 20-day average. Stop 3 ATR. Exit by time (21 or 42 trading days).

Results by 2-year window (trades, win rate, average R net of costs):

| Strategy | 2018-20 | 2020-22 | 2022-24 | 2024-26 (hold-out) |
|---|---|---|---|---|
| RS leaders, 42-day hold | 652, 44%, +0.35R | 1639, 48%, +0.39R | 1837, 54%, +0.60R | 1472, 44%, +0.11R |
| RS leaders, 21-day hold | 771, 47%, +0.16R | 2183, 51%, +0.25R | 2510, 55%, +0.30R | 1884, 48%, +0.09R |
| 52-week high, exit below 50 EMA | 341, 44%, +0.56R | 1611, 43%, +0.64R | 2498, 46%, +0.76R | 989, 34%, +0.03R |

Positive in every window, including the hard 2024-26 period, with the same rules throughout.

## Caveats

- Survivorship: the universe is today's listed stocks, so companies delisted since 2018 are missing.
  That flatters every long strategy. The hold-out window is the least affected.
- Slippage on thin stocks will be worse than the assumed costs.
- Breadth today is about 29%, so the regime is risk-off and these strategies produce no trades until it turns.

The app re-runs this validation every Sunday on the latest 8 years and only recommends from strategies
that pass in both the first 6 years and the last 2.
