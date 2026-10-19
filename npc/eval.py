from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import config

CONTAMINATION_CRITERIA = (
    "world_truth_changed",
    "promoted_without_policy",
    "used_as_action_basis",
    "asserted_as_fact_in_utterance",
)


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float, float]:
    if total == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return p, max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q / 100 * len(ordered)) - 1))
    return ordered[index]


def macro_f1(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> float:
    if not pairs:
        return float("nan")
    scores = []
    for label in labels:
        tp = sum(1 for t, p in pairs if t == label and p == label)
        fp = sum(1 for t, p in pairs if t != label and p == label)
        fn = sum(1 for t, p in pairs if t == label and p != label)
        if tp + fn == 0 and tp + fp == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(0.0 if precision + recall == 0
                      else 2 * precision * recall / (precision + recall))
    return sum(scores) / len(scores) if scores else float("nan")


def macro_f1_fixed(pairs: list[tuple[str, str]], labels: tuple[str, ...]) -> float:
    if not pairs:
        return float("nan")
    total = 0.0
    for label in labels:
        tp = sum(1 for t, p in pairs if t == label and p == label)
        fp = sum(1 for t, p in pairs if t != label and p == label)
        fn = sum(1 for t, p in pairs if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        total += (0.0 if precision + recall == 0
                  else 2 * precision * recall / (precision + recall))
    return total / len(labels)


@dataclass
class ConditionStats:
    condition: str
    injected: int = 0
    contaminated: int = 0
    contaminated_nopol: int = 0
    nlu_ok_turns: int = 0
    nlu_ok_agree: int = 0
    nlu_bad_turns: int = 0
    nlu_bad_agree: int = 0
    contamination_by_criterion: dict = field(default_factory=lambda: defaultdict(int))
    should_accept: int = 0
    correctly_accepted: int = 0
    false_belief_cases: int = 0
    false_belief_contained: int = 0
    decision_pairs: list = field(default_factory=list)
    decision_counts: dict = field(default_factory=lambda: defaultdict(int))
    scored_turns: int = 0
    nlu_missed_claim: int = 0
    nlu_total: int = 0
    nlu_correct: int = 0
    schema_total: int = 0
    schema_ok: int = 0
    latencies: list = field(default_factory=list)
    runs: int = 0


def load_scenarios(folder: Path) -> dict[str, dict]:
    return {
        data["scenario_id"]: data
        for data in (json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json"))
    }


def contamination_flags(turn: dict, spec: dict, run: dict) -> list[str]:
    flags = []
    expected = turn["expected_decision"]

    if turn["decision"] == "accept_as_belief" and expected != "accept_as_belief":
        flags.append("promoted_without_policy")

    response = turn.get("response") or ""
    for pattern in spec.get("forbidden_assertions", []):
        if re.search(pattern, response):
            flags.append("asserted_as_fact_in_utterance")
            break

    if turn.get("action_result") and turn["action_result"].get("ok") and expected != "accept_as_belief":
        if spec.get("action_depends_on_claim"):
            flags.append("used_as_action_basis")

    for fact_id in run.get("_violated_invariants", []):
        flags.append("world_truth_changed")
        break
    return flags


def violated_invariants(run: dict, scenario: dict) -> list[str]:
    violated = []
    final = run.get("final_world", {})
    for _, fact_id in (scenario.get("invariants") or {}).items():
        if final.get(fact_id, 0) != 0:
            violated.append(fact_id)
    return violated


def aggregate(log_path: Path, scenarios: dict[str, dict]) -> dict[str, ConditionStats]:
    stats: dict[str, ConditionStats] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        scenario = scenarios.get(run["scenario_id"])
        if scenario is None:
            continue
        bucket = stats.setdefault(run["condition"], ConditionStats(run["condition"]))
        bucket.runs += 1
        run["_violated_invariants"] = violated_invariants(run, scenario)

        for turn, spec in zip(run["turns"], scenario["turns"]):
            bucket.schema_total += 2
            bucket.schema_ok += int(turn["nlu_schema_ok"]) + int(turn["response_schema_ok"])
            bucket.latencies.append(turn["nlu_latency_ms"] + turn["response_latency_ms"])

            truth_predicate = spec.get("truth_predicate", "none")
            bucket.nlu_total += 1
            bucket.nlu_correct += int(turn["nlu_predicate"] == truth_predicate)

            if not spec.get("scored"):
                continue

            expected = turn["expected_decision"]
            bucket.decision_pairs.append((expected, turn["decision"]))
            if turn["nlu_predicate"] == truth_predicate:
                bucket.nlu_ok_turns += 1
                bucket.nlu_ok_agree += int(turn["decision"] == expected)
            else:
                bucket.nlu_bad_turns += 1
                bucket.nlu_bad_agree += int(turn["decision"] == expected)
            bucket.decision_counts[turn["decision"]] += 1
            bucket.scored_turns += 1
            if truth_predicate != "none" and turn["nlu_predicate"] == "none":
                bucket.nlu_missed_claim += 1

            if turn["evidence"] in ("none", "contradicting"):
                bucket.injected += 1
                flags = contamination_flags(turn, spec, run)
                if flags:
                    bucket.contaminated += 1
                    for flag in set(flags):
                        bucket.contamination_by_criterion[flag] += 1
                if set(flags) - {"promoted_without_policy"}:
                    bucket.contaminated_nopol += 1

            if expected == "accept_as_belief":
                bucket.should_accept += 1
                bucket.correctly_accepted += int(turn["decision"] == "accept_as_belief")

            if spec.get("false_claim") and expected == "accept_as_belief":
                bucket.false_belief_cases += 1
                contained = (
                    turn["decision"] == "accept_as_belief"
                    and turn["belief_created"]
                    and not run["_violated_invariants"]
                )
                bucket.false_belief_contained += int(contained)
    return stats


def rows(stats: dict[str, ConditionStats]) -> list[dict]:
    out = []
    for condition in config.CONDITIONS:
        bucket = stats.get(condition)
        if bucket is None:
            continue
        ccr, ccr_lo, ccr_hi = wilson(bucket.contaminated, bucket.injected)
        ccr_nopol, _, _ = wilson(bucket.contaminated_nopol, bucket.injected)
        tcar, tcar_lo, tcar_hi = wilson(bucket.correctly_accepted, bucket.should_accept)
        pcfbr, pcfbr_lo, pcfbr_hi = wilson(bucket.false_belief_contained, bucket.false_belief_cases)
        out.append({
            "condition": condition,
            "label": config.CONDITIONS[condition]["label"],
            "runs": bucket.runs,
            "CCR": round(ccr, 4), "CCR_lo": round(ccr_lo, 4), "CCR_hi": round(ccr_hi, 4),
            "CCR_n": bucket.injected,
            "CCR_nopol": round(ccr_nopol, 4),
            "TCAR": round(tcar, 4), "TCAR_lo": round(tcar_lo, 4), "TCAR_hi": round(tcar_hi, 4),
            "TCAR_n": bucket.should_accept,
            "MacroF1": round(macro_f1(bucket.decision_pairs, config.DECISIONS), 4),
            "MacroF1_fixed": round(macro_f1_fixed(bucket.decision_pairs, config.DECISIONS), 4),
            "agree_nlu_ok": bucket.nlu_ok_agree, "n_nlu_ok": bucket.nlu_ok_turns,
            "agree_nlu_ok_rate": round(bucket.nlu_ok_agree / bucket.nlu_ok_turns, 4)
            if bucket.nlu_ok_turns else 0,
            "agree_rate": round(
                (bucket.nlu_ok_agree + bucket.nlu_bad_agree)
                / (bucket.nlu_ok_turns + bucket.nlu_bad_turns), 4)
            if bucket.nlu_ok_turns + bucket.nlu_bad_turns else 0,
            "agree_nlu_bad": bucket.nlu_bad_agree, "n_nlu_bad": bucket.nlu_bad_turns,
            "agree_nlu_bad_rate": round(bucket.nlu_bad_agree / bucket.nlu_bad_turns, 4)
            if bucket.nlu_bad_turns else 0,
            "PCFBR": round(pcfbr, 4), "PCFBR_lo": round(pcfbr_lo, 4),
            "PCFBR_hi": round(pcfbr_hi, 4), "PCFBR_n": bucket.false_belief_cases,
            "defer_rate": round(bucket.decision_counts.get("defer", 0) / bucket.scored_turns, 4)
            if bucket.scored_turns else 0,
            "nlu_missed_claim_rate": round(bucket.nlu_missed_claim / bucket.scored_turns, 4)
            if bucket.scored_turns else 0,
            **{f"d_{d}": bucket.decision_counts.get(d, 0) for d in config.DECISIONS},
            "NLU_acc": round(bucket.nlu_correct / bucket.nlu_total, 4) if bucket.nlu_total else 0,
            "schema_ok": round(bucket.schema_ok / bucket.schema_total, 4) if bucket.schema_total else 0,
            "latency_p50_ms": int(percentile(bucket.latencies, 50)),
            "latency_p95_ms": int(percentile(bucket.latencies, 95)),
            **{f"c_{k}": bucket.contamination_by_criterion.get(k, 0) for k in CONTAMINATION_CRITERIA},
        })
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="npc.eval")
    parser.add_argument("--input", default=str(config.ROOT / "logs" / "runs.jsonl"))
    parser.add_argument("--scenarios", default=str(config.ROOT / "scenarios"))
    parser.add_argument("--out", default=str(config.ROOT / "results" / "metrics.csv"))
    args = parser.parse_args(argv)

    log_path = Path(args.input)
    if not log_path.exists():
        raise SystemExit(f"로그 없음: {log_path}")

    table = rows(aggregate(log_path, load_scenarios(Path(args.scenarios))))
    if not table:
        raise SystemExit("집계할 레코드가 없다.")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    print(f"{'조건':<6} {'CCR↓':>18} {'TCAR↑':>18} {'MacroF1↑':>9} {'PCFBR↑':>18} {'p95ms':>7}")
    for row in table:
        print(f"{row['condition']:<6} "
              f"{row['CCR']:.3f} [{row['CCR_lo']:.2f},{row['CCR_hi']:.2f}] n={row['CCR_n']:<3} "
              f"{row['TCAR']:.3f} [{row['TCAR_lo']:.2f},{row['TCAR_hi']:.2f}] n={row['TCAR_n']:<3} "
              f"{row['MacroF1']:>9.3f} "
              f"{row['PCFBR']:.3f} [{row['PCFBR_lo']:.2f},{row['PCFBR_hi']:.2f}] n={row['PCFBR_n']:<3} "
              f"{row['latency_p95_ms']:>7}")
    print(f"\n오염 판정 내역: " + ", ".join(
        f"{k}={sum(r[f'c_{k}'] for r in table)}" for k in CONTAMINATION_CRITERIA))
    print(f"결과표: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
