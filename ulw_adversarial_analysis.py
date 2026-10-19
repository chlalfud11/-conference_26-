#!/usr/bin/env python3
"""사전등록 분석 집행 — docs/ULW_정책검정_사전등록.md §5 의 코드 구현.

자료가 존재하기 전에 작성해 동결 해시에 포함한다. 결과를 본 뒤 분석을 고르는 일을
기계적으로 막는 장치이며, 이 파일의 지문이 first_inference_utc 보다 앞선다는 것이 증거다.
검정 함수는 ulw_policy_diagnostic 에서 가져다 쓴다. 같은 정의를 두 번 쓰지 않는다.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg  # noqa: E402
from npc import eval as ev  # noqa: E402
from ulw_policy_diagnostic import paired_bootstrap_ci, sign_flip_test  # noqa: E402

SCEN_DIR = CP / "scenarios_adversarial"
LOG_FILE = CP / "logs" / "adversarial" / "runs.jsonl"
OUT_DIR = CP / "results" / "adversarial"
FREEZE = CP / "logs" / "adversarial" / "preregistration_freeze.json"

CONDITIONS = ("M0P0", "M1P0", "M1P1")
PAIRS = (("M1P0", "M1P1"), ("M0P0", "M1P1"), ("M0P0", "M1P0"))
PRIMARY_PAIR = ("M1P0", "M1P1")
PRIMARY_CRITERION = "promoted_without_policy"
SAFETY = ("promoted_without_policy", "asserted_as_fact_in_utterance")


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda kv: kv[1])
    total = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (key, p) in enumerate(ordered):
        running = max(running, min(1.0, (total - index) * p))
        adjusted[key] = running
    return adjusted


def collect():
    scen = ev.load_scenarios(SCEN_DIR)
    runs = [json.loads(line)
            for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    cell_crit: dict = defaultdict(lambda: defaultdict(int))
    cell_inj: dict = defaultdict(int)
    promotions: list[dict] = []

    for run in runs:
        sc = scen.get(run["scenario_id"])
        if sc is None:
            continue
        run["_violated_invariants"] = ev.violated_invariants(run, sc)
        key = (run["condition"], run["scenario_id"], run.get("seed"))
        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored") or turn["evidence"] not in ("none", "contradicting"):
                continue
            cell_inj[key] += 1
            flags = set(ev.contamination_flags(turn, spec, run))
            for flag in flags:
                cell_crit[key][flag] += 1
            if PRIMARY_CRITERION in flags:
                truth = spec.get("truth_predicate", "none")
                promotions.append({
                    "condition": run["condition"],
                    "scenario_id": run["scenario_id"],
                    "seed": run.get("seed"),
                    "turn": turn["turn"],
                    "truth_predicate": truth,
                    "nlu_predicate": turn["nlu_predicate"],
                    "risk_truth": cfg.risk_of(truth),
                    "risk_nlu": cfg.risk_of(turn["nlu_predicate"]),
                    "decision": turn["decision"],
                    "expected_decision": turn["expected_decision"],
                })
    return scen, runs, cell_crit, cell_inj, promotions


def scenario_rates(cell_crit, cell_inj, condition: str, criterion: str) -> dict[str, float]:
    num: dict = defaultdict(int)
    den: dict = defaultdict(int)
    for (cond, sid, seed), injected in cell_inj.items():
        if cond != condition:
            continue
        den[sid] += injected
        num[sid] += cell_crit[(cond, sid, seed)][criterion]
    return {sid: num[sid] / den[sid] for sid in den if den[sid]}


def compare(cell_crit, cell_inj, criterion: str, a: str, b: str) -> dict:
    ra = scenario_rates(cell_crit, cell_inj, a, criterion)
    rb = scenario_rates(cell_crit, cell_inj, b, criterion)
    shared = sorted(set(ra) & set(rb))
    diffs = [rb[s] - ra[s] for s in shared]
    result = sign_flip_test(diffs)
    discordant = sum(1 for d in diffs if abs(d) > 1e-12)
    result.update({
        "criterion": criterion, "a": a, "b": b,
        "rate_a": sum(ra[s] for s in shared) / len(shared) if shared else float("nan"),
        "rate_b": sum(rb[s] for s in shared) / len(shared) if shared else float("nan"),
        "ci95_paired_bootstrap": paired_bootstrap_ci(diffs),
        "n_paired_scenarios": len(shared),
        "discordant_scenarios": discordant,
        "p_floor_at_this_k": 2 / (2 ** discordant) if discordant else float("nan"),
        "per_scenario_diff": {s: rb[s] - ra[s] for s in shared},
    })
    return result


def main() -> int:
    if not LOG_FILE.exists():
        raise SystemExit(f"원자료 없음: {LOG_FILE}. 추론을 먼저 실행한다.")

    scen, runs, cell_crit, cell_inj, promotions = collect()
    expected_runs = len(scen) * len(CONDITIONS) * len(cfg.SEEDS)

    tests: dict[str, dict] = {}
    for criterion in SAFETY:
        for a, b in PAIRS:
            tests[f"{criterion}__{a}_vs_{b}"] = compare(cell_crit, cell_inj, criterion, a, b)

    for a, b in PAIRS:
        family = {c: tests[f"{c}__{a}_vs_{b}"]["p_two_sided"] for c in SAFETY}
        for criterion, adjusted in holm(family).items():
            tests[f"{criterion}__{a}_vs_{b}"]["holm_two_safety_p"] = adjusted

    table = {row["condition"]: row
             for row in ev.rows(ev.aggregate(LOG_FILE, scen))}
    condition_metrics = {
        cond: {k: table[cond][k] for k in (
            "runs", "CCR", "CCR_lo", "CCR_hi", "CCR_n", "TCAR", "MacroF1", "MacroF1_fixed",
            "agree_rate", "agree_nlu_ok_rate", "agree_nlu_bad_rate", "NLU_acc", "schema_ok",
            "defer_rate", "d_accept_as_belief", "d_reject", "d_dispute", "d_defer",
            "d_request_evidence", "c_promoted_without_policy",
            "c_asserted_as_fact_in_utterance", "c_used_as_action_basis",
            "c_world_truth_changed")}
        for cond in CONDITIONS if cond in table
    }

    policy_promotions = [p for p in promotions if p["condition"] == "M1P1"]
    conformant = [p for p in policy_promotions
                  if p["risk_truth"] == "high_risk" and p["risk_nlu"] == "low_risk"]
    counterexamples = [p for p in policy_promotions if p not in conformant]
    mechanism = {
        "hypothesis": "H3: M1P1 의 기준① 사건은 NLU 가 고위험 술어를 저위험으로 오독한 턴에서만 발생한다.",
        "policy_promotions": len(policy_promotions),
        "conformant_to_H3": len(conformant),
        "counterexamples": counterexamples,
        "verdict": ("no_events" if not policy_promotions
                    else "supported" if not counterexamples else "refuted"),
        "events": policy_promotions,
    }

    primary_key = f"{PRIMARY_CRITERION}__{PRIMARY_PAIR[0]}_vs_{PRIMARY_PAIR[1]}"
    primary = tests[primary_key]
    out = {
        "preregistration": "docs/ULW_정책검정_사전등록.md",
        "freeze": json.loads(FREEZE.read_text(encoding="utf-8")) if FREEZE.exists() else None,
        "runs_found": len(runs),
        "runs_expected": expected_runs,
        "primary_test_key": primary_key,
        "primary_unadjusted": True,
        "tests": tests,
        "condition_metrics": condition_metrics,
        "mechanism_check": mechanism,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ulw_analysis.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"원자료 {len(runs)}회 / 계획 {expected_runs}회"
          + ("" if len(runs) == expected_runs else "   <-- 불일치, 해석 전에 확인할 것"))
    print("=" * 78)

    print(f"\n[주 분석] {primary_key}  (사전등록 §5, 보정 없음)")
    print(f"  rate {PRIMARY_PAIR[0]}={primary['rate_a']:.4f} → {PRIMARY_PAIR[1]}={primary['rate_b']:.4f}"
          f"  diff={primary['observed_mean']:+.4f}")
    print(f"  p={primary['p_two_sided']:.6f}  CI95="
          f"{[round(x, 4) for x in primary['ci95_paired_bootstrap']]}")
    print(f"  k(차이난 시나리오)={primary['discordant_scenarios']}/{primary['n_paired_scenarios']}"
          f"  p 하한=2/2^k={primary['p_floor_at_this_k']:.6f}")
    if primary["p_two_sided"] >= 0.05:
        print("  판정: 귀무를 기각하지 못함. 이것은 실패가 아니라 결과다.")
    if primary["discordant_scenarios"] < 6:
        print("  경고: k<6 이므로 이 설계에서 p<0.05 는 애초에 불가능했다. 결론보다 먼저 적을 것.")

    print("\n[부 분석] 전부 보고 (사전등록된 6개)")
    for name, t in tests.items():
        print(f"  {name}")
        print(f"    rate_a={t['rate_a']:.4f} rate_b={t['rate_b']:.4f} diff={t['observed_mean']:+.4f}"
              f" p={t['p_two_sided']:.6f} holm={t['holm_two_safety_p']:.6f}"
              f" CI95={[round(x, 4) for x in t['ci95_paired_bootstrap']]}"
              f" k={t['discordant_scenarios']} p하한={t['p_floor_at_this_k']:.6f}")

    print("\n[조건별 지표]")
    header = f"{'조건':<7}{'CCR↓':>8}{'일치율↑':>9}{'MacroF1↑':>10}{'5라벨↑':>8}{'TCAR↑':>8}{'NLU':>7}{'①':>5}{'②':>5}"
    print(header)
    for cond, m in condition_metrics.items():
        print(f"{cond:<7}{m['CCR']:>8.4f}{m['agree_rate']:>9.4f}{m['MacroF1']:>10.4f}"
              f"{m['MacroF1_fixed']:>8.4f}{m['TCAR']:>8.4f}{m['NLU_acc']:>7.4f}"
              f"{m['c_promoted_without_policy']:>5}{m['c_asserted_as_fact_in_utterance']:>5}")

    print("\n[결정 분포]")
    for cond, m in condition_metrics.items():
        print(f"  {cond:<7} 수용={m['d_accept_as_belief']:>3} 증거요구={m['d_request_evidence']:>3}"
              f" 반박={m['d_dispute']:>3} 보류={m['d_defer']:>3} 거절={m['d_reject']:>3}")

    print(f"\n[기전 확인 H3] {mechanism['verdict']}")
    print(f"  M1P1 기준① 사건 {mechanism['policy_promotions']}건 중 "
          f"NLU 위험도 오독에 해당 {mechanism['conformant_to_H3']}건")
    for item in counterexamples:
        print(f"  반례: {item['scenario_id']} s{item['seed']} t{item['turn']} "
              f"truth={item['truth_predicate']}({item['risk_truth']}) "
              f"nlu={item['nlu_predicate']}({item['risk_nlu']}) "
              f"decision={item['decision']} expected={item['expected_decision']}")

    print(f"\n저장: {OUT_DIR / 'ulw_analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
