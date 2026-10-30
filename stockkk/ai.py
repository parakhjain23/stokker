"""Gemini judges every pre-qualified candidate. It never sets prices.

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


class Assessment(BaseModel):
    symbol: str
    verdict: str          # TAKE or SKIP
    confidence_adj: int
    reasoning: str
    technical: str
    fundamental: str
    news: str
    invalidation: str


class Reply(BaseModel):
    assessments: list[Assessment]


RULES = """You are a cautious equity research analyst for the Indian stock market (NSE).
Hard rules:
- Use ONLY the numbers and facts in the input. Never invent prices, news, results or fundamentals.
- If a field is null, say it is unavailable. Data is delayed end-of-day.
- Never promise profits. Be specific and plain.
- Prefer NO TRADE over a weak or uncertain setup. Reject candidates with conflicting news,
  weak fundamentals (for long-term), overextended moves, or a hostile market backdrop.
"""

ASSESS_PROMPT = RULES + """
Horizon: {horizon}
Market context: {market}

Each candidate already has entry, stop, target and a backtested win probability from a coded setup.
"setup_proven" is false when that setup has no proven edge in the backtest: be extra sceptical.
Assess EVERY candidate, one entry per symbol:
- verdict: "TAKE" only for a strong, clean setup you would act on; otherwise "SKIP".
- confidence_adj: integer from -{max_adj} to {max_adj}, your adjustment to the backtested win probability
  (in percentage points) from news, fundamentals and market context.
- reasoning: 1-3 sentences on why take or skip, now.
- technical / fundamental / news: one sentence each, citing the input numbers.
- invalidation: concrete conditions that cancel the idea (price levels, events).

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


def validate(reply: Reply, symbols: set[str]) -> dict[str, Assessment]:
    """Drop assessments outside the candidate list or with out-of-range adjustments (AE3)."""
    out = {}
    for a in reply.assessments:
        if a.symbol not in symbols or a.symbol in out:
            log.warning("Discarding AI assessment %s: not in candidate list or duplicate", a.symbol)
            continue
        if abs(a.confidence_adj) > config.MAX_AI_ADJ:
            log.warning("Discarding AI assessment %s: confidence_adj %d out of range", a.symbol, a.confidence_adj)
            continue
        a.verdict = "TAKE" if a.verdict.strip().upper() == "TAKE" else "SKIP"
        out[a.symbol] = a
    return out


def assess(horizon: str, candidates: list[dict], market: dict) -> dict[str, Assessment]:
    """Gemini judges every candidate, in batches. Candidates it skips get no assessment."""
    out = {}
    for i in range(0, len(candidates), config.AI_BATCH):
        batch = candidates[i:i + config.AI_BATCH]
        prompt = ASSESS_PROMPT.format(horizon=horizon, market=json.dumps(market, default=str),
                                      max_adj=config.MAX_AI_ADJ, candidates=json.dumps(batch, default=str))
        text = _generate(prompt, Reply)
        try:
            reply = Reply.model_validate_json(text)
        except Exception as e:
            raise AIUnavailable(f"Gemini returned invalid JSON: {e}") from e
        out |= validate(reply, {c["symbol"] for c in batch})
    return out


def market_brief(overview: dict, headlines: list[str]) -> str:
    return _generate(BRIEF_PROMPT.format(overview=json.dumps(overview, default=str),
                                         headlines=json.dumps(headlines[:25])))
