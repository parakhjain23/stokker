import pytest

from stockkk import ai, config

GOOD = dict(verdict="TAKE", reasoning="r", technical="t", fundamental="f", news="n", invalidation="i")


def _reply(*items):
    return ai.Reply(assessments=[ai.Assessment(symbol=s, confidence_adj=adj, **GOOD) for s, adj in items])


def test_unknown_symbol_dropped():  # Covers AE3
    assert list(ai.validate(_reply(("TCS", 5), ("FAKE", 5)), {"TCS"})) == ["TCS"]


def test_out_of_range_adjustment_dropped():
    assert ai.validate(_reply(("TCS", 40)), {"TCS"}) == {}


def test_verdict_normalized():
    r = _reply(("TCS", 0))
    r.assessments[0].verdict = "maybe"
    assert ai.validate(r, {"TCS"})["TCS"].verdict == "SKIP"


def test_assess_batches_every_candidate(monkeypatch):
    monkeypatch.setattr(config, "AI_BATCH", 2)
    calls = []

    def fake(prompt, schema=None):
        syms = [s for s in "ABCDE" if f'"symbol": "{s}"' in prompt]
        calls.append(syms)
        return _reply(*[(s, 1) for s in syms]).model_dump_json()
    monkeypatch.setattr(ai, "_generate", fake)
    out = ai.assess("swing", [{"symbol": s} for s in "ABCDE"], {})
    assert sorted(out) == list("ABCDE") and len(calls) == 3


def test_invalid_json_is_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_generate", lambda p, s=None: "not json")
    with pytest.raises(ai.AIUnavailable):
        ai.assess("swing", [{"symbol": "TCS"}], {})


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(ai.AIUnavailable):
        ai._client()
