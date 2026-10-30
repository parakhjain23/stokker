import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "stockkk.db"))
UNIVERSE_CSV = ROOT / "data" / "nifty500.csv"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

HORIZONS = ("intraday", "swing", "longterm")
MIN_RR = {"intraday": 2.0, "swing": 2.0, "longterm": 1.5}
MIN_EXPECTED_R = 0.10      # publish only if expected R-multiple after AI adjustment beats this
MAX_AI_ADJ = 15            # Gemini may move win probability by at most this many points
MAX_CANDIDATES = 15        # per horizon, sent to Gemini
MAX_PICKS = 5              # per horizon, published
MIN_BACKTEST_TRADES = 30
MIN_LIVE_TRADES = 30       # auto-disable check needs at least this many live calls
MIN_LIVE_HIT_RATE = 0.35
BLEND_AFTER = 20           # blend live stats into confidence after this many live calls
BACKTEST_PERIOD = "3y"

# Yahoo symbols -> display name. GIFT Nifty is not on Yahoo, so it is shown as unavailable.
INDICES = {
    "^NSEI": "Nifty 50", "^NSEBANK": "Bank Nifty", "^BSESN": "Sensex", "^CNXIT": "Nifty IT",
    "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma", "^CNXFMCG": "Nifty FMCG",
    "^CNXMETAL": "Nifty Metal", "^INDIAVIX": "India VIX",
    "^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^N225": "Nikkei 225",
    "^HSI": "Hang Seng", "CL=F": "Crude Oil", "GC=F": "Gold", "INR=X": "USD/INR",
}
