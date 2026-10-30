import sqlite3
from datetime import datetime, timezone

from stockkk import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
  symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT, fetched_at TEXT, PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS data_status (symbol TEXT PRIMARY KEY, ok INTEGER, reason TEXT, checked_at TEXT);
CREATE TABLE IF NOT EXISTS fundamentals (
  symbol TEXT PRIMARY KEY, name TEXT, sector TEXT, pe REAL, roe REAL, debt_to_equity REAL,
  earnings_growth REAL, revenue_growth REAL, market_cap REAL, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS news (
  url TEXT PRIMARY KEY, symbol TEXT, title TEXT, source TEXT, published_at TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS setup_stats (
  setup TEXT PRIMARY KEY, horizon TEXT, generation TEXT, trades INTEGER, hit_rate REAL, avg_r REAL, max_dd_r REAL,
  is_avg_r REAL, oos_trades INTEGER, oos_hit_rate REAL, oos_avg_r REAL,
  live_trades INTEGER DEFAULT 0, live_hit_rate REAL, live_avg_r REAL,
  enabled INTEGER, disabled_reason TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY, created_at TEXT, horizon TEXT, symbol TEXT, name TEXT, direction TEXT,
  entry REAL, stop REAL, target REAL, rr REAL, hold_days INTEGER, trigger INTEGER,
  confidence REAL, expected_r REAL, setup TEXT, reasoning TEXT, technical TEXT, fundamental TEXT,
  news TEXT, invalidation TEXT, exit_note TEXT, data_as_of TEXT,
  status TEXT DEFAULT 'OPEN', closed_on TEXT, exit_price REAL, result_r REAL);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY, created_at TEXT, data_as_of TEXT, horizon TEXT, rank INTEGER, symbol TEXT, name TEXT,
  direction TEXT, entry REAL, stop REAL, target REAL, rr REAL, hold_days INTEGER, trigger INTEGER,
  setup TEXT, setup_proven INTEGER, win_prob REAL, expected_r REAL, ai_verdict TEXT, reasoning TEXT,
  invalidation TEXT, exit_note TEXT, recommended INTEGER);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, job TEXT, started_at TEXT, ok INTEGER, message TEXT);

CREATE TRIGGER IF NOT EXISTS recs_immutable
BEFORE UPDATE OF created_at, horizon, symbol, direction, entry, stop, target, rr, hold_days, trigger,
  confidence, expected_r, setup, reasoning, technical, fundamental, news, invalidation, data_as_of
ON recommendations
BEGIN SELECT RAISE(ABORT, 'published recommendations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS recs_no_delete BEFORE DELETE ON recommendations
BEGIN SELECT RAISE(ABORT, 'published recommendations are immutable'); END;
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")  # dashboard reads while the worker writes
    con.executescript(SCHEMA)
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def set_meta(con, key: str, value: str) -> None:
    con.execute("INSERT OR REPLACE INTO meta VALUES (?,?,?)", (key, value, now()))
    con.commit()


def get_meta(con, key: str):
    row = con.execute("SELECT value, updated_at FROM meta WHERE key=?", (key,)).fetchone()
    return (row["value"], row["updated_at"]) if row else (None, None)
