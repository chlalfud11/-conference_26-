import builtins
import json
from pathlib import Path

import pytest

import abcd4_ledger as LG
import abcd4_runner as R
from npc import config, llm, runner
from npc.adapters import KIND_LABELS


def run_tool(monkeypatch, sid, call, kind="promised_discount"):
    for name in ("PERSONA", "PRICES", "INITIAL_STOCK"):
        monkeypatch.setattr(config, name, getattr(config, name))
    labels, opened, real_open, real_read = dict(KIND_LABELS), [], builtins.open, Path.read_text
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (opened.append(str(self)), real_read(self, *a, **k))[1])

    def chat(messages, seed, max_tokens=0, json_schema=None):
        if json_schema is runner.NLU_SCHEMA:
            parsed = {"claim_predicate": "none", "claim_object": ""}
        elif json_schema is R.TOOL_SCHEMA:
            parsed = {"call": call, "claim_type": kind}
        else:
            parsed = {"decision": "defer", "utterance": "ok"}
        return llm.Completion(json.dumps(parsed), 0, 0, 0, True, parsed)

    monkeypatch.setattr(llm, "chat", chat)
    R.install()
    try:
        sc, (rows, today) = R.scenarios(), LG.load()
        record = json.loads(R.run_dialogue4(sc[sid], "T-M1P0", 11, rows, today).to_json())
    finally:
        KIND_LABELS.clear()
        KIND_LABELS.update(labels)
    assert not [p for p in opened if "answer_key" in p]
    return record["turns"][-1], sc[sid], rows


@pytest.mark.parametrize("sid", ["A001v", "A001n", "A001d"])
def test_tool_returns_only_this_customers_rows_of_that_type(monkeypatch, sid):
    turn, scenario, rows = run_tool(monkeypatch, sid, True)
    account = LG.split_who(scenario["customer"])[1]
    expected = [LG.render(r) for r in rows if r["account"] == account and LG.matches("promised_discount", r)]
    assert turn["nlu"]["tool"]["result_rows"] == expected
    system = json.loads(turn["prompt"])[0]["content"]
    assert "[Tool result] lookup(promised_discount)" in system
    assert ("(no records)" in system) == (not expected)
    others = [LG.render(r) for r in rows if r["account"] != account]
    assert not any(o in system for o in others)
    assert "verified:" not in turn["prompt"] and "contradicting" not in turn["prompt"]
    assert "Policy decision" not in system


def test_no_call_means_no_tool_result(monkeypatch):
    turn, _, _ = run_tool(monkeypatch, "A001v", False)
    assert turn["nlu"]["tool"]["call"] is False and turn["nlu"]["tool"]["result_rows"] == []
    assert "[Tool result]" not in json.loads(turn["prompt"])[0]["content"]
    assert turn["decision_actor"] == "slm"
