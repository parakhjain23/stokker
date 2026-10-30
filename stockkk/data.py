"""Free, delayed EOD market data: yfinance first, NSE (jugaad-data) as fallback.

Nothing here invents a value: bad or missing data is dropped and recorded in data_status.
"""
import logging
import time
import warnings
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from stockkk import config, db

warnings.filterwarnings("ignore", module="yfinance")
warnings.filterwarnings("ignore", module="jugaad_data")
log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

COLS = ["open", "high", "low", "close", "volume"]
MAX_GAP = 0.21          # NSE circuit limits cap most daily moves at 20%
MAX_INDEX_MOVE = 0.05   # a >21% gap with a calm index is treated as bad data


EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
INDUSTRY_LIST = "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"


def refresh_universe(max_age_days: int = 7) -> None:
    """All NSE stocks in the normal (EQ) series, with industry where NSE publishes it.
    Refreshed weekly; on failure the previous file is kept."""
    path = config.UNIVERSE_CSV
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return
    try:
        import io
        import urllib.request
        def get(url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return pd.read_csv(io.BytesIO(urllib.request.urlopen(req, timeout=30).read()))
        eq = get(EQUITY_LIST)
        eq.columns = eq.columns.str.strip()
        eq = eq[eq["SERIES"].str.strip() == "EQ"].rename(columns={"SYMBOL": "symbol", "NAME OF COMPANY": "name"})
        ind = get(INDUSTRY_LIST).rename(columns={"Symbol": "symbol", "Industry": "industry"})
        df = eq[["symbol", "name"]].merge(ind[["symbol", "industry"]], on="symbol", how="left")
        df["industry"] = df["industry"].fillna("Other")
        df.to_csv(path, index=False)
        log.info("universe refreshed: %d stocks", len(df))
    except Exception as e:
        log.warning("universe refresh failed, keeping previous list: %s", e)


def universe() -> pd.DataFrame:
    if not config.UNIVERSE_CSV.exists():
        refresh_universe()
    return pd.read_csv(config.UNIVERSE_CSV)


def history_counts(con) -> dict[str, int]:
    return dict(con.execute("SELECT symbol, COUNT(*) FROM prices GROUP BY symbol").fetchall())


def yahoo(symbol: str) -> str:
    return symbol if symbol.startswith("^") or "=" in symbol else f"{symbol}.NS"


def clean(df: pd.DataFrame, index_ret: pd.Series | None = None) -> tuple[pd.DataFrame, str | None]:
    """Drop impossible rows and suspicious gaps. Returns (clean df, reason if rows were dropped)."""
    if df.empty:
        return df, "no data returned"
    df = df.dropna(subset=["open", "high", "low", "close"])
    bad = (df[["open", "high", "low", "close"]] <= 0).any(axis=1) | (df["high"] < df["low"])
    df = df[~bad]
    ret = df["close"].pct_change()
    calm = index_ret.reindex(df.index).abs().fillna(0) < MAX_INDEX_MOVE if index_ret is not None else True
    gap = (ret.abs() > MAX_GAP) & calm
    n = int(bad.sum() + gap.sum())
    return df[~gap], (f"dropped {n} bad rows" if n else None)


def _normalize_yf(raw: pd.DataFrame) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=COLS)
    df = raw.rename(columns=str.lower)[COLS].dropna(how="all")
    df.index = pd.to_datetime(df.index).date
    return df


def _fallback_nse(symbol: str, period: str) -> pd.DataFrame:
    from jugaad_data.nse import stock_df
    days = {"3y": 3 * 365, "1y": 365}.get(period, 31)
    raw = stock_df(symbol=symbol, from_date=date.today() - timedelta(days=days),
                   to_date=date.today(), series="EQ")
    df = raw.rename(columns=str.lower)
    # jugaad returns IST midnight as UTC (previous day 18:30); shift back to the trading date
    df.index = (pd.to_datetime(df["date"]) + pd.Timedelta(hours=5, minutes=30)).dt.date
    return df[COLS].sort_index()


