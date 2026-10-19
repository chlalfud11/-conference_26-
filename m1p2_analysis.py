from __future__ import annotations

import csv
import json
from collections import Counter

from npc import config
from npc import eval as evaluator


def main() -> int:
    with (config.ROOT / "results" / "metrics.csv").open(encoding="utf-8") as handle:
        metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    with (config.ROOT / "logs" / "runs.jsonl").open(encoding="utf-8") as handle:
        runs = [json.loads(line) for line in handle if line.strip()]
    counts = Counter(run["condition"] for run in runs)
    assert len(runs) == len({run["run_id"] for run in runs}) == 324
    assert len(metrics) == 6 and all(count == 54 for count in counts.values())
    scenarios = evaluator.load_scenarios(config.ROOT / "scenarios")
    indexed = {(r["scenario_id"], r["seed"], r["condition"]): r for r in runs}
    pairs = []
    nlu_changed = decision_changed = unverified_grounding = 0
    for scenario_id in sorted(scenarios):
        scenario = scenarios[scenario_id]
        for seed in config.SEEDS:
            before = indexed[scenario_id, seed, "M1P1"]
            after = indexed[scenario_id, seed, "M1P2"]
            before["_violated_invariants"] = evaluator.violated_invariants(before, scenario)
            after["_violated_invariants"] = evaluator.violated_invariants(after, scenario)
            for a, b, spec in zip(before["turns"], after["turns"], scenario["turns"], strict=True):
                nlu_changed += a["nlu"] != b["nlu"]
                decision_changed += a["decision"] != b["decision"]
                unverified_grounding += (
                    b["decision"] == "accept_as_belief" and b["evidence"] != "verified"
                )
                if not spec.get("scored") or a["evidence"] not in ("none", "contradicting"):
                    continue
                flag = "asserted_as_fact_in_utterance"
                detected_before = flag in evaluator.contamination_flags(a, spec, before)
                detected_after = flag in evaluator.contamination_flags(b, spec, after)
                pairs.append({
                    "scenario_id": scenario_id, "seed": seed, "turn": a["turn"],
                    "player": a["player"], "before_decision": a["decision"],
                    "after_decision": b["decision"], "before_response": a["response"],
                    "after_response": b["response"], "before_detected": detected_before,
                    "after_detected": detected_after,
                })
    before_count = sum(p["before_detected"] for p in pairs)
    after_count = sum(p["after_detected"] for p in pairs)
    assert before_count == int(metrics["M1P1"]["c_asserted_as_fact_in_utterance"])
    assert after_count == int(metrics["M1P2"]["c_asserted_as_fact_in_utterance"])
    transitions = {
        "flag_disappeared": sum(p["before_detected"] and not p["after_detected"] for p in pairs),
        "flag_persisted": sum(p["before_detected"] and p["after_detected"] for p in pairs),
        "flag_introduced": sum(not p["before_detected"] and p["after_detected"] for p in pairs),
        "neither_flagged": sum(not p["before_detected"] and not p["after_detected"] for p in pairs),
    }
    result = {
        "record_count": len(runs), "condition_counts": dict(counts),
        "compared_all_turns": 54 * 8, "criterion2_eligible_pairs": len(pairs),
        "criterion2_before": before_count, "criterion2_after": after_count,
        "transitions": transitions, "nlu_objects_changed": nlu_changed,
        "decisions_changed": decision_changed,
        "m1p2_unverified_accept_grounding_count": unverified_grounding,
        "metrics": {condition: metrics[condition] for condition in ("M1P1", "M1P2")},
        "scope": "Regex-detected assertions, not independently validated semantic truthfulness.",
        "all_eligible_pairs": pairs,
    }
    with (config.ROOT / "results" / "m1p2_comparison.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print("D3 PASS: 324 unique records; 6 conditions; 54 records per condition")
    print("metric | M1P1 | M1P2")
    for key in ("c_asserted_as_fact_in_utterance", "CCR", "CCR_lo", "CCR_hi",
                "TCAR", "agree_rate", "MacroF1", "PCFBR", "c_promoted_without_policy"):
        print(f"{key} | {metrics['M1P1'][key]} | {metrics['M1P2'][key]}")
    print("criterion2 transitions:", transitions)
    print("NLU object changes:", nlu_changed, "; decision changes:", decision_changed)
    print("Unverified claims described as verified in grounding:", unverified_grounding)
    for label, states in (
        ("flag_disappeared", (True, False)),
        ("flag_persisted", (True, True)),
        ("flag_introduced", (False, True)),
    ):
        print(f"\n{label}: first occurrence per scenario")
        shown = set()
        for pair in pairs:
            if (pair["before_detected"], pair["after_detected"]) != states:
                continue
            scenario_id = pair["scenario_id"]
            if scenario_id in shown:
                continue
            shown.add(scenario_id)
            print(f"{scenario_id} seed={pair['seed']} turn={pair['turn']} player={pair['player']}")
            print("M1P1:", pair["before_response"])
            print("M1P2:", pair["after_response"])
            if len(shown) == 4:
                break
    print("\nFull paired evidence: results/m1p2_comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
