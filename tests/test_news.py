from stockkk import db, news

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Nifty hits record</title><link>https://x.com/a</link><pubDate>Thu, 29 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Bank stocks rally</title><link>https://x.com/b</link><pubDate>Thu, 29 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_and_dedupe(tmp_path):
    f = tmp_path / "feed.xml"
    f.write_text(RSS)
    con = db.connect(":memory:")
    rows = news.parse_feed(str(f), "Test", "TCS")
    assert rows[0][2] == "Nifty hits record" and rows[0][4].startswith("2026-10-29T10:00")
    assert news.save(con, rows) == 2
    assert news.save(con, rows) == 0


def test_nse_failure_still_fetches_rss(monkeypatch):
    con = db.connect(":memory:")
    monkeypatch.setattr(news, "nse_announcements", lambda s: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(news, "parse_feed", lambda u, s, sym: [("https://x/1", sym, "t", s, db.now(), db.now())])
    monkeypatch.setattr(news.time, "sleep", lambda s: None)
    assert news.fetch_symbol_news(con, "TCS", "Tata Consultancy Services Ltd.") == 1
