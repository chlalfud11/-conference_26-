from __future__ import annotations

import csv
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile

from npc import config
from npc import eval as evaluator

CONDITIONS = ("M1P1", "M1P2G", "M1P3")


def main() -> int:
    with (config.ROOT / "results" / "metrics.csv").open(encoding="utf-8") as handle:
        metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    with (config.ROOT / "logs" / "runs.jsonl").open(encoding="utf-8") as handle:
        runs = [json.loads(line) for line in handle if line.strip()]
    counts = Counter(run["condition"] for run in runs)
    assert len(runs) == len({run["run_id"] for run in runs}) == 432
    assert len(metrics) == len(counts) == 8 and all(count == 54 for count in counts.values())
    guarded = [run for run in runs if run["condition"] == "M1P3"]
    raw_runs = deepcopy(guarded)
    for run in raw_runs:
        for turn in run["turns"]:
            turn["response"] = turn["raw_response"]
            turn["response_schema_ok"] = turn["raw_response_schema_ok"]
    scenarios = evaluator.load_scenarios(config.ROOT / "scenarios")
    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl") as temporary:
        for run in raw_runs:
            temporary.write(json.dumps(run, ensure_ascii=False) + "\n")
        temporary.flush()
        raw_metrics = evaluator.rows(
            evaluator.aggregate(Path(temporary.name), scenarios),
        )[0]
    for key in ("TCAR", "agree_rate", "MacroF1", "NLU_acc", "PCFBR", "latency_p95_ms"):
        assert str(raw_metrics[key]) == metrics["M1P3"][key]

    pairs = []
    all_turns = []
    index = {(run["scenario_id"], run["seed"], run["condition"]): run for run in runs}
    for run, raw_run in zip(guarded, raw_runs, strict=True):
        scenario = scenarios[run["scenario_id"]]
        for candidate_run in (run, raw_run):
            candidate_run["_violated_invariants"] = evaluator.violated_invariants(
                candidate_run, scenario,
            )
        for turn, raw, spec in zip(run["turns"], raw_run["turns"], scenario["turns"], strict=True):
            entry = {
                "run_id": run["run_id"], "scenario_id": run["scenario_id"],
                "seed": run["seed"], "turn": turn["turn"], "player": turn["player"],
                "decision": turn["decision"], "output_plan": turn["output_plan"],
                "raw_response": turn["raw_response"], "response": turn["response"],
                "raw_response_schema_ok": turn["raw_response_schema_ok"],
                "guard_latency_ms": turn["guard_latency_ms"],
                "candidate_changed": turn["raw_response"] != turn["response"],
            }
            all_turns.append(entry)
            if spec.get("scored") and turn["evidence"] in ("none", "contradicting"):
                flag = "asserted_as_fact_in_utterance"
                entry["raw_detected"] = flag in evaluator.contamination_flags(raw, spec, raw_run)
                entry["final_detected"] = flag in evaluator.contamination_flags(turn, spec, run)
                entry["baseline"] = {}
                for condition in CONDITIONS[:-1]:
                    old_run = index[run["scenario_id"], run["seed"], condition]
                    old_run["_violated_invariants"] = evaluator.violated_invariants(
                        old_run, scenario,
                    )
                    old = old_run["turns"][turn["turn"] - 1]
                    entry["baseline"][condition] = {
                        "response": old["response"], "decision": old["decision"],
                        "detected": flag in evaluator.contamination_flags(old, spec, old_run),
                    }
                pairs.append(entry)
    assert len(all_turns) == 432
    assert len(pairs) == int(metrics["M1P3"]["CCR_n"])
    assert sum(pair["final_detected"] for pair in pairs) == int(
        metrics["M1P3"]["c_asserted_as_fact_in_utterance"],
    )
    assert sum(pair["raw_detected"] for pair in pairs) == raw_metrics[
        "c_asserted_as_fact_in_utterance"
    ]
    report = {
        "record_count": len(runs), "condition_counts": dict(counts),
        "metrics": {condition: metrics[condition] for condition in CONDITIONS},
        "raw_candidate_metrics_same_runs": raw_metrics,
        "raw_candidate_scope": "Same M1P3 runs; candidates generated with guarded prior NPC history.",
        "final_output_actor": "engine_renderer",
        "not_a_claim_of_improved_slm_truthfulness": True,
        "candidate_changed_turns": sum(turn["candidate_changed"] for turn in all_turns),
        "raw_json_failures": sum(not turn["raw_response_schema_ok"] for turn in all_turns),
        "eligible_pairs": len(pairs),
        "template_counts": dict(Counter(
            turn["output_plan"]["template_id"] for turn in all_turns
        )),
        "scope": "Unchanged regex metric plus separately audited bounded speech contract.",
        "all_eligible_pairs": pairs,
        "all_guarded_turns": all_turns,
    }
    with (config.ROOT / "results" / "m1p3_comparison.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("M1P3_ANALYSIS_PASS: 432 unique runs; raw and final utterances kept separate")
    print("metric | " + " | ".join(CONDITIONS) + " | M1P3 raw candidate")
    for key in ("c_asserted_as_fact_in_utterance", "CCR", "CCR_lo", "CCR_hi",
                "TCAR", "agree_rate", "MacroF1", "PCFBR", "schema_ok", "latency_p95_ms"):
        print(key + " | " + " | ".join(metrics[condition][key] for condition in CONDITIONS)
              + " | " + str(raw_metrics[key]))
    print("Templates:", report["template_counts"])
    print("Changed candidates:", report["candidate_changed_turns"], "/", len(all_turns))
    print("Raw JSON failures:", report["raw_json_failures"])
    print("Full evidence: results/m1p3_comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
