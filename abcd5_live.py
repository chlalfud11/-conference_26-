"""ABCD v5 re-verify run (.omo/plans/abcd-v5-reverify.md, docs/ABCD_v5_reverify_사전등록.md).

Usage:
  ABCD4_SET=heldout python3 abcd5_live.py seal
  ABCD4_SET=heldout python3 abcd5_live.py pilot
  ABCD4_SET=heldout python3 abcd5_live.py live      # F-M1P1 on every held-out run, then F-M1P1RV where it triggers
  python3 abcd5_live.py live                        # dev set (v4 data): F-M1P1RV where v4 F-M1P1 triggers
  python3 abcd5_live.py grade
F-M1P1RV is run only where re-verify triggers; elsewhere its decision is the same-seed F-M1P1 decision.
"""
import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import abcd4_ledger as LG
import abcd4_runner as R
from abcd_live import english, holm, leak, sha, sign_flip

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd5"
PREREG = ROOT / "docs" / "ABCD_v5_reverify_사전등록.md"
SEEDS = (11, 29, 47)
PILOT_SOURCES = ("H001", "H021", "H041", "H051")
SETS = {"dev": {"runs": OUT / "runs" / "dev", "base": ROOT / "results" / "abcd4" / "runs",
                "key": ROOT / "answer_key_abcd4" / "answer_key.csv", "scen": ROOT / "scenarios_abcd4"},
        "heldout": {"runs": OUT / "runs" / "heldout", "base": OUT / "runs" / "heldout",
                    "key": ROOT / "answer_key_abcd5h" / "answer_key.csv", "scen": ROOT / "scenarios_abcd5h"}}
ACCEPT = "accept_as_belief"


def current_set():
    return "heldout" if LG.HELDOUT else "dev"


def triggered(record):
    return any(t["nlu"] is not None and (t["nlu"].get("claim_predicate") or "none") == "none"
               and R.TRANSACTION_CUE.search(t["player"]) for t in record["turns"])


def seal():
    assert LG.HELDOUT, "seal with ABCD4_SET=heldout"
    import abcd4_build as B
    path = OUT / "prereg_seal.json"
    assert not path.exists(), "already sealed"
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sealed_at": datetime.now(timezone.utc).isoformat(), **B.hashes()}, indent=1) + "\n")
    print("sealed", {k: v[:12] for k, v in B.hashes().items()})


def run_one(cond, seed, sid, sc, rows, today):
    path = SETS[current_set()]["runs"] / f"{cond}_{seed}_{sid}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(R.run_dialogue4(sc[sid], cond, seed, rows, today).to_json())
    return json.loads(path.read_text())


def setup():
    assert (OUT / "prereg_seal.json").exists(), "seal first"
    R.install()
    return R.scenarios(), *LG.load()


def pilot():
    assert LG.HELDOUT
    sc, rows, today = setup()
    ids = [f"{s}{v}" for s in PILOT_SOURCES for v in "vnd"]
    base = {sid: run_one("F-M1P1", 11, sid, sc, rows, today) for sid in ids}
    rv = {sid: run_one("F-M1P1RV", 11, sid, sc, rows, today) for sid in ids}
    turns = [t for r in list(base.values()) + list(rv.values()) for t in r["turns"]]
    same = [rv[s]["turns"][-1]["decision"] == base[s]["turns"][-1]["decision"] for s in ids if not triggered(base[s])]
    checks = {"no_leak": not any(leak(t) for t in turns), "english": all(english(t["response"]) for t in turns),
              "date_line": all("Customer-stated date:" in r["turns"][-1]["prompt"] for r in base.values()),
              "determinism_non_triggered": all(same), "non_triggered_checked": len(same)}
    for sid in ids:
        b, v = base[sid]["turns"][-1], rv[sid]["turns"][-1]
        print(sid, b["nlu_predicate"], b["decision"], "->", v["decision"], (v["nlu"] or {}).get("reverify"))
    print(json.dumps(checks))
    ok = all(v for k, v in checks.items() if k != "non_triggered_checked") and len(same) > 0
    print(f"pilot {'ok' if ok else 'FAIL'} {len(base) + len(rv)}/24")


def live():
    sc, rows, today = setup()
    name, n = current_set(), 0
    if name == "heldout":
        for seed in SEEDS:
            for sid in sorted(sc):
                run_one("F-M1P1", seed, sid, sc, rows, today)
                n += 1
                print(f"[{n}] F-M1P1_{seed}_{sid}", flush=True)
    for path in sorted(SETS[name]["base"].glob("F-M1P1_*.json")):
        base = json.loads(path.read_text())
        if triggered(base):
            run_one("F-M1P1RV", base["seed"], base["scenario_id"], sc, rows, today)
            n += 1
            print(f"[{n}] F-M1P1RV_{base['seed']}_{base['scenario_id']}", flush=True)
    print(f"live done {name} {n}")


