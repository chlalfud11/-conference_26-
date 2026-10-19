"""ABCD v4 live run (.omo/plans/abcd-v4-answer-key.md). Subcommands: pilot live.

Needs the seal from `python3 abcd4_build.py seal`. Run files: results/abcd4/runs/<condition>_<seed>_<scenario>.json.
"""
import json
import sys
from pathlib import Path

import abcd4_ledger as LG
import abcd4_runner as R
from abcd_live import english, leak

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd4"
RUNS = OUT / "runs"
SEEDS = (11, 29, 47)
PILOT_SOURCES = ("A001", "A002", "A021", "A050")
PLAN = [(c, s) for s in SEEDS for c in R.CONDITIONS]
LEAK_TOKENS = ("verified:", "truth_predicate", "expected_decision", "answer_key")


def run(plan, ids):
    assert (OUT / "prereg_seal.json").exists(), "seal first: python3 abcd4_build.py seal"
    R.install()
    sc, (rows, today) = R.scenarios(), LG.load()
    RUNS.mkdir(parents=True, exist_ok=True)
    done = 0
    for cond, seed in plan:
        for sid in ids:
            path = RUNS / f"{cond}_{seed}_{sid}.json"
            if not path.exists():
                path.write_text(R.run_dialogue4(sc[sid], cond, seed, rows, today).to_json())
            done += 1
            print(f"[{done}] {path.name}", flush=True)
    return done


def pilot():
    ids = [f"{s}{v}" for s in PILOT_SOURCES for v in "vnd"]
    n = run([(c, 11) for c in R.CONDITIONS], ids)
    recs = [json.loads((RUNS / f"{c}_11_{sid}.json").read_text()) for c in R.CONDITIONS for sid in ids]
    turns = [t for r in recs for t in r["turns"]]
    claims = [r["turns"][-1] for r in recs]
    checks = {
        "no_thinking_leak": sum(leak(t) for t in turns) == 0,
        "english": all(english(t["response"]) for t in turns),
        "stated_date_in_claim_prompt": all("Customer-stated date:" in t["prompt"] for t in claims),
        "search_block_in_S": all("Ledger search results" in r["turns"][-1]["prompt"] for r in recs if r["condition"] == "S-M1P0"),
        "no_answer_tokens_in_prompt": not any(tok in t["prompt"] for t in turns for tok in LEAK_TOKENS),
    }
    for r in recs:
        t = r["turns"][-1]
        print(r["condition"], r["scenario_id"], t["nlu_predicate"], t["evidence"], t["decision"], "|", t["response"][:90])
    print(json.dumps(checks))
    print(f"pilot {'ok' if n == 36 and all(checks.values()) else 'FAIL'} {n}/36")


def live():
    print("live done", run(PLAN, sorted(R.scenarios())))


if __name__ == "__main__":
    {"pilot": pilot, "live": live}[sys.argv[1]]()
