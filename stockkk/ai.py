"""Gemini ranks and explains pre-qualified candidates. It never sets prices.

Entry, stop and target come from coded setups. Gemini may only pick from the given
candidates, explain them, and nudge the win probability by at most MAX_AI_ADJ points.
"""
import json
import logging
import time

from pydantic import BaseModel

from stockkk import config

log = logging.getLogger(__name__)


class AIUnavailable(Exception):
    pass


class Pick(BaseModel):
    symbol: str
    confidence_adj: int
    reasoning: str
    technical: str
    fundamental: str
    news: str
    invalidation: str


class Reply(BaseModel):
    picks: list[Pick]
    no_trade_reason: str


RULES = """You are a cautious equity research analyst for the Indian stock market (NSE).
Hard rules:
- Use ONLY the numbers and facts in the input. Never invent prices, news, results or fundamentals.
- If a field is null, say it is unavailable. Data is delayed end-of-day.
- Never promise profits. Be specific and plain.
- Prefer NO TRADE over a weak or uncertain setup. Reject candidates with conflicting news,
  weak fundamentals (for long-term), overextended moves, or a hostile market backdrop.
"""

RANK_PROMPT = RULES + """
Horizon: {horizon}
Market context: {market}

Each candidate already has entry, stop, target and a backtested win probability from a coded setup.
Pick at most {max_picks} of them, best first. Return zero picks if none are good enough.
For each pick:
- confidence_adj: integer from -{max_adj} to {max_adj}, your adjustment to the backtested win probability
  (in percentage points) from news, fundamentals and market context.
- reasoning: 2-4 sentences on why this trade, now.
- technical / fundamental / news: one or two sentences each, citing the input numbers.
- invalidation: concrete conditions that cancel the idea (price levels, events).
no_trade_reason: if you return zero picks, one sentence why; otherwise an empty string.

Candidates (JSON):
{candidates}
"""

BRIEF_PROMPT = RULES + """
Write a short market brief (5-7 bullet points) for an Indian trader for the next session:
trend of Nifty and Bank Nifty, sector leaders and laggards, global cues, notable news, key risks.
Mention the as-of date of the data. Plain text bullets starting with "- ".

Market data (JSON): {overview}
Headlines: {headlines}
"""


def _client():
    if not config.GEMINI_API_KEY:
        raise AIUnavailable("GEMINI_API_KEY not set")
    from google import genai
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _generate(prompt: str, schema=None) -> str:
    from google.genai import types
    client = _client()
    cfg = types.GenerateContentConfig(temperature=0.2, **(
        {"response_mime_type": "application/json", "response_schema": schema} if schema else {}))
    for attempt in range(3):
        try:
            return client.models.generate_content(model=config.GEMINI_MODEL, contents=prompt, config=cfg).text
        except Exception as e:
            code = getattr(e, "code", None)
            log.warning("Gemini call failed (attempt %d): %s", attempt + 1, e)
            if code and code != 429 and code < 500:  # bad model, key or request: retrying will not help
                raise AIUnavailable(f"Gemini error {code}: {getattr(e, 'message', e)}") from e
            time.sleep(20 * (attempt + 1))
    raise AIUnavailable("Gemini did not respond after 3 attempts")


def validate(reply: Reply, symbols: set[str]) -> list[Pick]:
    """Drop picks outside the candidate list or with out-of-range adjustments (AE3)."""
    seen, picks = set(), []
    for p in reply.picks:
        if p.symbol not in symbols or p.symbol in seen:
            log.warning("Discarding AI pick %s: not in candidate list or duplicate", p.symbol)
            continue
        if abs(p.confidence_adj) > config.MAX_AI_ADJ:
            log.warning("Discarding AI pick %s: confidence_adj %d out of range", p.symbol, p.confidence_adj)
            continue
        seen.add(p.symbol)
        picks.append(p)
    return picks[: config.MAX_PICKS]


def rank(horizon: str, candidates: list[dict], market: dict) -> tuple[list[Pick], str]:
    prompt = RANK_PROMPT.format(horizon=horizon, market=json.dumps(market, default=str),
                                max_picks=config.MAX_PICKS, max_adj=config.MAX_AI_ADJ,
                                candidates=json.dumps(candidates, default=str))
    text = _generate(prompt, Reply)
    try:
        reply = Reply.model_validate_json(text)
    except Exception as e:
        raise AIUnavailable(f"Gemini returned invalid JSON: {e}") from e
    return validate(reply, {c["symbol"] for c in candidates}), reply.no_trade_reason


def market_brief(overview: dict, headlines: list[str]) -> str:
    return _generate(BRIEF_PROMPT.format(overview=json.dumps(overview, default=str),
                                         headlines=json.dumps(headlines[:25])))