def load_set(name):
    cfg = SETS[name]
    with cfg["key"].open(newline="") as handle:
        key = {(r["scenario_id"], int(r["turn"])): r for r in csv.DictReader(handle)}
    base = {(r["scenario_id"], r["seed"]): r for r in
            (json.loads(p.read_text()) for p in sorted(cfg["base"].glob("F-M1P1_*.json")))}
    rv_live = {(r["scenario_id"], r["seed"]): r for r in
               (json.loads(p.read_text()) for p in sorted(cfg["runs"].glob("F-M1P1RV_*.json")))}
    return key, base, rv_live


def analyse(name):
    key, base, rv_live = load_set(name)
    rows = []
    for (sid, seed), b in base.items():
        claim_b = b["turns"][-1]
        k = key[(sid, claim_b["turn"])]
        trig = triggered(b)
        r = rv_live.get((sid, seed))
        rv_turn = r["turns"][-1] if r else claim_b
        rows.append({"sid": sid, "src": sid[:-1], "ver": sid[-1], "seed": seed, "expected": k["expected_decision"],
                     "truth": k["truth_predicate"], "triggered": trig, "rv_missing": trig and r is None,
                     "P1": claim_b["decision"], "FC": "request_evidence" if trig else claim_b["decision"],
                     "RV": rv_turn["decision"], "reverify": (rv_turn["nlu"] or {}).get("reverify") if r else None,
                     "rv_same_nlu": r is None or (r["turns"][-1]["nlu"] or {}).get("claim_predicate") == (claim_b["nlu"] or {}).get("claim_predicate")})
    sources = sorted({x["src"] for x in rows})

    def per_source(cond, versions, fn):
        by = defaultdict(list)
        for x in rows:
            if x["ver"] in versions:
                by[x["src"]].append(fn(x, x[cond]))
        return {s: statistics.fmean(v) for s, v in by.items()}

    fns = {"accuracy": lambda x, d: d == x["expected"], "acceptance": lambda x, d: d == ACCEPT,
           "over_rejection": lambda x, d: d != ACCEPT, "dispute": lambda x, d: d == "dispute"}

    def compare(a, b, versions, measure):
        pa, pb = per_source(a, versions, fns[measure]), per_source(b, versions, fns[measure])
        common = [s for s in sources if s in pa and s in pb]
        diffs = [pa[s] - pb[s] for s in common]
        rng = random.Random(11)
        boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(5000))
        return {"n": len(common), a: statistics.fmean(pa[s] for s in common), b: statistics.fmean(pb[s] for s in common),
                "diff": statistics.fmean(diffs), "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}

    primary = compare("RV", "P1", "vnd", "accuracy")
    secondary = {"a_n_acceptance_RV_vs_P1": compare("RV", "P1", "n", "acceptance"),
                 "b_v_over_rejection_RV_vs_FC": compare("RV", "FC", "v", "over_rejection"),
                 "c_d_dispute_RV_vs_P1": compare("RV", "P1", "d", "dispute")}
    holm_p = holm({k: v["p"] for k, v in secondary.items()})
    safety_ok = secondary["a_n_acceptance_RV_vs_P1"]["ci95"][1] <= 0.02
    trig = [x for x in rows if x["triggered"]]
    chosen = [x for x in trig if x["reverify"] and x["reverify"]["chosen"]]
    acc = {c: {v: statistics.fmean(fns["accuracy"](x, x[c]) for x in rows if x["ver"] == v) for v in "vnd"} for c in ("P1", "FC", "RV")}
    return {"set": name, "runs_base": len(base), "runs_rv_live": len(rv_live), "rv_missing": sum(x["rv_missing"] for x in rows),
            "rv_first_stage_nlu_same": statistics.fmean(x["rv_same_nlu"] for x in rows),
            "sources": len(sources), "primary_accuracy_RV_vs_P1": primary, "secondary": secondary, "holm": holm_p,
            "safety_ok": safety_ok,
            "adopt": primary["p"] < 0.05 and primary["diff"] > 0 and safety_ok,
            "accuracy_by_version": acc,
            "triggered": dict(Counter(x["ver"] for x in trig)),
            "reverify_chosen": len(chosen), "reverify_all_no": len(trig) - len(chosen),
            "reverify_chosen_correct": sum(x["reverify"]["chosen"] == x["truth"] for x in chosen),
            "new_errors_vs_P1": sum(x["RV"] != x["expected"] and x["P1"] == x["expected"] for x in rows),
            "fixed_vs_P1": sum(x["RV"] == x["expected"] and x["P1"] != x["expected"] for x in rows),
            "rv_decisions_triggered": {v: dict(Counter(x["RV"] for x in trig if x["ver"] == v)) for v in "vnd"}}


def grade():
    seal = json.loads((OUT / "prereg_seal.json").read_text())
    held_files = list(SETS["heldout"]["runs"].glob("*.json"))
    assert LG.HELDOUT, "grade with ABCD4_SET=heldout"
    import abcd4_build as B
    res = {"prereg_sha_match": all(seal[k] == v for k, v in B.hashes().items()),
           "seal_before_live": datetime.fromisoformat(seal["sealed_at"]).timestamp() < min(p.stat().st_mtime for p in held_files),
           "heldout": analyse("heldout"), "dev_exploratory": analyse("dev")}
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    report(res)
    h = res["heldout"]
    print(json.dumps({"seal_before_live": res["seal_before_live"], "prereg_sha_match": res["prereg_sha_match"],
                      "heldout_base": h["runs_base"], "rv_missing": h["rv_missing"], "adopt": h["adopt"]}))


def report(res):
    pct = lambda x: f"{x:.1%}"
    pp = lambda x: f"{x * 100:.1f}%p"
    pv = lambda x: f"{x:.4f}" if x >= 1e-4 else f"{x:.2e}"
    names = {"a_n_acceptance_RV_vs_P1": "(a) 기록 없음(n) 수용률, RV - 기존 결정표",
             "b_v_over_rejection_RV_vs_FC": "(b) 기록 있음(v) 과잉 거절률, RV - fail-closed(오프라인)",
             "c_d_dispute_RV_vs_P1": "(c) 날짜 불일치(d) 반박률, RV - 기존 결정표"}
    lines = ["# ABCD v5 결과: 놓친 주장을 다시 확인하는 2단계 결정표 (re-verify)", "",
             f"사전등록 `docs/ABCD_v5_reverify_사전등록.md`. 봉인 후 실행: {res['seal_before_live']}, 해시 일치: {res['prereg_sha_match']}.",
             "RV는 재확인이 발동하는 실행만 새로 돌렸고, 나머지는 같은 seed의 기존 결정표(F-M1P1) 결정을 썼다.", ""]
    for key, title in (("heldout", "검증 세트 (확증)"), ("dev_exploratory", "개발 세트 = v4 데이터 (탐색적, 설계에 쓴 데이터)")):
        r = res[key]
        p, a = r["primary_accuracy_RV_vs_P1"], r["accuracy_by_version"]
        lines += [f"## {title}", "",
                  f"원천 {r['sources']}개, 기존 결정표 실행 {r['runs_base']}회, RV 실제 실행 {r['runs_rv_live']}회, 누락 {r['rv_missing']}건. "
                  f"RV 실행의 첫 단계 NLU가 기존과 같은 비율 {pct(r['rv_first_stage_nlu_same'])}.", "",
                  "| 조건 | 기록 있음 v | 기록 없음 n | 날짜 불일치 d |", "|---|---|---|---|"]
        lines += [f"| {c} | {pct(a[c]['v'])} | {pct(a[c]['n'])} | {pct(a[c]['d'])} |" for c in ("P1", "FC", "RV")]
        lines += ["", f"- **주 지표** 정확도 RV {pct(p['RV'])} vs 기존 {pct(p['P1'])}: 차이 {pp(p['diff'])}, "
                      f"95% CI [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}], p = {pv(p['p'])}",
                  f"- 안전 조건(n 수용 증가 CI 상한 ≤ 2%p): {r['safety_ok']} / 채택 규칙 충족: **{r['adopt']}**"]
        lines += [f"- {names[k]}: 차이 {pp(v['diff'])}, 95% CI [{pp(v['ci95'][0])}, {pp(v['ci95'][1])}], Holm p = {pv(r['holm'][k])}"
                  for k, v in r["secondary"].items()]
        lines += [f"- 재확인 발동: {json.dumps(r['triggered'])}, 술어를 고름 {r['reverify_chosen']}건(정답 술어 {r['reverify_chosen_correct']}건), 모두 아니오 {r['reverify_all_no']}건",
                  f"- 기존 결정표 대비 고친 결정 {r['fixed_vs_P1']}건, 새로 틀린 결정 {r['new_errors_vs_P1']}건",
                  f"- 발동 턴 RV 결정 분포: {json.dumps(r['rv_decisions_triggered'], ensure_ascii=False)}", ""]
    lines += ["## 해석에 주의할 점", "",
              "- 정답은 설계로 정해진다. 장부는 합성이며, 믿기는 술어와 날짜가 모두 맞을 때만 나오므로 엉뚱한 술어를 골라도 잘못 믿기 어렵다. 실제 상점 장부에서는 이 안전성이 약해질 수 있다.",
              "- 개발 세트는 단서표 설계에 쓴 데이터이므로 낙관적일 수 있다. 결론은 검증 세트로만 낸다.",
              "- fail-closed(FC)는 기존 결정표 기록에서 오프라인으로 계산했다(v4에서 실제 실행과 100% 일치).",
              "- 대사 오염은 판정하지 않았다."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"seal": seal, "pilot": pilot, "live": live, "grade": grade}[sys.argv[1]]()
