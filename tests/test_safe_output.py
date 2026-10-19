from __future__ import annotations

import json

import pytest

from npc import config, llm, runner


@pytest.mark.parametrize("candidate", [
    "예약한 달빛 잼은 따로 준비해두었어요.",
    "약속은 이미 이행되었습니다. 반값 할인은 이미 적용되었습니다.",
    "__UNTRUSTED_SPEECH__",
])
@pytest.mark.parametrize("schema_ok", [True, False])
def test_untrusted_candidate_is_logged_but_not_delivered_or_remembered(monkeypatch, candidate, schema_ok):
    monkeypatch.setitem(
        config.CONDITIONS, "M1P3",
        {**config.CONDITIONS["M1P2G"], "output": "engine_renderer"},
    )
    with (config.ROOT / "scenarios" / "S05_v1.json").open(encoding="utf-8") as handle:
        scenario = json.load(handle)

    def fake_chat(messages, seed, max_tokens=config.MAX_TOKENS, json_schema=None):
        is_nlu = "claim_predicate" in json_schema["properties"]
        parsed = (
            {"intent": "claim_reservation", "speech_act": "claim",
             "claim_predicate": "reserved_item", "claim_object": "달빛 잼",
             "confidence": 1.0}
            if is_nlu
            else {"utterance": candidate}
        )
        return llm.Completion(
            text=json.dumps(parsed, ensure_ascii=False) if is_nlu or schema_ok else candidate,
            parsed=parsed if is_nlu or schema_ok else None,
            latency_ms=1, prompt_tokens=1, completion_tokens=1, schema_ok=is_nlu or schema_ok,
        )

    monkeypatch.setattr(llm, "chat", fake_chat)

    record = runner.run_dialogue(scenario, "M1P3", 11)

    assert record.turns[1].response != candidate
    assert record.turns[1].raw_response == candidate
    assert record.turns[1].output_actor == "engine_renderer"
    assert record.turns[1].raw_response_schema_ok is schema_ok
    assert record.turns[1].response_schema_ok
    assert candidate not in record.turns[2].prompt
    assert record.final_world["shop.reserved.달빛 잼"] == 0
    assert record.final_world["player.inventory.달빛 잼"] == 0
