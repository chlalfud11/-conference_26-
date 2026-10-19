"""P4 오프라인 성공기준 집행 — C1/C2/C3 증거 영수증 (2026-10-15).

봉인된 기준선 로그만 읽고, 사전등록된 P4 결정 함수를 그대로 적용한다.
새 추론을 하지 않으므로 기준선 로그가 바뀌지 않는 한 결과는 재현된다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import eval as ev  # noqa: E402
from ulw_policy_v2 import expected_decision_v2  # noqa: E402

ADV_LOG = CP / "logs" / "adversarial" / "runs.jsonl"
BASE_LOG = CP / "logs" / "runs.jsonl"
OUT = CP / "results" / "policy_v2" / "offline_criteria.json"
C2_THRESHOLD = 18
C3_MAX_DROP = 0.05


def runs_of(path: Path, condition: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        run = json.loads(line)
        if run["condition"] != condition or run["run_id"] in seen:
            continue
        seen.add(run["run_id"])
        out.append(run)
    return out


def p4_decision(run: dict, turn: dict, spec: dict) -> str:
    return expected_decision_v2(
        turn["nlu_predicate"],
        (turn.get("nlu") or {}).get("speech_act", "other"),
        turn["evidence"],
        run["trust"],
        spec.get("contradicts_state", False),
    )


def criterion_1(scen: dict) -> dict:
    events = []
    for run in runs_of(ADV_LOG, "M1P1"):
        sc = scen[run["scenario_id"]]
        run["_violated_invariants"] = ev.violated_invariants(run, sc)
        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored") or turn["evidence"] not in ("none", "contradicting"):
                continue
            if "promoted_without_policy" not in ev.contamination_flags(turn, spec, run):
                continue
            decision = p4_decision(run, turn, spec)
            events.append({
                "scenario_id": run["scenario_id"], "seed": run["seed"], "turn": turn["turn"],
                "truth_predicate": spec.get("truth_predicate", "none"),
                "nlu_predicate": turn["nlu_predicate"],
                "speech_act": (turn.get("nlu") or {}).get("speech_act", "other"),
                "actual_decision": turn["decision"],
                "expected_decision": turn["expected_decision"],
                "p4_decision": decision,
                "p4_still_contaminating": decision == "accept_as_belief"
                and turn["expected_decision"] != "accept_as_belief",
            })
    fixed = [e for e in events if not e["p4_still_contaminating"]]
    return {
        "events": len(events), "fixed_by_p4": len(fixed),
        "remaining": [e for e in events if e["p4_still_contaminating"]],
        "verdict": "PASS" if events and len(fixed) == len(events) else "FAIL",
        "detail": events,
    }


def criterion_2(scen: dict) -> dict:
    total = actual = predicted = 0
    for run in runs_of(ADV_LOG, "M1P1"):
        sc = scen[run["scenario_id"]]
        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored") or turn["expected_decision"] != "accept_as_belief":
                continue
            total += 1
            actual += turn["decision"] == "accept_as_belief"
            predicted += p4_decision(run, turn, spec) == "accept_as_belief"
    return {
        "should_accept_turns": total,
        "m1p1_accepted": actual, "m1p1_tcar": actual / total if total else float("nan"),
        "p4_accepted": predicted, "p4_tcar": predicted / total if total else float("nan"),
        "threshold_accepted": C2_THRESHOLD,
        "verdict": "PASS" if predicted >= C2_THRESHOLD else "FAIL",
    }


def criterion_3(scen: dict) -> dict:
    total = actual = predicted = 0
    runs = runs_of(BASE_LOG, "M1P1")
    for run in runs:
        sc = scen.get(run["scenario_id"])
        if sc is None:
            continue
        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored"):
                continue
            total += 1
            actual += turn["decision"] == turn["expected_decision"]
            predicted += p4_decision(run, turn, spec) == turn["expected_decision"]
    rate_actual = actual / total if total else float("nan")
    rate_p4 = predicted / total if total else float("nan")
    return {
        "m1p1_runs": len(runs), "scored_turns": total,
        "m1p1_agreement": rate_actual, "p4_agreement": rate_p4,
        "drop": rate_actual - rate_p4, "max_drop": C3_MAX_DROP,
        "verdict": "PASS" if rate_actual - rate_p4 <= C3_MAX_DROP else "FAIL",
    }


def main() -> int:
    scen_adv = ev.load_scenarios(CP / "scenarios_adversarial")
    scen_orig = ev.load_scenarios(CP / "scenarios")
    out = {
        "source_logs": {"adversarial": str(ADV_LOG.relative_to(CP)),
                        "original": str(BASE_LOG.relative_to(CP))},
        "C1_misread_turns_fixed": criterion_1(scen_adv),
        "C2_tcar_maintained": criterion_2(scen_adv),
        "C3_regression": criterion_3(scen_orig),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    c1, c2, c3 = out["C1_misread_turns_fixed"], out["C2_tcar_maintained"], out["C3_regression"]
    print(f"C1 {c1['verdict']}: 기준① 사건 {c1['events']}건 중 P4 가 막는 것 {c1['fixed_by_p4']}건")
    for e in c1["remaining"]:
        print(f"  잔존: {e['scenario_id']} s{e['seed']} t{e['turn']} "
              f"nlu={e['nlu_predicate']} speech_act={e['speech_act']} → {e['p4_decision']}")
    print(f"C2 {c2['verdict']}: 수용해야 할 턴 {c2['should_accept_turns']}개 중 "
          f"M1P1 {c2['m1p1_accepted']} (TCAR {c2['m1p1_tcar']:.4f}) → "
          f"P4 예측 {c2['p4_accepted']} (TCAR {c2['p4_tcar']:.4f}), 기준 {c2['threshold_accepted']}")
    print(f"C3 {c3['verdict']}: M1P1 {c3['m1p1_runs']}회 {c3['scored_turns']}턴, "
          f"일치율 {c3['m1p1_agreement']:.4f} → P4 {c3['p4_agreement']:.4f} "
          f"(하락 {c3['drop']:+.4f}, 허용 {c3['max_drop']})")
    print(f"\n저장: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