def _download(tickers: list[str], period: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            return yf.download(tickers, period=period, group_by="ticker", auto_adjust=False,
                               progress=False, threads=True)
        except Exception as e:  # throttling or network
            log.warning("yfinance download failed (%s), retrying", e)
            time.sleep(5 * (attempt + 1))
    return pd.DataFrame()


def drop_partial_bar(df: pd.DataFrame, now_ist: datetime | None = None) -> pd.DataFrame:
    """Before 16:00 IST today's bar is incomplete, so it is not stored."""
    now_ist = now_ist or datetime.now(IST)
    if now_ist.hour < 16:
        return df[[d != now_ist.date() for d in df.index]]
    return df


def store(con, symbol: str, df: pd.DataFrame, source: str) -> None:
    fetched = db.now()
    con.executemany(
        "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?,?)",
        [(symbol, str(d), r.open, r.high, r.low, r.close, r.volume, source, fetched)
         for d, r in df.iterrows()])


def set_status(con, symbol: str, ok: bool, reason: str | None) -> None:
    con.execute("INSERT OR REPLACE INTO data_status VALUES (?,?,?,?)", (symbol, int(ok), reason, db.now()))


def fetch_prices(con, symbols: list[str], period: str, use_fallback: bool = True) -> dict:
    """Fetch and store daily bars. Returns {'ok': n, 'failed': [symbols]}."""
    raw_idx = _download(["^NSEI"], period)
    idx = _normalize_yf(raw_idx["^NSEI"] if not raw_idx.empty else raw_idx)
    index_ret = pd.Series(idx["close"].pct_change().values, index=idx.index) if not idx.empty else None
    ok, failed = 0, []
    for i in range(0, len(symbols), 100):
        chunk = symbols[i:i + 100]
        raw = _download([yahoo(s) for s in chunk], period)
        for s in chunk:
            try:
                df = _normalize_yf(raw[yahoo(s)]) if not raw.empty else pd.DataFrame(columns=COLS)
            except KeyError:
                df = pd.DataFrame(columns=COLS)
            source = "yahoo (delayed)"
            if df.empty and use_fallback and not s.startswith("^") and "=" not in s:
                try:
                    df, source = _fallback_nse(s, period), "nse (delayed)"
                except Exception as e:
                    log.warning("NSE fallback failed for %s: %s", s, e)
            df = drop_partial_bar(df)
            df, reason = clean(df, None if s.startswith("^") or "=" in s else index_ret)
            if df.empty:
                failed.append(s)
                set_status(con, s, False, reason or "no data")
                continue
            store(con, s, df, source)
            set_status(con, s, True, reason)
            ok += 1
        con.commit()
    return {"ok": ok, "failed": failed}


def load_prices(con, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    q = "SELECT symbol, date, open, high, low, close, volume FROM prices"
    params: tuple = ()
    if symbols:
        q += f" WHERE symbol IN ({','.join('?' * len(symbols))})"
        params = tuple(symbols)
    df = pd.read_sql_query(q + " ORDER BY symbol, date", con, params=params)
    df["date"] = pd.to_datetime(df["date"])
    return {s: g.drop(columns="symbol").set_index("date") for s, g in df.groupby("symbol")}


def fundamentals(con, symbol: str, max_age_days: int = 7) -> dict:
    """Cached yfinance fundamentals. Missing fields stay None (shown as unavailable)."""
    row = con.execute("SELECT * FROM fundamentals WHERE symbol=?", (symbol,)).fetchone()
    if row and datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(days=max_age_days):
        return dict(row)
    try:
        info = yf.Ticker(yahoo(symbol)).info or {}
    except Exception as e:
        log.warning("fundamentals failed for %s: %s", symbol, e)
        return dict(row) if row else {"symbol": symbol}
    f = {
        "symbol": symbol, "name": info.get("longName"), "sector": info.get("sector"),
        "pe": info.get("trailingPE"), "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"), "earnings_growth": info.get("earningsQuarterlyGrowth"),
        "revenue_growth": info.get("revenueGrowth"), "market_cap": info.get("marketCap"),
        "fetched_at": db.now(),
    }
    con.execute("INSERT OR REPLACE INTO fundamentals VALUES (:symbol,:name,:sector,:pe,:roe,:debt_to_equity,"
                ":earnings_growth,:revenue_growth,:market_cap,:fetched_at)", f)
    con.commit()
    return f
