"""P4 사전등록 분석 집행 — docs/ULW_정책v2_사전등록.md §4 구현 (2026-10-15).

검정 함수는 ulw_adversarial_analysis / ulw_policy_diagnostic 에서 가져다 쓴다.
이 파일의 지문은 logs/policy_v2/analysis_freeze.json 에 추론 진행 중 시점으로 봉인된다.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg  # noqa: E402
from npc import eval as ev  # noqa: E402
from ulw_adversarial_analysis import compare, holm, scenario_rates  # noqa: E402

SCEN_DIRS = (CP / "scenarios", CP / "scenarios_adversarial")
BASE_LOGS = (CP / "logs" / "runs.jsonl", CP / "logs" / "adversarial" / "runs.jsonl")
V2_LOG = CP / "logs" / "policy_v2" / "runs.jsonl"
MERGED = CP / "logs" / "policy_v2" / "merged_runs.jsonl"
OUT_DIR = CP / "results" / "policy_v2"
FREEZE = CP / "logs" / "policy_v2" / "preregistration_freeze.json"

BASELINES = ("M0P0", "M1P0", "M1P1")
PAIRS = (("M1P0", "M1P4"), ("M1P1", "M1P4"), ("M0P0", "M1P4"))
PRIMARY_PAIR = ("M1P0", "M1P4")
PRIMARY_CRITERION = "promoted_without_policy"
SAFETY = ("promoted_without_policy", "asserted_as_fact_in_utterance")

cfg.CONDITIONS.setdefault("M1P4", {
    "label": "구조화 기억 + 승격 정책(fail-closed)",
    "memory": "structured",
    "fields": ("type", "text", "source", "verified", "confidence"),
    "decider": "decision_table_v2",
    "note": "speech_act=claim 이고 술어를 못 읽은 턴을 고위험으로 처리한다.",
})


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    n = a + b + c + d
    if n == 0:
        return float("nan")
    row1, col1 = a + b, a + c

    def prob(x: int) -> float:
        return math.comb(row1, x) * math.comb(n - row1, col1 - x) / math.comb(n, col1)

    lo, hi = max(0, col1 - (n - row1)), min(row1, col1)
    observed = prob(a)
    return min(1.0, sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= observed + 1e-12))


def load_scenarios() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for folder in SCEN_DIRS:
        merged.update(ev.load_scenarios(folder))
    return merged


def merge_runs() -> list[dict]:
    seen: set[str] = set()
    runs: list[dict] = []
    sources = [(path, BASELINES) for path in BASE_LOGS] + [(V2_LOG, ("M1P4",))]
    for path, keep in sources:
        if not path.exists():
            raise SystemExit(f"원자료 없음: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            run = json.loads(line)
            if run["condition"] not in keep or run["run_id"] in seen:
                continue
            seen.add(run["run_id"])
            runs.append(run)
    MERGED.parent.mkdir(parents=True, exist_ok=True)
    MERGED.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs), encoding="utf-8")
    return runs


def collect(runs: list[dict], scen: dict[str, dict]):
    cell_crit: dict = defaultdict(lambda: defaultdict(int))
    cell_inj: dict = defaultdict(int)
    events: list[dict] = []
    trigger: dict = defaultdict(lambda: defaultdict(int))

    for run in runs:
        sc = scen.get(run["scenario_id"])
        if sc is None:
            continue
        run["_violated_invariants"] = ev.violated_invariants(run, sc)
        key = (run["condition"], run["scenario_id"], run.get("seed"))
        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored"):
                continue
            speech_act = (turn.get("nlu") or {}).get("speech_act", "other")
            fail_closed_case = speech_act == "claim" and turn["nlu_predicate"] == "none"
            if fail_closed_case:
                trigger[run["condition"]][turn["decision"]] += 1
            if turn["evidence"] not in ("none", "contradicting"):
                continue
            cell_inj[key] += 1
            flags = set(ev.contamination_flags(turn, spec, run))
            for flag in flags:
                cell_crit[key][flag] += 1
            if PRIMARY_CRITERION in flags:
                truth = spec.get("truth_predicate", "none")
                events.append({
                    "condition": run["condition"], "scenario_id": run["scenario_id"],
                    "seed": run.get("seed"), "turn": turn["turn"],
                    "truth_predicate": truth, "nlu_predicate": turn["nlu_predicate"],
                    "speech_act": speech_act,
                    "risk_truth": cfg.risk_of(truth),
                    "risk_nlu": cfg.risk_of(turn["nlu_predicate"]),
                    "fail_closed_case": fail_closed_case,
                    "decision": turn["decision"],
                    "expected_decision": turn["expected_decision"],
                })
    return cell_crit, cell_inj, events, trigger


def main() -> int:
    scen = load_scenarios()
    runs = merge_runs()
    cell_crit, cell_inj, events, trigger = collect(runs, scen)
    stats = ev.aggregate(MERGED, scen)
    table = ev.rows(stats)
    by_condition = {row["condition"]: row for row in table}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "metrics_v2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    tests: dict[str, dict] = {}
    for criterion in SAFETY:
        for a, b in PAIRS:
            tests[f"{criterion}__{a}_vs_{b}"] = compare(cell_crit, cell_inj, criterion, a, b)
    for a, b in PAIRS:
        family = {c: tests[f"{c}__{a}_vs_{b}"]["p_two_sided"] for c in SAFETY}
        for criterion, adjusted in holm(family).items():
            tests[f"{criterion}__{a}_vs_{b}"]["holm_two_safety_p"] = adjusted

    tcar_tests = {}
    for a, b in PAIRS:
        sa, sb = stats.get(a), stats.get(b)
        if sa is None or sb is None:
            continue
        ya, na = sa.correctly_accepted, sa.should_accept - sa.correctly_accepted
        yb, nb = sb.correctly_accepted, sb.should_accept - sb.correctly_accepted
        tcar_tests[f"TCAR__{a}_vs_{b}"] = {
            "a": a, "b": b,
            "accepted_a": ya, "n_a": sa.should_accept,
            "accepted_b": yb, "n_b": sb.should_accept,
            "rate_a": ya / sa.should_accept if sa.should_accept else float("nan"),
            "rate_b": yb / sb.should_accept if sb.should_accept else float("nan"),
            "p_fisher_two_sided": fisher_two_sided(ya, na, yb, nb),
        }

    v2_events = [e for e in events if e["condition"] == "M1P4"]
    scope_violations = [e for e in v2_events if e["fail_closed_case"]]
    mechanism = {
        "hypothesis": "P4 가 열어둔 경로(speech_act=claim & predicate=none)에서는 기준① 이 발생할 수 없다.",
        "m1p4_events": len(v2_events),
        "fail_closed_scope_violations": len(scope_violations),
        "verdict": ("no_events" if not v2_events
                    else "implementation_consistent" if not scope_violations else "refuted"),
        "events": v2_events,
        "fail_closed_turn_decisions": {c: dict(d) for c, d in trigger.items()},
    }

    primary_key = f"{PRIMARY_CRITERION}__{PRIMARY_PAIR[0]}_vs_{PRIMARY_PAIR[1]}"
    primary = tests[primary_key]
    out = {
        "preregistration": "docs/ULW_정책v2_사전등록.md",
        "freeze": json.loads(FREEZE.read_text(encoding="utf-8")) if FREEZE.exists() else None,
        "scenarios": len(scen),
        "runs_by_condition": {row["condition"]: row["runs"] for row in table},
        "primary_test_key": primary_key,
        "tests": tests,
        "tcar_tests": tcar_tests,
        "condition_metrics": by_condition,
        "mechanism_check": mechanism,
    }
    (OUT_DIR / "ulw_analysis_v2.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"시나리오 {len(scen)}편 / 런 " + ", ".join(
        f"{row['condition']}={row['runs']}" for row in table))
    print("=" * 78)

    print(f"\n[주 분석 H1] {primary_key}  (사전등록 §4.1, 보정 없음)")
    print(f"  rate {PRIMARY_PAIR[0]}={primary['rate_a']:.4f} → {PRIMARY_PAIR[1]}={primary['rate_b']:.4f}"
          f"  diff={primary['observed_mean']:+.4f}")
    print(f"  p={primary['p_two_sided']:.6f}  CI95="
          f"{[round(x, 4) for x in primary['ci95_paired_bootstrap']]}")
    print(f"  k(차이난 시나리오)={primary['discordant_scenarios']}/{primary['n_paired_scenarios']}"
          f"  p 하한=2/2^k={primary['p_floor_at_this_k']:.6f}")
    print("  판정: " + ("귀무 기각" if primary["p_two_sided"] < 0.05 else "귀무를 기각하지 못함"))

    print("\n[부 분석 H2] TCAR (사전등록 §4.2, Fisher 양측)")
    for name, t in tcar_tests.items():
        print(f"  {name}: {t['accepted_a']}/{t['n_a']}={t['rate_a']:.4f} → "
              f"{t['accepted_b']}/{t['n_b']}={t['rate_b']:.4f}  p={t['p_fisher_two_sided']:.6f}")

    print("\n[보조 비교] 사전등록된 6개 전부")
    for name, t in tests.items():
        print(f"  {name}")
        print(f"    rate_a={t['rate_a']:.4f} rate_b={t['rate_b']:.4f} diff={t['observed_mean']:+.4f}"
              f" p={t['p_two_sided']:.6f} holm={t['holm_two_safety_p']:.6f}"
              f" CI95={[round(x, 4) for x in t['ci95_paired_bootstrap']]}"
              f" k={t['discordant_scenarios']} p하한={t['p_floor_at_this_k']:.6f}")

    print("\n[조건별 지표]")
    print(f"{'조건':<7}{'CCR↓':>8}{'일치율↑':>9}{'MacroF1↑':>10}{'TCAR↑':>8}{'NLU':>7}{'①':>5}{'②':>5}")
    for row in table:
        print(f"{row['condition']:<7}{row['CCR']:>8.4f}{row['agree_rate']:>9.4f}"
              f"{row['MacroF1']:>10.4f}{row['TCAR']:>8.4f}{row['NLU_acc']:>7.4f}"
              f"{row['c_promoted_without_policy']:>5}{row['c_asserted_as_fact_in_utterance']:>5}")

    print("\n[결정 분포]")
    for row in table:
        print(f"  {row['condition']:<7} 수용={row['d_accept_as_belief']:>3}"
              f" 증거요구={row['d_request_evidence']:>3} 반박={row['d_dispute']:>3}"
              f" 보류={row['d_defer']:>3} 거절={row['d_reject']:>3}")

    print(f"\n[기전 확인] {mechanism['verdict']}")
    print(f"  M1P4 기준① {mechanism['m1p4_events']}건, 그중 fail-closed 경로 위반 "
          f"{mechanism['fail_closed_scope_violations']}건")
    for e in v2_events:
        print(f"  잔존: {e['scenario_id']} s{e['seed']} t{e['turn']} "
              f"truth={e['truth_predicate']}({e['risk_truth']}) "
              f"nlu={e['nlu_predicate']}({e['risk_nlu']}) speech_act={e['speech_act']} "
              f"decision={e['decision']} expected={e['expected_decision']}")
    print("\n  fail-closed 대상 턴의 결정 분포:")
    for cond, dist in mechanism["fail_closed_turn_decisions"].items():
        print(f"    {cond:<7} {dist}")

    print(f"\n저장: {OUT_DIR / 'ulw_analysis_v2.json'}, {OUT_DIR / 'metrics_v2.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
