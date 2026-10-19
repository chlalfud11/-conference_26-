import builtins
import csv
import io
import json
import re
from datetime import date
from pathlib import Path

import pytest

import abcd4_ledger as LG
import abcd4_runner as R
from npc import config, llm, runner
from npc.adapters import KIND_LABELS

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios_abcd4"
KEY = ROOT / "answer_key_abcd4" / "answer_key.csv"
FORBIDDEN = {"truth_predicate", "evidence", "expected_decision", "scored", "kind", "attack", "ledger_record",
             "contradicts_state", "initial_facts", "forbidden_assertions"}

pytestmark = pytest.mark.skipif(not KEY.exists(), reason="run python3 abcd4_build.py build first")


def scenarios():
    return {p.stem: json.loads(p.read_text()) for p in sorted(SCEN.glob("*.json"))}


def key_rows():
    with KEY.open(newline="") as handle:
        return list(csv.DictReader(handle))


def keys_of(value):
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def test_no_answer_fields():
    sc = scenarios()
    assert len(sc) == 252
    assert {sid: keys_of(s) & FORBIDDEN for sid, s in sc.items() if keys_of(s) & FORBIDDEN} == {}


def test_unique_identity():
    rows, _ = LG.load()
    owners = {}
    for r in rows:
        owners.setdefault(r["customer"], set()).add(r["account"])
    assert all(len(a) == 1 for a in owners.values())
    accounts = [LG.split_who(s["customer"])[1] for s in scenarios().values()]
    names = [LG.split_who(s["customer"])[0] for s in scenarios().values()]
    assert len(set(accounts)) == len(set(names)) == 252


def test_utterances_name_only_their_speaker():
    sc = scenarios()
    names = {LG.split_who(s["customer"])[0] for s in sc.values()}
    for sid, s in sc.items():
        own = LG.split_who(s["customer"])[0]
        said = {n for n in names for t in s["turns"] if re.search(rf"\b{re.escape(n)}\b", t["player"])}
        assert said <= {own}, (sid, said)


def test_pairs():
    sc, (rows, _) = scenarios(), LG.load()
    claims = {k["scenario_id"]: k for k in key_rows() if int(k["turn"]) == len(sc[k["scenario_id"]]["turns"])}
    for s in sorted({sid[:-1] for sid in sc}):
        v, n, d = (sc[f"{s}{x}"] for x in "vnd")
        assert len(v["turns"]) == len(n["turns"]) == len(d["turns"])
        assert v["turns"][-1]["date"] == n["turns"][-1]["date"] == d["turns"][-1]["date"]
        assert all("date" not in t for t in v["turns"][:-1])
        pred = claims[f"{s}v"]["truth_predicate"]
        acct = {x: LG.split_who(sc[f"{s}{x}"]["customer"])[1] for x in "vnd"}
        stated = date.fromisoformat(v["turns"][-1]["date"])
        assert [r for r in rows if r["account"] == acct["v"] and LG.matches(pred, r) and r["date"] == str(stated)]
        assert not [r for r in rows if r["account"] == acct["n"] and LG.matches(pred, r)]
        gaps = [(stated - date.fromisoformat(r["date"])).days for r in rows if r["account"] == acct["d"] and LG.matches(pred, r)]
        assert gaps and min(gaps) >= 14, (s, gaps)


def test_ledger_lookup_matches_answer_key():
    sc, (rows, _) = scenarios(), LG.load()
    claims = [k for k in key_rows() if int(k["turn"]) == len(sc[k["scenario_id"]]["turns"])]
    assert len(claims) == 252
    got = [LG.lookup(rows, LG.split_who(sc[k["scenario_id"]]["customer"])[1], k["truth_predicate"],
                     sc[k["scenario_id"]]["turns"][-1]["date"]) == k["evidence"] for k in claims]
    assert sum(got) == 252


def fake_chat(messages, seed, max_tokens=0, json_schema=None):
    if json_schema is runner.NLU_SCHEMA:
        parsed = {"claim_predicate": "promised_discount", "claim_object": "promo code"}
    elif json_schema is runner.DECIDE_SCHEMA:
        parsed = {"decision": "request_evidence", "utterance": "Do you have the code?"}
    else:
        parsed = {"utterance": "Let me check."}
    return llm.Completion(json.dumps(parsed), 0, 0, 0, True, parsed)


@pytest.mark.parametrize("condition", list(R.CONDITIONS))
def test_runner_isolated_and_prompt(monkeypatch, condition):
    for module in ("abcd4_runner.py", "abcd_live4.py", "abcd4_ledger.py", "ledger_vdb.py"):
        source = (ROOT / module).read_text()
        assert "answer_key_abcd4" not in source, module
        assert not re.search(r"^\s*(import|from)\s+abcd4_build\b", source, re.M), module
    opened, real_open, real_read = [], builtins.open, Path.read_text
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (opened.append(str(self)), real_read(self, *a, **k))[1])
    for name in ("PERSONA", "PRICES", "INITIAL_STOCK"):
        monkeypatch.setattr(config, name, getattr(config, name))
    labels = dict(KIND_LABELS)
    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(R.ledger_vdb, "search4", lambda q, k=5: [{"text": "2019-11-01 | Other Person (otherperson) | promo code NGAAAAAA issued, x"}])
    R.install()
    try:
        sc, (rows, today) = R.scenarios(), LG.load()
        record = json.loads(R.run_dialogue4(sc["A002d"], condition, 11, rows, today).to_json())
    finally:
        KIND_LABELS.clear()
        KIND_LABELS.update(labels)
    assert not [p for p in opened if "answer_key" in p]
    prompts = [t["prompt"] for t in record["turns"]]
    assert all("verified:" not in p for p in prompts)
    assert "Customer-stated date: " in prompts[-1] and "Customer-stated date" not in prompts[0]
    assert ("Ledger search results" in prompts[-1]) == condition.startswith("S")
    assert record["turns"][-1]["evidence"] == "contradicting"
    if condition == "F-M1P1":
        assert record["turns"][-1]["decision"] == "dispute"
