import pytest

from stockkk import ai, config

GOOD = dict(reasoning="r", technical="t", fundamental="f", news="n", invalidation="i")


def test_unknown_symbol_dropped():  # Covers AE3
    reply = ai.Reply(picks=[ai.Pick(symbol="TCS", confidence_adj=5, **GOOD),
                            ai.Pick(symbol="FAKE", confidence_adj=5, **GOOD)], no_trade_reason="")
    assert [p.symbol for p in ai.validate(reply, {"TCS"})] == ["TCS"]


def test_out_of_range_adjustment_dropped():
    reply = ai.Reply(picks=[ai.Pick(symbol="TCS", confidence_adj=40, **GOOD)], no_trade_reason="")
    assert ai.validate(reply, {"TCS"}) == []


def test_valid_reply_parses(monkeypatch):
    text = ai.Reply(picks=[ai.Pick(symbol="TCS", confidence_adj=-3, **GOOD)], no_trade_reason="").model_dump_json()
    monkeypatch.setattr(ai, "_generate", lambda p, s=None: text)
    picks, reason = ai.rank("swing", [{"symbol": "TCS"}], {})
    assert picks[0].confidence_adj == -3 and reason == ""


def test_invalid_json_is_unavailable(monkeypatch):
    monkeypatch.setattr(ai, "_generate", lambda p, s=None: "not json")
    with pytest.raises(ai.AIUnavailable):
        ai.rank("swing", [{"symbol": "TCS"}], {})


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(ai.AIUnavailable):
        ai._client()
