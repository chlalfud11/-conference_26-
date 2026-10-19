#!/usr/bin/env python3
"""승격 정책 진단 — 기존 432회 자료만 사용. 새 추론 0건, 기존 파일 수정 0건.

질문: 승격 정책(M1P1)의 효과가 안 보이는 것이 정책이 약해서인가,
      지표가 정책이 통제하지 않는 계층을 재고 있어서인가.

기준 정의는 재구현하지 않고 npc.eval 의 함수를 그대로 import 해서 쓴다.
따라서 이 집계가 기존 metrics.csv 와 어긋나면 그건 내 버그가 아니라 자료 불일치다.
trust 는 턴이 아니라 시나리오 단위 필드다 (npc/runner.py:240).
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg  # noqa: E402
from npc import eval as ev  # noqa: E402

BOOTSTRAP_N = 10_000  # 요구사항 정리.md:816 의 사전 규약
RNG_SEED = 20261014


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_flip_test(diffs: list[float]) -> dict:
    """부호 뒤집기 순열검정. n<=20 이면 2^n 전수, 아니면 표본."""
    n = len(diffs)
    if n == 0:
        return {"observed_mean": float("nan"), "p_two_sided": float("nan"),
                "permutations": 0}
    obs = sum(diffs) / n
    if n <= 20:
        total = hits = 0
        for signs in itertools.product((1, -1), repeat=n):
            m = sum(s * d for s, d in zip(signs, diffs)) / n
            total += 1
            if abs(m) >= abs(obs) - 1e-12:
                hits += 1
        return {"observed_mean": obs, "p_two_sided": hits / total,
                "permutations": total, "exhaustive": True}
    rng = random.Random(RNG_SEED)
    total, hits = 100_000, 0
    for _ in range(total):
        m = sum(d if rng.random() < 0.5 else -d for d in diffs) / n
        if abs(m) >= abs(obs) - 1e-12:
            hits += 1
    return {"observed_mean": obs, "p_two_sided": hits / total,
            "permutations": total, "exhaustive": False}


def paired_bootstrap_ci(diffs: list[float]) -> list[float]:
    rng = random.Random(RNG_SEED)
    n = len(diffs)
    if n == 0:
        return [float("nan"), float("nan")]
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(BOOTSTRAP_N))
    return [means[int(0.025 * BOOTSTRAP_N)], means[int(0.975 * BOOTSTRAP_N) - 1]]


def required_n_two_proportion(p1: float, p2: float) -> float:
    """양측 alpha=0.05, 검정력 80% 에서 두 비율 차이를 검출하는 조건별 표본 수."""
    d = abs(p1 - p2)
    if d == 0:
        return float("inf")
    z_a, z_b = 1.959963985, 0.8416212336
    return (z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (d * d)


def main() -> int:
    scen = ev.load_scenarios(CP / "scenarios")
    runs = [json.loads(line)
            for line in (CP / "logs" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]

    sample_run = runs[0]
    structure = {
        "n_runs": len(runs),
        "n_scenarios": len(scen),
        "run_keys": sorted(sample_run),
        "turn_keys": sorted(sample_run["turns"][0]),
        "spec_keys": sorted(scen[sample_run["scenario_id"]]["turns"][0]),
        "scenario_keys": sorted(scen[sample_run["scenario_id"]]),
    }

    cell_crit: dict = defaultdict(lambda: defaultdict(int))
    cell_inj: dict = defaultdict(int)
    cond_crit: dict = defaultdict(lambda: defaultdict(int))
    cond_inj: dict = defaultdict(int)

    high_risk_turns = 0
    crit1_eligible_turns = 0
    trust_values: dict = defaultdict(int)
    scored_turns_total = 0
    per_scenario: dict = {}

    action_dep_scenarios = sorted(
        sid for sid, s in scen.items()
        if any(t.get("action_depends_on_claim") for t in s["turns"]))
    action_dep_turns = sum(
        1 for s in scen.values() for t in s["turns"] if t.get("action_depends_on_claim"))
    scenarios_with_invariants = sorted(
        sid for sid, s in scen.items() if (s.get("invariants") or {}))
    invariant_violations = 0

    for run in runs:
        sc = scen.get(run["scenario_id"])
        if sc is None:
            continue
        run["_violated_invariants"] = ev.violated_invariants(run, sc)
        invariant_violations += len(run["_violated_invariants"])
        trust = cfg.clamp_trust(sc.get("trust", 1))
        key = (run["condition"], run["scenario_id"], run.get("seed"))
        row = per_scenario.setdefault(run["scenario_id"], {
            "trust": trust,
            "type": sc.get("type"),
            "scored_turns": 0,
            "high_risk_evidence_none": 0,
            "crit1_eligible": 0,
            "declares_invariants": bool(sc.get("invariants")),
            "scored_truth_predicates": sorted(
                {t.get("truth_predicate", "none") for t in sc["turns"] if t.get("scored")}),
        })
        first_pass = row["scored_turns"] == 0

        for turn, spec in zip(run["turns"], sc["turns"]):
            if not spec.get("scored"):
                continue
            scored_turns_total += 1
            trust_values[trust] += 1
            risk = cfg.risk_of(spec.get("truth_predicate", "none"))
            eligible = (risk == "high_risk"
                        and spec.get("evidence") == "none"
                        and trust >= cfg.TRUST_ACCEPT_THRESHOLD)
            if risk == "high_risk":
                high_risk_turns += 1
            if eligible:
                crit1_eligible_turns += 1
            if first_pass:
                row["scored_turns"] += 1
                row["high_risk_evidence_none"] += int(
                    risk == "high_risk" and spec.get("evidence") == "none")
                row["crit1_eligible"] += int(eligible)
            if turn["evidence"] not in ("none", "contradicting"):
                continue
            cell_inj[key] += 1
            cond_inj[run["condition"]] += 1
            for flag in set(ev.contamination_flags(turn, spec, run)):
                cell_crit[key][flag] += 1
                cond_crit[run["condition"]][flag] += 1

    csv_rows = {r["condition"]: r for r in csv.DictReader((CP / "results" / "metrics.csv").open())}
    csv_map = {
        "world_truth_changed": "c_world_truth_changed",
        "promoted_without_policy": "c_promoted_without_policy",
        "used_as_action_basis": "c_used_as_action_basis",
        "asserted_as_fact_in_utterance": "c_asserted_as_fact_in_utterance",
    }
    mismatches = []
    recount = {}
    for cond in csv_rows:
        recount[cond] = {"injected": cond_inj[cond]}
        for crit, col in csv_map.items():
            mine, theirs = cond_crit[cond][crit], int(csv_rows[cond][col])
            recount[cond][crit] = mine
            if mine != theirs:
                mismatches.append({"condition": cond, "criterion": crit,
                                   "recount": mine, "metrics_csv": theirs})
        if cond_inj[cond] != int(csv_rows[cond]["CCR_n"]):
            mismatches.append({"condition": cond, "criterion": "injected_denominator",
                               "recount": cond_inj[cond],
                               "metrics_csv": int(csv_rows[cond]["CCR_n"])})

    def scenario_rate(cond: str, crit: str) -> dict[str, float]:
        num: dict = defaultdict(int)
        den: dict = defaultdict(int)
        for (c, sid, seed), inj in cell_inj.items():
            if c != cond:
                continue
            den[sid] += inj
            num[sid] += cell_crit[(c, sid, seed)][crit]
        return {sid: (num[sid] / den[sid] if den[sid] else float("nan")) for sid in den}

    tests = {}
    for crit in ("promoted_without_policy", "asserted_as_fact_in_utterance"):
        for a, b in (("M1P0", "M1P1"), ("M0P0", "M1P1"), ("M0P0", "M1P0")):
            ra, rb = scenario_rate(a, crit), scenario_rate(b, crit)
            shared = sorted(set(ra) & set(rb))
            diffs = [rb[s] - ra[s] for s in shared]
            res = sign_flip_test(diffs)
            res["ci95_paired_bootstrap"] = paired_bootstrap_ci(diffs)
            res["n_paired_scenarios"] = len(shared)
            res["rate_a"] = sum(ra[s] for s in shared) / len(shared) if shared else float("nan")
            res["rate_b"] = sum(rb[s] for s in shared) / len(shared) if shared else float("nan")
            res["discordant_scenarios"] = sum(1 for d in diffs if abs(d) > 1e-12)
            res["p_floor_at_this_k"] = 2 / (2 ** res["discordant_scenarios"]) \
                if res["discordant_scenarios"] else float("nan")
            tests[f"{crit}__{a}_vs_{b}"] = res

    power = {
        "current_injected_turns_per_condition": cond_inj.get("M1P1", 0),
        "ccr_M0P0_vs_M1P1": {
            "p1": float(csv_rows["M0P0"]["CCR"]), "p2": float(csv_rows["M1P1"]["CCR"]),
            "required_n_per_condition_power80": required_n_two_proportion(
                float(csv_rows["M0P0"]["CCR"]), float(csv_rows["M1P1"]["CCR"])),
        },
        "crit2_M1P0_vs_M1P1": {
            "p1": cond_crit["M1P0"]["asserted_as_fact_in_utterance"] / cond_inj["M1P0"],
            "p2": cond_crit["M1P1"]["asserted_as_fact_in_utterance"] / cond_inj["M1P1"],
            "note": "M1P1 이 더 높다. 표본을 늘리면 '정책이 발화 계층에서 더 나쁘다'가 유의해진다.",
        },
        "sign_flip_p_floor_by_discordant_k": {str(k): 2 / (2 ** k) for k in range(3, 11)},
        "scenarios_needed_for_p_below_005": 6,
    }

    coverage_gap = {
        "trust_accept_threshold": cfg.TRUST_ACCEPT_THRESHOLD,
        "trust_source": "scenario-level field 'trust' (npc/runner.py:240)",
        "trust_histogram_over_scored_turns": dict(sorted(trust_values.items())),
        "scenarios_by_trust": {
            str(t): sorted(sid for sid, r in per_scenario.items() if r["trust"] == t)
            for t in sorted({r["trust"] for r in per_scenario.values()})},
        "scored_turns_total_all_conditions": scored_turns_total,
        "high_risk_scored_turns_all_conditions": high_risk_turns,
        "crit1_eligible_turns_all_conditions": crit1_eligible_turns,
        "crit1_eligibility_rule": (
            "CCR 분모 내에서는 evidence=='none' 이므로 M1P1 에서 기준① 이 뜨려면 "
            "true risk==high_risk AND evidence=='none' AND trust>=수용임계값 인 턴에서 "
            "NLU 가 위험도를 low_risk 로 잘못 읽어야 한다. 그런 턴이 0 이면 ①은 설계상 0 이다."),
        "action_depends_on_claim_scenarios": action_dep_scenarios,
        "action_depends_on_claim_turns": action_dep_turns,
        "scenarios_declaring_invariants": scenarios_with_invariants,
        "invariant_violations_observed": invariant_violations,
        "per_scenario": per_scenario,
    }

    preserved = {}
    for rel in ("logs/runs.jsonl", "results/metrics.csv", "npc/eval.py", "npc/config.py",
                "npc/runner.py", "npc/adapters.py", "results/paper_values.json",
                "paper/draft.md", "results/M1P3_실험결과.md"):
        p = CP / rel
        if p.exists():
            preserved[rel] = sha256(p)

    out = {
        "generated_at_kst": "2026-10-14",
        "purpose": "승격 정책 효과의 측정 타당성 진단. 새 추론 없음.",
        "structure": structure,
        "recount_vs_metrics_csv": recount,
        "recount_mismatches": mismatches,
        "coverage_gap": coverage_gap,
        "decision_layer_test": tests,
        "power": power,
    }
    (CP / "results" / "ulw_policy_diagnostic.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (CP / "results" / "ulw_preservation.json").write_text(
        json.dumps({"recorded_at_kst": "2026-10-14", "sha256": preserved},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"런 {structure['n_runs']}개, 시나리오 {structure['n_scenarios']}편")
    print("=" * 78)

    print("\n[1] 기준별 분리 집계 (주입 턴 분모)")
    print(f"{'조건':<8}{'분모':>6}{'①승격':>8}{'②단정':>8}{'③행동':>8}{'④세계':>8}")
    for cond in csv_rows:
        r = recount[cond]
        print(f"{cond:<8}{r['injected']:>6}"
              f"{r['promoted_without_policy']:>8}{r['asserted_as_fact_in_utterance']:>8}"
              f"{r['used_as_action_basis']:>8}{r['world_truth_changed']:>8}")
    print(f"\nmetrics.csv 대조 불일치: {mismatches if mismatches else '없음'}")

    cg = coverage_gap
    print("\n[2] 커버리지 공백")
    print(f"  trust 수용 임계값   : {cg['trust_accept_threshold']}  ({cg['trust_source']})")
    for t, v in cg["scenarios_by_trust"].items():
        print(f"  trust={t} 시나리오    : {len(v)}편  {v}")
    print(f"  고위험 채점 턴      : {cg['high_risk_scored_turns_all_conditions']}")
    print(f"  ① 가동 가능 턴     : {cg['crit1_eligible_turns_all_conditions']}"
          "   <-- 0 이면 M1P1 의 ①=0 은 성능이 아니라 설계")
    print(f"  ③ 가동 가능 턴     : {cg['action_depends_on_claim_turns']}"
          "   <-- 0 이면 전 조건 가동 불가")
    print(f"  invariants 선언     : {len(cg['scenarios_declaring_invariants'])}편,"
          f" 위반 관측 {cg['invariant_violations_observed']}"
          "   <-- 0 이면 ④ 가동 불가")
    print("\n  시나리오별 (trust / 채점턴 / 고위험·미증거 / ①가동가능 / 유형 / 채점 술어)")
    for sid in sorted(cg["per_scenario"]):
        r = cg["per_scenario"][sid]
        print(f"    {sid:<9} t={r['trust']}  채점={r['scored_turns']:>2}"
              f"  고위험·미증거={r['high_risk_evidence_none']:>2}"
              f"  ①가능={r['crit1_eligible']:>2}  {str(r['type']):<22}"
              f"{r['scored_truth_predicates']}")

    print("\n[3] 결정 계층 vs 발화 계층 (시나리오 페어 부호뒤집기 전수 + paired bootstrap CI)")
    for name, t in tests.items():
        print(f"  {name}")
        print(f"    rate_a={t['rate_a']:.4f} rate_b={t['rate_b']:.4f} "
              f"diff={t['observed_mean']:+.4f} p={t['p_two_sided']:.6f} "
              f"CI95={[round(x, 4) for x in t['ci95_paired_bootstrap']]} "
              f"n={t['n_paired_scenarios']} k(차이난 시나리오)={t['discordant_scenarios']} "
              f"p하한={t['p_floor_at_this_k']:.6f}")

    print("\n[4] 검정력")
    pw = power["ccr_M0P0_vs_M1P1"]
    print(f"  현재 조건별 주입 턴 : {power['current_injected_turns_per_condition']}")
    print(f"  CCR M0P0={pw['p1']:.4f} vs M1P1={pw['p2']:.4f}"
          f" → 80% 검정력에 조건별 {pw['required_n_per_condition_power80']:.0f} 턴 필요")
    c2 = power["crit2_M1P0_vs_M1P1"]
    print(f"  기준② M1P0={c2['p1']:.4f} vs M1P1={c2['p2']:.4f} → {c2['note']}")
    print(f"  부호뒤집기 p 하한 = 2/2^k → p<0.05 에는 차이나는 시나리오 "
          f"k>={power['scenarios_needed_for_p_below_005']} 필요")

    print("\n저장: results/ulw_policy_diagnostic.json, results/ulw_preservation.json")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
