"""ABCD v6 tool-calling baseline T-M1P0 (.omo/plans/abcd-v6-toolcall.md, docs/ABCD_v6_toolcall_사전등록.md).

Usage:
  python3 abcd6_live.py seal
  python3 abcd6_live.py pilot
  python3 abcd6_live.py live                     # v4 set
  ABCD4_SET=heldout python3 abcd6_live.py live   # v5 held-out set
  python3 abcd6_live.py grade
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
from abcd_3way import GROUP
from abcd_live import english, holm, leak, sha, sign_flip

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd6"
PREREG = ROOT / "docs" / "ABCD_v6_toolcall_사전등록.md"
SEEDS = (11, 29, 47)
COND = "T-M1P0"
PILOT_SOURCES = ("A001", "A021", "A041", "A061")
SETS = {"v4": {"base": ROOT / "results" / "abcd4" / "runs", "key": ROOT / "answer_key_abcd4" / "answer_key.csv"},
        "heldout": {"base": ROOT / "results" / "abcd5" / "runs" / "heldout", "key": ROOT / "answer_key_abcd5h" / "answer_key.csv"}}


def runs_dir(name):
    return OUT / "runs" / name


def seal():
    path = OUT / "prereg_seal.json"
    assert not path.exists(), "already sealed"
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sealed_at": datetime.now(timezone.utc).isoformat(), "prereg": sha(PREREG),
                                "v4_seal": sha(ROOT / "results" / "abcd4" / "prereg_seal.json"),
                                "v5_seal": sha(ROOT / "results" / "abcd5" / "prereg_seal.json")}, indent=1) + "\n")
    print("sealed", sha(PREREG)[:12])


def setup():
    assert (OUT / "prereg_seal.json").exists(), "seal first"
    R.install()
    return R.scenarios(), *LG.load()


def run_one(seed, sid, sc, rows, today):
    path = runs_dir("heldout" if LG.HELDOUT else "v4") / f"{COND}_{seed}_{sid}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(R.run_dialogue4(sc[sid], COND, seed, rows, today).to_json())
    return json.loads(path.read_text())


def pilot():
    assert not LG.HELDOUT
    sc, rows, today = setup()
    recs = [run_one(11, f"{s}{v}", sc, rows, today) for s in PILOT_SOURCES for v in "vnd"]
    turns = [t for r in recs for t in r["turns"]]
    tools = [r["turns"][-1]["nlu"]["tool"] for r in recs]
    accounts = [LG.split_who(sc[r["scenario_id"]]["customer"])[1] for r in recs]
    checks = {"no_leak": not any(leak(t) for t in turns), "english": all(english(t["response"]) for t in turns),
              "tool_format_failures": sum(not t["schema_ok"] for t in tools),
              "rows_only_this_customer": all(f"({a})" in row for t, a in zip(tools, accounts) for row in t["result_rows"]),
              "no_verdict_in_prompt": not any("verified:" in t["prompt"] for t in turns)}
    for r, t in zip(recs, tools):
        print(r["scenario_id"], t["call"], t["claim_type"], len(t["result_rows"]), r["turns"][-1]["decision"])
    print(json.dumps(checks))
    ok = checks["no_leak"] and checks["english"] and checks["tool_format_failures"] < 2 \
        and checks["rows_only_this_customer"] and checks["no_verdict_in_prompt"]
    print(f"pilot {'ok' if ok else 'FAIL'} {len(recs)}/12")


def live():
    sc, rows, today = setup()
    n = 0
    for seed in SEEDS:
        for sid in sorted(sc):
            run_one(seed, sid, sc, rows, today)
            n += 1
            print(f"[{n}] {COND}_{seed}_{sid}", flush=True)
    print(f"live done {'heldout' if LG.HELDOUT else 'v4'} {n}")


def claim_rows(name):
    with SETS[name]["key"].open(newline="") as handle:
        key = {(r["scenario_id"], int(r["turn"])): r for r in csv.DictReader(handle)}
    conds = {COND: runs_dir(name), "F-M1P1": SETS[name]["base"]}
    if name == "v4":
        conds.update({"F-M1P0": SETS[name]["base"], "S-M1P0": SETS[name]["base"]})
    out = []
    for cond, folder in conds.items():
        for p in sorted(folder.glob(f"{cond}_*.json")):
            r = json.loads(p.read_text())
            t = r["turns"][-1]
            k = key[(r["scenario_id"], t["turn"])]
            out.append({"cond": cond, "src": r["scenario_id"][:-1], "ver": r["scenario_id"][-1], "seed": r["seed"],
                        "decision": t["decision"], "expected": k["expected_decision"], "truth": k["truth_predicate"],
                        "tool": (t["nlu"] or {}).get("tool")})
    return out


MEASURES = {"accuracy": ("vnd", lambda x: x["decision"] == x["expected"]),
            "dispute_d": ("d", lambda x: x["decision"] == "dispute"),
            "wrong_accept_nd": ("nd", lambda x: GROUP[x["decision"]] == "accept"),
            "wrong_reject_v": ("v", lambda x: GROUP[x["decision"]] == "reject"),
            "hold_v": ("v", lambda x: GROUP[x["decision"]] == "hold")}


def per_source(rows, cond, measure):
    versions, fn = MEASURES[measure]
    by = defaultdict(list)
    for x in rows:
        if x["cond"] == cond and x["ver"] in versions:
            by[x["src"]].append(fn(x))
    return {s: statistics.fmean(v) for s, v in by.items()}


def compare(rows, a, b, measure):
    pa, pb = per_source(rows, a, measure), per_source(rows, b, measure)
    common = sorted(s for s in pa if s in pb)
    diffs = [pa[s] - pb[s] for s in common]
    rng = random.Random(11)
    boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(5000))
    return {"n": len(common), a: statistics.fmean(pa[s] for s in common), b: statistics.fmean(pb[s] for s in common),
            "diff": statistics.fmean(diffs), "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}


def describe(rows, cond):
    mine = [x for x in rows if x["cond"] == cond]
    return {m: statistics.fmean(per_source(rows, cond, m).values()) for m in MEASURES} | {"runs": len(mine)}


def grade():
    seal_ = json.loads((OUT / "prereg_seal.json").read_text())
    files = list((OUT / "runs").rglob("*.json"))
    res = {"prereg_sha_match": seal_["prereg"] == sha(PREREG),
           "seal_before_live": datetime.fromisoformat(seal_["sealed_at"]).timestamp() < min(p.stat().st_mtime for p in files)}
    primary, secondary = {}, {}
    for name in ("v4", "heldout"):
        rows = claim_rows(name)
        conds = sorted({x["cond"] for x in rows})
        tools = [x for x in rows if x["cond"] == COND]
        called = [x for x in tools if x["tool"] and x["tool"]["call"]]
        res[name] = {"table": {c: describe(rows, c) for c in conds},
                     "tool_call_rate": len(called) / len(tools),
                     "tool_type_correct": sum(x["tool"]["claim_type"] == x["truth"] for x in called) / max(len(called), 1),
                     "tool_format_failures": sum(not (x["tool"] or {}).get("schema_ok", False) for x in tools),
                     "decisions_by_version": {v: dict(Counter(x["decision"] for x in tools if x["ver"] == v)) for v in "vnd"}}
        primary[name] = compare(rows, "F-M1P1", COND, "accuracy")
        if name == "v4":
            secondary["a_T_vs_F-M1P0_accuracy_v4"] = compare(rows, COND, "F-M1P0", "accuracy")
        secondary[f"b_dispute_d_P1_vs_T_{name}"] = compare(rows, "F-M1P1", COND, "dispute_d")
        secondary[f"c_wrong_accept_nd_P1_vs_T_{name}"] = compare(rows, "F-M1P1", COND, "wrong_accept_nd")
    res |= {"primary": primary, "primary_holm": holm({k: v["p"] for k, v in primary.items()}),
            "secondary": secondary, "secondary_holm": holm({k: v["p"] for k, v in secondary.items()})}
    res["decision_table_better"] = {k: res["primary_holm"][k] < 0.05 and v["diff"] > 0 for k, v in primary.items()}
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    report(res)
    print(json.dumps({k: res[k] for k in ("seal_before_live", "prereg_sha_match", "decision_table_better")}))


def report(res):
    pct = lambda x: f"{x:.1%}"
    pp = lambda x: f"{x * 100:+.1f}%p"
    pv = lambda x: f"{x:.4f}" if x >= 1e-4 else f"{x:.2e}"
    lines = ["# ABCD v6 결과: 도구 호출(tool-calling) 기준선 T-M1P0", "",
             f"사전등록 `docs/ABCD_v6_toolcall_사전등록.md`. 봉인 후 실행: {res['seal_before_live']}, 해시 일치: {res['prereg_sha_match']}.", ""]
    for name, title in (("v4", "v4 데이터 (84원천)"), ("heldout", "v5 검증 세트 (59원천)")):
        r, p = res[name], res["primary"][name]
        lines += [f"## {title}", "", "| 조건 | 실행 | 정확도 | 반박 정답 (d) | 잘못 수용 (n·d) | 잘못 거부 (v) | 보류 (v) |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {c} | {t['runs']} | {pct(t['accuracy'])} | {pct(t['dispute_d'])} | {pct(t['wrong_accept_nd'])} | "
                  f"{pct(t['wrong_reject_v'])} | {pct(t['hold_v'])} |" for c, t in r["table"].items()]
        lines += ["", f"- **주 지표** 정확도 F-M1P1 - T-M1P0: {pp(p['diff'])}, 95% CI [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}], "
                      f"Holm p = {pv(res['primary_holm'][name])} → 결정표가 더 나음: **{res['decision_table_better'][name]}**",
                  f"- 도구 호출률 {pct(r['tool_call_rate'])}, 고른 종류가 정답 술어인 비율 {pct(r['tool_type_correct'])}, 형식 실패 {r['tool_format_failures']}회",
                  f"- T-M1P0 결정 분포: {json.dumps(r['decisions_by_version'], ensure_ascii=False)}", ""]
    lines += ["## 부 지표 (Holm)", ""]
    lines += [f"- {k}: {pp(v['diff'])}, 95% CI [{pp(v['ci95'][0])}, {pp(v['ci95'][1])}], Holm p = {pv(res['secondary_holm'][k])}"
              for k, v in res["secondary"].items()]
    lines += ["", "## 해석에 주의할 점", "",
              "- 도구 호출은 llama-server의 tools API가 아니라 JSON 구조화 출력으로 흉내 냈다. 실제 function calling과 다를 수 있다.",
              "- τ-bench 자체를 재현한 것이 아니라, τ-bench가 평가하는 tool-calling 에이전트 방식을 이 과제에 구현한 것이다.",
              "- 수용/보류/거부 열은 v4·v5와 같은 사후 3분류 기준(`docs/ABCD_3way_사후분석.md`)으로 계산했다.",
              "- 검증 세트에는 F-M1P0이 없다."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"seal": seal, "pilot": pilot, "live": live, "grade": grade}[sys.argv[1]]()
