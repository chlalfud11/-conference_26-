"""M1P4 원자료 무결성 검사 — 집계 전에 형상만 본다 (2026-10-15).

지표·검정은 건드리지 않는다. 런 수, 중복, 조건, 결정 주체, 스키마 성공률, 턴 길이만 센다.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg  # noqa: E402
from npc import eval as ev  # noqa: E402
from ulw_policy_v2 import expected_decision_v2  # noqa: E402

LOG = CP / "logs" / "policy_v2" / "runs.jsonl"
ADV_LOG = CP / "logs" / "adversarial" / "runs.jsonl"
OUT = CP / "logs" / "policy_v2" / "integrity.json"


def scoring_key_audit(runs: list[dict], scen: dict[str, dict]) -> dict:
    mismatches = []
    divergent = scored_as_v2 = turns = 0
    for r in runs:
        sc = scen.get(r["scenario_id"])
        if sc is None:
            continue
        for t, spec in zip(r["turns"], sc["turns"]):
            if not spec.get("scored"):
                continue
            turns += 1
            truth = spec.get("truth_predicate", "none")
            contradicts = spec.get("contradicts_state", False)
            truth_based = spec.get("expected_decision") or cfg.expected_decision(
                cfg.risk_of(truth), t["evidence"], r["trust"], contradicts)
            if t["expected_decision"] != truth_based:
                mismatches.append({"run_id": r["run_id"], "turn": t["turn"],
                                   "logged": t["expected_decision"], "truth_based": truth_based})
            policy_based = expected_decision_v2(
                truth, (t.get("nlu") or {}).get("speech_act", "other"),
                t["evidence"], r["trust"], contradicts)
            if policy_based != truth_based:
                divergent += 1
                scored_as_v2 += int(t["expected_decision"] == policy_based)
    return {
        "runs": len(runs), "scored_turns": turns,
        "mismatches_vs_truth_based_key": len(mismatches),
        "turns_where_p4_would_differ": divergent,
        "turns_scored_with_p4_key": scored_as_v2,
        "samples": mismatches[:5],
        "verdict": "PASS" if not mismatches and not scored_as_v2 else "FAIL",
    }


def baseline_runs(condition: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for line in ADV_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        if run["condition"] != condition or run["run_id"] in seen:
            continue
        seen.add(run["run_id"])
        out.append(run)
    return out


def main() -> int:
    scen = {}
    for folder in ("scenarios", "scenarios_adversarial"):
        scen.update(ev.load_scenarios(CP / folder))

    lines = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    runs = [json.loads(l) for l in lines]
    ids = Counter(r["run_id"] for r in runs)
    expected_ids = {f"{sid}__M1P4__s{seed}" for sid in scen for seed in cfg.SEEDS}

    actors = Counter()
    schema_total = schema_ok = 0
    turn_mismatch = []
    for r in runs:
        sc = scen.get(r["scenario_id"])
        if sc is None:
            turn_mismatch.append({"run_id": r["run_id"], "reason": "unknown_scenario"})
            continue
        if len(r["turns"]) != len(sc["turns"]):
            turn_mismatch.append({"run_id": r["run_id"],
                                  "turns": len(r["turns"]), "spec_turns": len(sc["turns"])})
        for t in r["turns"]:
            actors[t.get("decision_actor")] += 1
            schema_total += 2
            schema_ok += int(t["nlu_schema_ok"]) + int(t["response_schema_ok"])

    out = {
        "log": str(LOG.relative_to(CP)),
        "lines": len(lines),
        "unique_run_ids": len(ids),
        "duplicate_run_ids": {k: v for k, v in ids.items() if v > 1},
        "planned_runs": len(expected_ids),
        "missing_run_ids": sorted(expected_ids - set(ids)),
        "unexpected_run_ids": sorted(set(ids) - expected_ids),
        "conditions": dict(Counter(r["condition"] for r in runs)),
        "seeds": dict(Counter(r["seed"] for r in runs)),
        "models": dict(Counter(r["model"] for r in runs)),
        "decision_actors": dict(actors),
        "schema_ok_rate": schema_ok / schema_total if schema_total else float("nan"),
        "turn_count_mismatches": turn_mismatch,
        "scoring_independence": {
            "M1P4": scoring_key_audit(runs, scen),
            **{c: scoring_key_audit(baseline_runs(c), scen) for c in ("M1P0", "M1P1")},
        },
    }
    independent = all(v["verdict"] == "PASS" for v in out["scoring_independence"].values())
    out["verdict"] = "PASS" if (independent and
        out["lines"] == out["unique_run_ids"] == out["planned_runs"]
        and not out["duplicate_run_ids"] and not out["missing_run_ids"]
        and not out["unexpected_run_ids"] and not turn_mismatch
        and set(out["conditions"]) == {"M1P4"}
        and set(out["decision_actors"]) == {"policy_engine_v2"}
    ) else "INCOMPLETE_OR_FAIL"

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{out['verdict']}: {out['lines']}행 / 고유 {out['unique_run_ids']} / 계획 {out['planned_runs']}")
    print(f"  중복 {len(out['duplicate_run_ids'])}건, 누락 {len(out['missing_run_ids'])}건, "
          f"예상 외 {len(out['unexpected_run_ids'])}건, 턴수 불일치 {len(turn_mismatch)}건")
    print(f"  조건 {out['conditions']} / 시드 {out['seeds']}")
    print(f"  결정 주체 {out['decision_actors']} / 스키마 성공률 {out['schema_ok_rate']:.4f}")
    print(f"  모델 {out['models']}")
    print("  채점 독립성 (expected_decision 이 진실 술어 기반 공식인가):")
    for cond, v in out["scoring_independence"].items():
        print(f"    {cond:<6} {v['verdict']}  채점턴 {v['scored_turns']}, "
              f"진실기반 공식과 불일치 {v['mismatches_vs_truth_based_key']}건, "
              f"P4 로 채점된 턴 {v['turns_scored_with_p4_key']}건"
              f" (P4 가 다른 답을 낼 턴 {v['turns_where_p4_would_differ']}개)")
    print(f"저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
