import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "stockkk.db"))
UNIVERSE_CSV = ROOT / "data" / "universe.csv"
MIN_TRADED_VALUE = 1e7     # skip stocks trading under ₹1 crore a day (20-day average)
AI_BATCH = 20              # candidates per Gemini call

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

HORIZONS = ("intraday", "swing", "longterm")
MIN_RR = {"intraday": 1.0, "swing": 0.5, "longterm": 1.0}  # only for setups with a fixed target
MIN_EXPECTED_R = 0.05      # publish only if expected R-multiple after AI adjustment beats this
BREADTH_MIN = 0.40         # trend strategies trade only when >40% of stocks are above their 200-day average
MAX_AI_ADJ = 15            # Gemini may move win probability by at most this many points
MIN_BACKTEST_TRADES = 200   # in-sample
MIN_OOS_TRADES = 100        # out-of-sample (last 2 years)
MIN_WIN_PROB = 0.40         # hide and never recommend matches below this win probability
MIN_BACKTEST_AVG_R = 0.02   # net of costs, required in BOTH the in-sample and the out-of-sample window
OOS_YEARS = 2               # hold-out window at the end of the backtest
MIN_LIVE_TRADES = 30       # auto-disable check needs at least this many live calls
MIN_LIVE_HIT_RATE = 0.35
BLEND_AFTER = 20           # blend live stats into confidence after this many live calls
BACKTEST_PERIOD = "8y"      # long enough to cover several market regimes

# Yahoo symbols -> display name. GIFT Nifty is not on Yahoo, so it is shown as unavailable.
INDICES = {
    "^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "^BSESN": "Sensex", "^CNXIT": "Nifty IT",
    "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma", "^CNXFMCG": "Nifty FMCG",
    "^CNXMETAL": "Nifty Metal", "^INDIAVIX": "India VIX",
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^N225": "Nikkei 225",
    "^HSI": "Hang Seng", "CL=F": "Crude Oil", "GC=F": "Gold", "INR=X": "USD/INR",
}
