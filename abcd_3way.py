"""ABCD 3-way post-hoc analysis (docs/ABCD_3way_사후분석.md): accept / hold / reject.

Usage: python3 abcd_3way.py  -> results/abcd_3way/analysis.json, report.md
Re-scores existing runs only; FC and RV decisions are derived exactly as in abcd5_live.analyse.
"""
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import abcd5_live as V5
from abcd_live import sign_flip

ROOT = Path(__file__).parent
OUT = ROOT / "results" / "abcd_3way"
GROUP = {"accept_as_belief": "accept", "request_evidence": "hold", "defer": "hold", "dispute": "reject", "reject": "reject"}


def rows_for(name):
    key, base, rv_live = V5.load_set(name)
    rows = []
    for (sid, seed), b in base.items():
        trig = V5.triggered(b)
        r = rv_live.get((sid, seed))
        decisions = {"F-M1P1": b["turns"][-1]["decision"],
                     "FC": "request_evidence" if trig else b["turns"][-1]["decision"],
                     "RV": (r or b)["turns"][-1]["decision"]}
        for cond, d in decisions.items():
            rows.append({"cond": cond, "src": sid[:-1], "ver": sid[-1], "decision": d})
    if name == "dev":
        for cond in ("F-M1P0", "S-M1P0"):
            for p in sorted((ROOT / "results" / "abcd4" / "runs").glob(f"{cond}_*.json")):
                r = json.loads(p.read_text())
                rows.append({"cond": cond, "src": r["scenario_id"][:-1], "ver": r["scenario_id"][-1],
                             "decision": r["turns"][-1]["decision"]})
    return rows


MEASURES = {
    "wrong_accept_nd": ("nd", lambda d: GROUP[d] == "accept"),
    "wrong_reject_v": ("v", lambda d: GROUP[d] == "reject"),
    "hold_v": ("v", lambda d: GROUP[d] == "hold"),
    "accept_v": ("v", lambda d: GROUP[d] == "accept"),
    "dispute_d": ("d", lambda d: d == "dispute"),
}


def per_source(rows, cond, measure):
    versions, fn = MEASURES[measure]
    by = defaultdict(list)
    for x in rows:
        if x["cond"] == cond and x["ver"] in versions:
            by[x["src"]].append(fn(x["decision"]))
    return {s: statistics.fmean(v) for s, v in by.items()}


def summarise(name):
    rows = rows_for(name)
    conds = [c for c in ("F-M1P0", "S-M1P0", "F-M1P1", "FC", "RV") if any(x["cond"] == c for x in rows)]
    table = {c: {m: statistics.fmean(per_source(rows, c, m).values()) for m in MEASURES} for c in conds}
    tests = {}
    for m in ("wrong_accept_nd", "wrong_reject_v", "hold_v"):
        a, b = per_source(rows, "RV", m), per_source(rows, "F-M1P1", m)
        diffs = [a[s] - b[s] for s in a if s in b]
        tests[m] = {"diff_RV_minus_P1": statistics.fmean(diffs), "p": sign_flip(diffs), "n": len(diffs)}
    return {"set": name, "sources": len({x["src"] for x in rows}), "table": table, "RV_vs_P1": tests}


def main():
    res = {"note": "post-hoc exploratory; preregistered results unchanged",
           "v4": summarise("dev"), "v5_heldout": summarise("heldout")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    pct = lambda x: f"{x:.1%}"
    lines = ["# ABCD 3분류 사후 분석 (수용 / 보류 / 거부)", "",
             "계획: `docs/ABCD_3way_사후분석.md` (계산 전 커밋). **사후 탐색 분석**이며 사전등록 결과는 바뀌지 않는다.", "",
             "- 잘못 수용: n·d에서 믿음 (속음) / 잘못 거부: v에서 반박·거절 / 보류(v): v에서 증거 요구·보류 (확인 비용)", ""]
    for key, title in (("v4", "v4 데이터 (84원천)"), ("v5_heldout", "v5 검증 세트 (59원천)")):
        r = res[key]
        lines += [f"## {title}", "", "| 조건 | 잘못 수용 (n·d) | 잘못 거부 (v) | 보류 (v) | 수용 (v) | 반박 정답 (d) |", "|---|---|---|---|---|---|"]
        lines += [f"| {c} | {pct(t['wrong_accept_nd'])} | {pct(t['wrong_reject_v'])} | {pct(t['hold_v'])} | {pct(t['accept_v'])} | {pct(t['dispute_d'])} |"
                  for c, t in r["table"].items()]
        lines += [""] + [f"- RV - F-M1P1, {m}: {v['diff_RV_minus_P1'] * 100:+.1f}%p, p = {v['p']:.4f} (참고용)" for m, v in r["RV_vs_P1"].items()] + [""]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
