"""24/7 research worker.

  python -m stockkk.worker              # run on schedule (IST)
  python -m stockkk.worker --once eod   # run one job now: eod | premarket | news | backtest
"""
import argparse
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from stockkk import config, data, db, engine, news, setups

log = logging.getLogger("stockkk")


def _job(name):
    def wrap(fn):
        def run():
            con = db.connect()
            started = db.now()
            try:
                msg = fn(con)
                con.execute("INSERT INTO runs (job, started_at, ok, message) VALUES (?,?,1,?)", (name, started, str(msg)))
                log.info("%s done: %s", name, msg)
            except Exception as e:  # one failed job must not stop the scheduler
                log.exception("%s failed", name)
                con.execute("INSERT INTO runs (job, started_at, ok, message) VALUES (?,?,0,?)", (name, started, repr(e)))
            con.commit()
            con.close()
        run.__name__ = name
        return run
    return wrap


def _backtest(con):
    frames = engine.build_frames(data.load_prices(con), data.universe()["symbol"])
    return {r["setup"]: (r["trades"], r["hit_rate"] and round(r["hit_rate"], 3), r["avg_r"] and round(r["avg_r"], 3))
            for r in setups.run_backtest(con, frames)}


@_job("eod")
def job_eod(con):
    data.refresh_universe()
    counts = data.history_counts(con)
    syms = list(data.universe()["symbol"])
    new = [s for s in syms if counts.get(s, 0) < 200]   # new stocks need full history for the backtest
    old = [s for s in syms if counts.get(s, 0) >= 200]
    fetched = {"ok": 0, "failed": []}
    for group, period in ((new, config.BACKTEST_PERIOD), (old, "1mo")):
        if group:
            r = data.fetch_prices(con, group, period)
            fetched["ok"] += r["ok"]
            fetched["failed"] += r["failed"]
    idx_period = "1mo" if counts.get("^NSEI", 0) >= 200 else config.BACKTEST_PERIOD
    data.fetch_prices(con, list(config.INDICES), idx_period, use_fallback=False)
    if new:
        _backtest(con)  # new stocks change the backtest sample
    news.fetch_market_news(con)
    prices = data.load_prices(con)
    graded = setups.grade_open(con, prices)
    setups.update_live_stats(con)
    if not new and not con.execute("SELECT 1 FROM setup_stats").fetchone():
        _backtest(con)
    summary = engine.run(con, prices)
    engine.refresh_brief(con)
    return {"prices_ok": fetched["ok"], "failed": len(fetched["failed"]), "graded": graded, **summary}


@_job("premarket")
def job_premarket(con):
    data.fetch_prices(con, list(config.INDICES), "1mo", use_fallback=False)
    n = news.fetch_market_news(con)
    engine.refresh_brief(con)
    return f"{n} new headlines"


@_job("news")
def job_news(con):
    return f"{news.fetch_market_news(con)} new headlines"


@_job("backtest")
def job_backtest(con):
    return _backtest(con)


JOBS = {"eod": job_eod, "premarket": job_premarket, "news": job_news, "backtest": job_backtest}


def eod_is_stale(con) -> bool:
    row = con.execute("SELECT MAX(started_at) FROM runs WHERE job='eod' AND ok=1").fetchone()[0]
    return not row or datetime.fromisoformat(row) < datetime.now(datetime.fromisoformat(row).tzinfo) - timedelta(hours=20)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--once", choices=JOBS)
    args = p.parse_args()
    if args.once:
        JOBS[args.once]()
        return
    con = db.connect()
    if eod_is_stale(con):
        log.info("EOD data is stale; running catch-up")
        job_eod()
    con.close()
    s = BlockingScheduler(timezone="Asia/Kolkata")
    s.add_job(job_eod, "cron", day_of_week="mon-fri", hour=16, minute=30)
    s.add_job(job_premarket, "cron", day_of_week="mon-fri", hour=8, minute=30)
    s.add_job(job_news, "cron", minute=5)
    s.add_job(job_backtest, "cron", day_of_week="sun", hour=10)
    log.info("worker started; jobs: %s", [j.name for j in s.get_jobs()])
    s.start()


if __name__ == "__main__":
    main()
