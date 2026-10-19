from __future__ import annotations

import csv
import json
from collections import Counter

from npc import config
from npc import eval as evaluator
from npc.engine import GameEngine

CONDITIONS = ("M1P1", "M1P2", "M1P2G")


def main() -> int:
    with (config.ROOT / "results" / "metrics.csv").open(encoding="utf-8") as handle:
        metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    with (config.ROOT / "logs" / "runs.jsonl").open(encoding="utf-8") as handle:
        runs = [json.loads(line) for line in handle if line.strip()]
    counts = Counter(run["condition"] for run in runs)
    assert len(runs) == len({run["run_id"] for run in runs}) == 378
    assert len(metrics) == len(counts) == 7 and all(v == 54 for v in counts.values())
    indexed = {(r["scenario_id"], r["seed"], r["condition"]): r for r in runs}
    scenarios = evaluator.load_scenarios(config.ROOT / "scenarios")
    pairs = []
    differences = {
        condition: {"nlu_object": 0, "predicate": 0, "decision": 0}
        for condition in CONDITIONS[:-1]
    }
    grounding_checked = 0
    for scenario_id, scenario in sorted(scenarios.items()):
        for seed in config.SEEDS:
            group = {c: indexed[scenario_id, seed, c] for c in CONDITIONS}
            for run in group.values():
                run["_violated_invariants"] = evaluator.violated_invariants(run, scenario)
            engine = GameEngine()
            try:
                engine.reset(scenario.get("initial_facts"))
                for index, spec in enumerate(scenario["turns"]):
                    turns = {c: group[c]["turns"][index] for c in CONDITIONS}
                    new = turns["M1P2G"]
                    system = json.loads(new["prompt"])[0]["content"]
                    ground = json.loads(system.split("[엔진 근거]\n", 1)[1].splitlines()[0])
                    assert ground["world_truth"] == engine.world()
                    assert ground["world_truth_source"] == "game_engine"
                    inputs = ground["policy_inputs"]
                    assert inputs["evidence"] == spec.get("evidence", "none")
                    assert inputs["evidence_verified"] == (new["evidence"] == "verified")
                    assert inputs["claim_predicate"] == new["nlu_predicate"]
                    assert inputs["claim_object"] == (new["nlu"].get("claim_object") or "")
                    assert inputs["risk"] == config.risk_of(new["nlu_predicate"])
                    assert inputs["trust"] == config.clamp_trust(scenario.get("trust", 1))
                    assert inputs["contradicts_state"] == spec.get("contradicts_state", False)
                    assert inputs["evidence_trust_contradiction_source"] == "scenario_fixture"
                    assert "truth_predicate" not in ground and "expected_decision" not in ground
                    grounding_checked += 1
                    for baseline in CONDITIONS[:-1]:
                        old = turns[baseline]
                        differences[baseline]["nlu_object"] += old["nlu"] != new["nlu"]
                        differences[baseline]["predicate"] += old["nlu_predicate"] != new["nlu_predicate"]
                        differences[baseline]["decision"] += old["decision"] != new["decision"]
                    if spec.get("scored") and new["evidence"] in ("none", "contradicting"):
                        flag = "asserted_as_fact_in_utterance"
                        pairs.append({
                            "scenario_id": scenario_id, "seed": seed, "turn": new["turn"],
                            "player": new["player"],
                            "responses": {c: turns[c]["response"] for c in CONDITIONS},
                            "decisions": {c: turns[c]["decision"] for c in CONDITIONS},
                            "detected": {
                                c: flag in evaluator.contamination_flags(turns[c], spec, group[c])
                                for c in CONDITIONS
                            },
                        })
                    action = spec.get("action")
                    if action and action.get("skill") == "buy":
                        result = engine.buy(index + 1, action["item"], action["quantity"])
                        assert new["action_result"]["ok"] == result.ok
                        assert new["action_result"]["reason"] == result.reason
                assert group["M1P2G"]["final_world"] == engine.world()
            finally:
                engine.close()
    assert grounding_checked == 432
    for condition in CONDITIONS:
        assert len(pairs) == int(metrics[condition]["CCR_n"])
        assert sum(p["detected"][condition] for p in pairs) == int(
            metrics[condition]["c_asserted_as_fact_in_utterance"]
        )
    transitions = {}
    for baseline in CONDITIONS[:-1]:
        transitions[baseline] = {
            "flag_disappeared": sum(p["detected"][baseline] and not p["detected"]["M1P2G"] for p in pairs),
            "flag_persisted": sum(p["detected"][baseline] and p["detected"]["M1P2G"] for p in pairs),
            "flag_introduced": sum(not p["detected"][baseline] and p["detected"]["M1P2G"] for p in pairs),
            "neither_flagged": sum(not p["detected"][baseline] and not p["detected"]["M1P2G"] for p in pairs),
        }
    report = {
        "record_count": len(runs), "condition_counts": dict(counts),
        "grounding_turns_checked": grounding_checked, "eligible_pairs": len(pairs),
        "metrics": {c: metrics[c] for c in CONDITIONS},
        "differences_from_m1p2g": differences, "transitions_to_m1p2g": transitions,
        "scope": "Unchanged regex metric; not a semantic truthfulness error rate.",
        "all_eligible_pairs": pairs,
    }
    with (config.ROOT / "results" / "m1p2g_comparison.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("M1P2G_ANALYSIS_PASS: 378 unique records; grounded state verified in 432 turns")
    print("metric | " + " | ".join(CONDITIONS))
    for key in ("c_asserted_as_fact_in_utterance", "CCR", "CCR_lo", "CCR_hi",
                "TCAR", "agree_rate", "MacroF1", "PCFBR", "latency_p95_ms"):
        print(key + " | " + " | ".join(metrics[c][key] for c in CONDITIONS))
    print("Differences from M1P2G:", differences)
    print("Regex flag transitions:", transitions)
    for states, label in (((True, False), "flag_disappeared"), ((False, True), "flag_introduced")):
        print("\nM1P1 -> M1P2G", label, ": first occurrence per scenario")
        shown = set()
        for pair in pairs:
            if (pair["detected"]["M1P1"], pair["detected"]["M1P2G"]) != states:
                continue
            if pair["scenario_id"] in shown:
                continue
            shown.add(pair["scenario_id"])
            print(f"{pair['scenario_id']} seed={pair['seed']} turn={pair['turn']}")
            print("Player:", pair["player"])
            for condition in CONDITIONS:
                print(condition + ":", pair["responses"][condition])
            if len(shown) == 4:
                break
    print("\nFull evidence: results/m1p2g_comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
