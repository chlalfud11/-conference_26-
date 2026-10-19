"""Grade ABCD v4 runs against the sealed answer key (.omo/plans/abcd-v4-answer-key.md).

Usage: python3 abcd4_grade.py   -> results/abcd4/analysis.json, results/abcd4/report.md
"""
import csv
import json
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import abcd4_build as B
import abcd4_ledger as LG
from abcd_live import holm, sign_flip
from abcd_live2 import ACK

OUT = B.OUT
RUNS = OUT / "runs"
FOREIGN = re.compile(r"\| ([A-Z][a-z]+ [A-Z][a-z]+) \(([^)]+)\) \|")
DATE_WORD = re.compile(r"\b(\d{4}-\d{2}-\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b")
ACCEPT, CONDS = "accept_as_belief", ("F-M1P0", "S-M1P0", "F-M1P1")


def load():
    runs = defaultdict(list)
    for p in sorted(RUNS.glob("*.json")):
        cond, seed, sid = p.stem.split("_")
        runs[cond].append(json.loads(p.read_text()))
    with B.KEY.open(newline="") as handle:
        key = {(r["scenario_id"], int(r["turn"])): r for r in csv.DictReader(handle)}
    return runs, key


def main():
    runs, key = load()
    rows, _ = LG.load()
    scen = B.SCEN
    sources = sorted({p.stem[:-1] for p in scen.glob("*.json")})
    claim = lambda r: r["turns"][-1]
    answer = lambda r: key[(r["scenario_id"], claim(r)["turn"])]
    correct = lambda r: claim(r)["decision"] == answer(r)["expected_decision"]
    measures = {"accuracy": correct, "over_rejection": lambda r: claim(r)["decision"] != ACCEPT,
                "acceptance": lambda r: claim(r)["decision"] == ACCEPT,
                "dispute": lambda r: claim(r)["decision"] == "dispute"}

    def per_source(cond, versions, fn):
        by = defaultdict(list)
        for r in runs[cond]:
            if r["scenario_id"][-1] in versions:
                by[r["scenario_id"][:-1]].append(fn(r))
        return {s: statistics.fmean(v) for s, v in by.items()}

    def compare(a, b, versions, measure):
        pa, pb = per_source(a, versions, measures[measure]), per_source(b, versions, measures[measure])
        common = [s for s in sources if s in pa and s in pb]
        diffs = [pa[s] - pb[s] for s in common]
        rng = random.Random(11)
        boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(5000))
        return {"n": len(common), a: statistics.fmean(pa[s] for s in common), b: statistics.fmean(pb[s] for s in common),
                "diff": statistics.fmean(diffs), "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}

    primary = compare("F-M1P1", "F-M1P0", "vnd", "accuracy")
    secondary = {"a_over_rejection_v": compare("F-M1P1", "F-M1P0", "v", "over_rejection"),
                 "b_acceptance_n": compare("F-M1P1", "F-M1P0", "n", "acceptance"),
                 "c_dispute_d": compare("F-M1P1", "F-M1P0", "d", "dispute"),
                 "d_full_vs_search": compare("F-M1P0", "S-M1P0", "vnd", "accuracy")}
    holm_p = holm({k: v["p"] for k, v in secondary.items()})
    a = secondary["a_over_rejection_v"]
    adopt = (primary["p"] < 0.05 and primary["diff"] > 0
             and not (holm_p["a_over_rejection_v"] < 0.05 and a["diff"] > 0))

    def describe(cond):
        recs = runs[cond]
        wrong = [r for r in recs if not correct(r)]
        nlu_ok = lambda r: claim(r)["nlu_predicate"] == answer(r)["truth_predicate"]
        out = {"runs": len(recs),
               "decisions": {v: dict(Counter(claim(r)["decision"] for r in recs if r["scenario_id"][-1] == v)) for v in "vnd"},
               "accuracy": {v: statistics.fmean(correct(r) for r in recs if r["scenario_id"][-1] == v) for v in "vnd"},
               "nlu_accuracy": statistics.fmean(nlu_ok(r) for r in recs),
               "wrong": len(wrong), "wrong_with_nlu_error": sum(not nlu_ok(r) for r in wrong),
               "ack_in_response": sum(bool(ACK.search(claim(r)["response"])) for r in recs),
               "date_in_response": sum(bool(DATE_WORD.search(claim(r)["response"])) for r in recs)}
        if cond.startswith("S"):
            hit, foreign = [], []
            for r in recs:
                sc = json.loads((scen / f"{r['scenario_id']}.json").read_text())
                acct = LG.split_who(sc["customer"])[1]
                support = [LG.render(x) for x in rows if x["account"] == acct and LG.matches(answer(r)["truth_predicate"], x)]
                prompt = claim(r)["prompt"]
                if support:
                    hit.append(any(t in prompt for t in support))
                foreign.append(sum(1 for _, ac in FOREIGN.findall(prompt) if ac != acct))
            out["search_hit_rate_vd"] = statistics.fmean(hit)
            out["mean_foreign_rows"] = statistics.fmean(foreign)
        return out

    seal = json.loads((OUT / "prereg_seal.json").read_text())
    files = list(RUNS.glob("*.json"))
    res = {"n_runs": len(files), "complete": len(files) == 2268,
           "seal_before_live": datetime.fromisoformat(seal["sealed_at"]).timestamp() < min(p.stat().st_mtime for p in files),
           "hashes_match": {k: seal[k] == v for k, v in B.hashes().items()},
           "primary_accuracy_M1P1_vs_M1P0": primary, "secondary": secondary, "holm": holm_p, "adopt": adopt,
           "vn_only_accuracy_M1P1_vs_M1P0": compare("F-M1P1", "F-M1P0", "vn", "accuracy"),
           "describe": {c: describe(c) for c in CONDS}}
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    report(res)
    print(json.dumps({k: res[k] for k in ("n_runs", "complete", "seal_before_live", "hashes_match", "adopt")}))


def report(res):
    pct = lambda x: f"{x:.1%}"
    pp = lambda x: f"{x * 100:.1f}%p"
    pv = lambda x: f"{x:.4f}" if x >= 1e-4 else f"{x:.2e}"
    p, d = res["primary_accuracy_M1P1_vs_M1P0"], res["describe"]
    name = {"a_over_rejection_v": "(a) 기록 있음(v) 과잉 거절률, M1P1 - M1P0",
            "b_acceptance_n": "(b) 기록 없음(n) 수용률, M1P1 - M1P0",
            "c_dispute_d": "(c) 날짜 불일치(d) 반박률, M1P1 - M1P0",
            "d_full_vs_search": "(d) 정확도, 전체 장부(F) - 검색(S), 둘 다 M1P0"}
    lines = ["# ABCD v4 결과 (정답 분리, 가게 장부 하나, 날짜 필드)", "",
             f"사전등록 `docs/ABCD_v4_사전등록.md`. 실행 {res['n_runs']}회, 완결: {res['complete']}, "
             f"봉인 후 실행: {res['seal_before_live']}, 해시 일치: {res['hashes_match']}.", "",
             "## 주장 턴 결정 정확도 (높을수록 좋음)", "", "| 조건 | 기록 있음 v | 기록 없음 n | 날짜 불일치 d |", "|---|---|---|---|"]
    lines += [f"| {c} | {pct(d[c]['accuracy']['v'])} | {pct(d[c]['accuracy']['n'])} | {pct(d[c]['accuracy']['d'])} |" for c in CONDS]
    lines += ["", f"- **주 지표** 정확도 F-M1P1 {pct(p['F-M1P1'])} vs F-M1P0 {pct(p['F-M1P0'])}: 차이 {pp(p['diff'])}, "
              f"95% CI [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}], p = {pv(p['p'])} (원천 {p['n']}개)",
              f"- 사전등록 채택 규칙 충족: **{res['adopt']}**", "", "## 부 지표 (Holm 보정)", ""]
    lines += [f"- {name[k]}: 차이 {pp(v['diff'])}, 95% CI [{pp(v['ci95'][0])}, {pp(v['ci95'][1])}], Holm p = {pv(res['holm'][k])}"
              for k, v in res["secondary"].items()]
    vn = res["vn_only_accuracy_M1P1_vs_M1P0"]
    lines += ["", "## 기술 통계", "",
              f"- 반박 판(d)을 뺀 v·n 정확도: F-M1P1 {pct(vn['F-M1P1'])} vs F-M1P0 {pct(vn['F-M1P0'])}, 차이 {pp(vn['diff'])}, p = {pv(vn['p'])}"]
    for c in CONDS:
        x = d[c]
        extra = (f", 검색 적중률(v·d) {pct(x['search_hit_rate_vd'])}, 다른 손님 줄 평균 {x['mean_foreign_rows']:.2f}개"
                 if "search_hit_rate_vd" in x else "")
        lines.append(f"- {c}: NLU 술어 정확도 {pct(x['nlu_accuracy'])}, 오답 {x['wrong']}건 중 NLU 오독 {x['wrong_with_nlu_error']}건, "
                     f"장부 인정 발화 {x['ack_in_response']}, 날짜 언급 발화 {x['date_in_response']}{extra}")
        lines.append(f"  - 결정 분포: {json.dumps(x['decisions'], ensure_ascii=False)}")
    lines += ["", "## 해석에 주의할 점", "",
              "- 정답은 설계로 정해진다(v 믿기, n 증거 요구, d 반박). 사람 라벨이 아니다.",
              "- d의 날짜 불일치는 14~28일이다. 날짜가 달라도 같은 사건일 수 있으므로, d에서 믿기를 고른 응답이 꼭 틀렸다고 보기 어렵다. 그래서 v·n만의 정확도를 함께 보고한다.",
              "- M1P1은 NLU가 읽은 술어로 엔진이 장부를 조회해 결정한다. NLU가 맞으면 결정표는 정답과 같은 규칙을 따르므로, M1P1의 오답은 대부분 NLU 오독에서 나온다.",
              "- 대사 오염은 판정하지 않았다. 장부 인정·날짜 언급은 정규식 기술 통계다."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
