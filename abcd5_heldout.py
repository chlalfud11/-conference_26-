"""ABCD v5 held-out sources (.omo/plans/abcd-v5-reverify.md).

Usage: python3 abcd5_heldout.py <abcd_v1.1.json.gz>
Draws claim sources from the ABCD dev and test splits (both unused by v4) with the v4 selection rules (abcd_build.claim_of), after
excluding utterances with a full calendar date or a denied purchase, and writes v3-format scenarios and
ledger rows to results/abcd5/heldout_src/ for abcd4_build (ABCD4_SET=heldout).
"""
import gzip
import json
import random
import re
import sys
from pathlib import Path

import abcd_build
import abcd_ledger

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd5" / "heldout_src"
FULL_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|"
                       r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}(st|nd|rd|th)?,? \d{4}\b", re.I)
DENIAL = re.compile(r"\b(did ?n[o']?t|never)\b.{0,20}\b(buy|bought|order|ordered|purchase|purchased|make)\b", re.I)


def excluded(text):
    return bool(text and (FULL_DATE.search(text) or DENIAL.search(text)))


def main(gz):
    data = json.load(gzip.open(gz))
    v4_ids = {json.loads(p.read_text())["source"]["convo_id"] for p in (ROOT / "scenarios_abcd").glob("*v.json")}
    pool, dropped = {}, {"overlap": 0, "full_date_or_denial": 0}
    split_of = {c["convo_id"]: split for split in ("dev", "test") for c in data[split]}
    for predicate, text, greeting, convo in abcd_build.candidates(data["dev"] + data["test"]):
        if convo["convo_id"] in v4_ids:
            dropped["overlap"] += 1
        elif excluded(text) or excluded(greeting):
            dropped["full_date_or_denial"] += 1
        else:
            pool.setdefault(predicate, []).append((text, greeting, convo))
    rng = random.Random(abcd_build.SEED)
    (OUT / "scenarios").mkdir(parents=True, exist_ok=True)
    (OUT / "ledgers").mkdir(parents=True, exist_ok=True)
    n = 0
    for predicate, _ in abcd_build.RULES:
        items = pool.get(predicate, [])
        for text, greeting, convo in rng.sample(items, min(abcd_build.PER_PREDICATE, len(items))):
            n += 1
            sid, sc = f"H{n:03d}v", convo["scenario"]
            turns = ([abcd_build.turn(greeting, "none", "none", "other")] if greeting else []) + [
                abcd_build.turn(text, predicate, "verified", "claim")]
            scenario = {"scenario_id": sid, "trust": 2,
                        "source": {"dataset": "ABCD v1.1 (MIT)", "split": split_of[convo["convo_id"]], "convo_id": convo["convo_id"],
                                   "flow": sc["flow"], "subflow": sc["subflow"]},
                        "turns": turns}
            meta, _ = abcd_ledger.build3_one(scenario, convo)
            (OUT / "scenarios" / f"{sid}.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1) + "\n")
            (OUT / "ledgers" / f"{sid}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    counts = {p: len(v) for p, v in pool.items()}
    (OUT / "selection.json").write_text(json.dumps({"candidates": counts, "dropped": dropped, "sources": n}, indent=1) + "\n")
    print("candidates", counts, "dropped", dropped, "sources", n)


if __name__ == "__main__":
    main(sys.argv[1])
