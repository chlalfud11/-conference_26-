"""Held-out F-M1P0 add-on (docs/ABCD_v5_P0추가_사전등록.md).

Usage: python3 abcd5_p0.py seal | ABCD4_SET=heldout python3 abcd5_p0.py live | python3 abcd5_p0.py grade
"""
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import abcd4_ledger as LG
import abcd4_runner as R
import abcd6_live as V6
from abcd_live import english, holm, leak, sha

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd5p0"
RUNS = OUT / "runs"
PREREG = ROOT / "docs" / "ABCD_v5_P0추가_사전등록.md"
SOURCES = {"F-M1P0": RUNS, "F-M1P1": ROOT / "results" / "abcd5" / "runs" / "heldout", "T-M1P0": ROOT / "results" / "abcd6" / "runs" / "heldout"}


def seal():
    path = OUT / "prereg_seal.json"
    assert not path.exists(), "already sealed"
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sealed_at": datetime.now(timezone.utc).isoformat(), "prereg": sha(PREREG),
                                "v5_seal": sha(ROOT / "results" / "abcd5" / "prereg_seal.json")}, indent=1) + "\n")
    print("sealed", sha(PREREG)[:12])


def live():
    assert LG.HELDOUT and (OUT / "prereg_seal.json").exists()
    R.install()
    sc, (rows, today) = R.scenarios(), LG.load()
    RUNS.mkdir(parents=True, exist_ok=True)
    n = 0
    for seed in V6.SEEDS:
        for sid in sorted(sc):
            path = RUNS / f"F-M1P0_{seed}_{sid}.json"
            if not path.exists():
                path.write_text(R.run_dialogue4(sc[sid], "F-M1P0", seed, rows, today).to_json())
            n += 1
            print(f"[{n}] F-M1P0_{seed}_{sid}", flush=True)
    print(f"live done {n}")


def grade():
    seal_ = json.loads((OUT / "prereg_seal.json").read_text())
    with V6.SETS["heldout"]["key"].open(newline="") as handle:
        key = {(r["scenario_id"], int(r["turn"])): r for r in csv.DictReader(handle)}
    rows, turns = [], []
    for cond, folder in SOURCES.items():
        for p in sorted(folder.glob(f"{cond}_*.json")):
            r = json.loads(p.read_text())
            t = r["turns"][-1]
            turns += r["turns"] if cond == "F-M1P0" else []
            k = key[(r["scenario_id"], t["turn"])]
            rows.append({"cond": cond, "src": r["scenario_id"][:-1], "ver": r["scenario_id"][-1],
                         "decision": t["decision"], "expected": k["expected_decision"]})
    p0 = sorted(RUNS.glob("*.json"))
    res = {"runs": len(p0), "prereg_sha_match": seal_["prereg"] == sha(PREREG),
           "seal_before_live": datetime.fromisoformat(seal_["sealed_at"]).timestamp() < min(p.stat().st_mtime for p in p0),
           "leaks": sum(bool(leak(t)) for t in turns), "non_english": sum(not english(t["response"]) for t in turns),
           "table": {c: V6.describe(rows, c) for c in SOURCES},
           "primary": V6.compare(rows, "F-M1P1", "F-M1P0", "accuracy"),
           "secondary": {"a_T_vs_P0_accuracy": V6.compare(rows, "T-M1P0", "F-M1P0", "accuracy"),
                         "b_dispute_d_P1_vs_P0": V6.compare(rows, "F-M1P1", "F-M1P0", "dispute_d"),
                         "c_wrong_reject_v_P0_vs_P1": V6.compare(rows, "F-M1P0", "F-M1P1", "wrong_reject_v")},
           "decisions_P0": {v: dict(Counter(x["decision"] for x in rows if x["cond"] == "F-M1P0" and x["ver"] == v)) for v in "vnd"}}
    res["secondary_holm"] = holm({k: v["p"] for k, v in res["secondary"].items()})
    res["decision_table_better"] = res["primary"]["p"] < 0.05 and res["primary"]["diff"] > 0
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: res[k] for k in ("runs", "seal_before_live", "prereg_sha_match", "leaks", "non_english", "decision_table_better")}))
    print(json.dumps({"table": res["table"], "primary": res["primary"], "holm": res["secondary_holm"],
                      "secondary": {k: (v["diff"], v["ci95"]) for k, v in res["secondary"].items()}, "dec": res["decisions_P0"]}, indent=1))


if __name__ == "__main__":
    {"seal": seal, "live": live, "grade": grade}[sys.argv[1]]()
