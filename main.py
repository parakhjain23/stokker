"""Embarko entrypoint: Streamlit dashboard plus GET /tasks/<job> routes that Embarko's schedules call."""
import logging
import os
import queue
import secrets
import threading
from pathlib import Path

data_dir = os.environ.get("DATA_DIR")
if data_dir:
    os.environ.setdefault("DB_PATH", str(Path(data_dir) / "stockkk.db"))
    import yfinance
    yfinance.set_tz_cache_location(str(Path(data_dir) / "yf-cache"))  # the image's home dir is read-only

from streamlit.web import cli as stcli  # noqa: E402
from streamlit.web.server.starlette import starlette_app  # noqa: E402
from stockkk import worker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
_orig_health = starlette_app.create_health_routes
_queue: "queue.Queue[str]" = queue.Queue()


def _runner():  # ponytail: one job at a time; 256MB is not enough to run two scans together
    while True:
        job = _queue.get()
        try:
            worker.JOBS[job]()
        except Exception:
            logging.exception("%s crashed", job)


threading.Thread(target=_runner, daemon=True).start()


def _health_routes(runtime, base_url):
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def task(request):
        if request.headers.get("authorization") != "Bearer " + os.environ.get("CRON_SECRET", secrets.token_hex()):
            return PlainTextResponse("unauthorized", 401)
        job = request.path_params["job"]
        if job not in worker.JOBS:
            return PlainTextResponse("no such job", 404)
        _queue.put(job)
        return PlainTextResponse(f"{job} queued", 202)  # jobs can take >5 min: answer now, work in background

    return [Route("/tasks/{job}", task, methods=["GET"])] + _orig_health(runtime, base_url)


starlette_app.create_health_routes = _health_routes

port = os.environ.get("PORT", "8501")
stcli.main(["run", "stockkk/dashboard.py", "--server.port", port, "--server.address", "0.0.0.0",
            "--server.headless", "true", "--browser.gatherUsageStats", "false"])
