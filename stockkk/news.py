"""Market news and company announcements. Stores headlines only; Gemini reads them later."""
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser

from stockkk import db

log = logging.getLogger(__name__)

MARKET_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Economic Times Stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
}


def _iso(entry) -> str:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc).isoformat() if t else db.now()


def parse_feed(url: str, source: str, symbol: str | None) -> list[tuple]:
    f = feedparser.parse(url)
    return [(e.link, symbol, e.title, source, _iso(e), db.now()) for e in f.entries if e.get("link")]


def save(con, rows: list[tuple]) -> int:
    before = con.total_changes
    con.executemany("INSERT OR IGNORE INTO news VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    return con.total_changes - before


def fetch_market_news(con) -> int:
    n = 0
    for source, url in MARKET_FEEDS.items():
        try:
            n += save(con, parse_feed(url, source, None))
        except Exception as e:
            log.warning("feed %s failed: %s", source, e)
    return n


def nse_announcements(symbol: str) -> list[tuple]:
    from jugaad_data.nse import NSELive
    rows = []
    for a in NSELive().corporate_announcements(segment="equities", symbol=symbol)[:10]:
        title = f"{a.get('desc', '')}: {(a.get('attchmntText') or '')[:300]}"
        published = datetime.strptime(a["sort_date"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat()
        rows.append((a.get("attchmntFile") or f"nse:{a.get('seq_id')}", symbol, title, "NSE filing", published, db.now()))
    return rows


def fetch_symbol_news(con, symbol: str, name: str) -> int:
    """NSE filings first, then Google News. Each source fails on its own without stopping the other."""
    n = 0
    try:
        n += save(con, nse_announcements(symbol))
    except Exception as e:
        log.warning("NSE announcements failed for %s: %s", symbol, e)
    q = quote(f'"{name.replace(" Ltd.", "").replace(" Limited", "")}" share')
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        n += save(con, parse_feed(url, "Google News", symbol)[:15])
    except Exception as e:
        log.warning("Google News failed for %s: %s", symbol, e)
    time.sleep(0.5)  # be polite to free endpoints
    return n


def recent(con, symbol: str | None, days: int = 7, limit: int = 8) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = "SELECT title, source, published_at, url FROM news WHERE published_at >= ? AND "
    q += "symbol IS NULL" if symbol is None else "symbol = ?"
    params = (since,) if symbol is None else (since, symbol)
    return [dict(r) for r in con.execute(q + " ORDER BY published_at DESC LIMIT ?", (*params, limit))]
