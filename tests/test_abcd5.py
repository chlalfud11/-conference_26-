import builtins
import csv
import json
import re
from pathlib import Path

import pytest

import abcd4_ledger as LG
import abcd4_runner as R
import abcd5_heldout as H
from npc import config, llm, runner
from npc.adapters import KIND_LABELS

ROOT = Path(__file__).resolve().parent.parent
HSCEN = ROOT / "scenarios_abcd5h"
HKEY = ROOT / "answer_key_abcd5h" / "answer_key.csv"
HLEDGER = ROOT / "ledger_abcd5h" / "shop_ledger.csv"
FORBIDDEN = {"truth_predicate", "evidence", "expected_decision", "scored", "kind", "attack", "ledger_record"}

heldout = pytest.mark.skipif(not HKEY.exists(), reason="run ABCD4_SET=heldout python3 abcd4_build.py build first")


def scenarios(folder):
    return {p.stem: json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))}


@heldout
def test_heldout_disjoint_from_v4():
    v4 = {s["source"]["convo_id"] for s in scenarios(ROOT / "scenarios_abcd").values()}
    held = {s["source"]["convo_id"] for s in scenarios(HSCEN).values()}
    assert held and not held & v4
    assert {s["source"]["split"] for s in scenarios(HSCEN).values()} <= {"dev", "test"}


@heldout
def test_heldout_exclusions_and_no_answer_fields():
    for sid, s in scenarios(HSCEN).items():
        assert not FORBIDDEN & set(s) and all(not FORBIDDEN & set(t) for t in s["turns"]), sid
        assert not any(H.excluded(t["player"]) for t in s["turns"]), sid


@heldout
def test_heldout_names_only_speaker_and_lookup_matches_key():
    sc = scenarios(HSCEN)
    names = {LG.split_who(s["customer"])[0] for s in sc.values()}
    assert len(names) == len(sc)
    for sid, s in sc.items():
        said = {n for n in names for t in s["turns"] if re.search(rf"\b{re.escape(n)}\b", t["player"])}
        assert said <= {LG.split_who(s["customer"])[0]}, sid
    with HLEDGER.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with HKEY.open(newline="") as handle:
        key = [k for k in csv.DictReader(handle) if int(k["turn"]) == len(sc[k["scenario_id"]]["turns"])]
    assert len(key) == len(sc)
    assert all(LG.lookup(rows, LG.split_who(sc[k["scenario_id"]]["customer"])[1], k["truth_predicate"],
                         sc[k["scenario_id"]]["turns"][-1]["date"]) == k["evidence"] for k in key)


def run_with(monkeypatch, sid, asserts):
    for name in ("PERSONA", "PRICES", "INITIAL_STOCK"):
        monkeypatch.setattr(config, name, getattr(config, name))
    labels, opened, real_open, real_read = dict(KIND_LABELS), [], builtins.open, Path.read_text
    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: (opened.append(str(self)), real_read(self, *a, **k))[1])

    def chat(messages, seed, max_tokens=0, json_schema=None):
        if json_schema is runner.NLU_SCHEMA:
            parsed = {"claim_predicate": "none", "claim_object": ""}
        elif json_schema is R.REVERIFY_SCHEMA:
            parsed = {"asserts": asserts}
        else:
            parsed = {"utterance": "ok"}
        return llm.Completion(json.dumps(parsed), 0, 0, 0, True, parsed)

    monkeypatch.setattr(llm, "chat", chat)
    R.install()
    try:
        sc, (rows, today) = R.scenarios(), LG.load()
        record = json.loads(R.run_dialogue4(sc[sid], "F-M1P1RV", 11, rows, today).to_json())
    finally:
        KIND_LABELS.clear()
        KIND_LABELS.update(labels)
    assert not [p for p in opened if "answer_key" in p]
    return record["turns"][-1]


@pytest.mark.parametrize("sid, asserts, expected", [
    ("A001v", True, "accept_as_belief"), ("A001n", True, "request_evidence"), ("A001d", True, "dispute"),
    ("A001v", False, "request_evidence"),
])
def test_reverify_recovers_missed_claim(monkeypatch, sid, asserts, expected):
    turn = run_with(monkeypatch, sid, asserts)
    assert turn["decision"] == expected
    assert turn["nlu"]["reverify"]["candidates"][0] == "promised_discount"
    assert turn["nlu"]["reverify"]["chosen"] == ("promised_discount" if asserts else None)
    assert "verified:" not in turn["prompt"]
