"""ABCD v4 fail-closed follow-up (docs/ABCD_v4_failclosed_사전등록.md). Subcommands: seal pilot live grade.

Runs F-M1P1FC into results/abcd4fc/runs and compares it with the sealed v4 F-M1P1 runs (results/abcd4/runs).
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
OUT = ROOT / "results" / "abcd4fc"
RUNS = OUT / "runs"
BASE = ROOT / "results" / "abcd4" / "runs"
KEY = ROOT / "answer_key_abcd4" / "answer_key.csv"
PREREG = ROOT / "docs" / "ABCD_v4_failclosed_사전등록.md"
COND, BASE_COND = "F-M1P1FC", "F-M1P1"
SEEDS = (11, 29, 47)
PILOT_SOURCES = ("A001", "A019", "A021", "A074")


def seal():
    path = OUT / "prereg_seal.json"
    assert not path.exists(), "already sealed"
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sealed_at": datetime.now(timezone.utc).isoformat(), "prereg": sha(PREREG)}, indent=1) + "\n")
    print("sealed", sha(PREREG)[:16])


def run(seeds, ids):
    assert (OUT / "prereg_seal.json").exists(), "seal first"
    R.install()
    sc, (rows, today) = R.scenarios(), LG.load()
    RUNS.mkdir(parents=True, exist_ok=True)
    done = 0
    for seed in seeds:
        for sid in ids:
            path = RUNS / f"{COND}_{seed}_{sid}.json"
            if not path.exists():
                path.write_text(R.run_dialogue4(sc[sid], COND, seed, rows, today).to_json())
            done += 1
            print(f"[{done}] {path.name}", flush=True)
    return done


def pilot():
    ids = [f"{s}{v}" for s in PILOT_SOURCES for v in "vnd"]
    n = run((11,), ids)
    recs = [json.loads((RUNS / f"{COND}_11_{sid}.json").read_text()) for sid in ids]
    turns = [t for r in recs for t in r["turns"]]
    ok = (n == 12 and not any(leak(t) for t in turns) and all(english(t["response"]) for t in turns)
          and all("Customer-stated date:" in r["turns"][-1]["prompt"] for r in recs))
    for r in recs:
        t = r["turns"][-1]
        print(r["scenario_id"], t["nlu_predicate"], t["evidence"], t["decision"], "|", t["response"][:80])
    print(f"pilot {'ok' if ok else 'FAIL'} {n}/12")


def live():
    print("live done", run(SEEDS, sorted(R.scenarios())))


def grade():
    with KEY.open(newline="") as handle:
        key = {(r["scenario_id"], int(r["turn"])): r for r in csv.DictReader(handle)}
    runs = {COND: [json.loads(p.read_text()) for p in sorted(RUNS.glob(f"{COND}_*.json"))],
            BASE_COND: [json.loads(p.read_text()) for p in sorted(BASE.glob(f"{BASE_COND}_*.json"))]}
    claim = lambda r: r["turns"][-1]
    answer = lambda r: key[(r["scenario_id"], claim(r)["turn"])]
    measures = {"accuracy": lambda r: claim(r)["decision"] == answer(r)["expected_decision"],
                "acceptance": lambda r: claim(r)["decision"] == "accept_as_belief",
                "over_rejection": lambda r: claim(r)["decision"] != "accept_as_belief",
                "dispute": lambda r: claim(r)["decision"] == "dispute"}
    sources = sorted({r["scenario_id"][:-1] for r in runs[COND]})

    def per_source(cond, versions, fn):
        by = defaultdict(list)
        for r in runs[cond]:
            if r["scenario_id"][-1] in versions:
                by[r["scenario_id"][:-1]].append(fn(r))
        return {s: statistics.fmean(v) for s, v in by.items()}

    def compare(versions, measure):
        pa, pb = per_source(COND, versions, measures[measure]), per_source(BASE_COND, versions, measures[measure])
        common = [s for s in sources if s in pa and s in pb]
        diffs = [pa[s] - pb[s] for s in common]
        rng = random.Random(11)
        boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(5000))
        return {"n": len(common), COND: statistics.fmean(pa[s] for s in common), BASE_COND: statistics.fmean(pb[s] for s in common),
                "diff": statistics.fmean(diffs), "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}

    primary = compare("n", "acceptance")
    secondary = {"a_over_rejection_v": compare("v", "over_rejection"), "b_accuracy_all": compare("vnd", "accuracy"),
                 "c_dispute_d": compare("d", "dispute")}
    holm_p = holm({k: v["p"] for k, v in secondary.items()})
    base_by = {(r["scenario_id"], r["seed"]): r for r in runs[BASE_COND]}
    same_nlu = [t["nlu_predicate"] == u["nlu_predicate"] for r in runs[COND]
                for t, u in zip(r["turns"], base_by[(r["scenario_id"], r["seed"])]["turns"])]
    triggered = Counter(r["scenario_id"][-1] for r in runs[COND]
                        if claim(r)["nlu_predicate"] == "none" and R.TRANSACTION_CUE.search(claim(r)["player"]))
    greeting_triggers = sum(1 for r in runs[COND] for t in r["turns"][:-1]
                            if t["nlu_predicate"] == "none" and R.TRANSACTION_CUE.search(t["player"]))
    a = secondary["a_over_rejection_v"]
    adopt = (primary["p"] < 0.05 and primary["diff"] < 0 and a["ci95"][1] <= 0.10)
    seal_t = datetime.fromisoformat(json.loads((OUT / "prereg_seal.json").read_text())["sealed_at"]).timestamp()
    res = {"n_runs": len(runs[COND]), "complete": len(runs[COND]) == 756,
           "seal_before_live": seal_t < min(p.stat().st_mtime for p in RUNS.glob("*.json")),
           "prereg_sha_match": json.loads((OUT / "prereg_seal.json").read_text())["prereg"] == sha(PREREG),
           "primary_n_acceptance": primary, "secondary": secondary, "holm": holm_p, "adopt": adopt,
           "nlu_same_as_v4": statistics.fmean(same_nlu), "fail_closed_triggers_claim_turn": dict(triggered),
           "fail_closed_triggers_greeting_turns": greeting_triggers,
           "decisions": {c: {v: dict(Counter(claim(r)["decision"] for r in runs[c] if r["scenario_id"][-1] == v)) for v in "vnd"}
                         for c in (COND, BASE_COND)}}
    pred_path = OUT / "offline_prediction.json"
    if pred_path.exists():
        pred = json.loads(pred_path.read_text())
        res["offline_prediction_agreement"] = statistics.fmean(
            pred[f"{r['scenario_id']}_{r['seed']}"] == claim(r)["decision"] for r in runs[COND])
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    report(res)
    print(json.dumps({k: res[k] for k in ("n_runs", "complete", "seal_before_live", "prereg_sha_match", "adopt")}))


def report(res):
    pct = lambda x: f"{x:.1%}"
    pp = lambda x: f"{x * 100:.1f}%p"
    pv = lambda x: f"{x:.4f}" if x >= 1e-4 else f"{x:.2e}"
    p, s = res["primary_n_acceptance"], res["secondary"]
    name = {"a_over_rejection_v": "(a) 기록 있음(v) 과잉 거절률", "b_accuracy_all": "(b) 전체 정확도(v·n·d)",
            "c_dispute_d": "(c) 날짜 불일치(d) 반박률"}
    lines = ["# ABCD v4 fail-closed 후속 실험 결과", "",
             f"사전등록 `docs/ABCD_v4_failclosed_사전등록.md`. 실행 {res['n_runs']}회, 완결: {res['complete']}, "
             f"봉인 후 실행: {res['seal_before_live']}, 해시 일치: {res['prereg_sha_match']}. 비교 대상은 봉인된 v4의 F-M1P1 실행이다.", "",
             "## 주 지표: 기록 없는 주장(n)을 믿어 준 비율 (낮을수록 좋음)", "",
             f"- F-M1P1FC {pct(p[COND])} vs F-M1P1 {pct(p[BASE_COND])}: 차이 {pp(p['diff'])}, 95% CI [{pp(p['ci95'][0])}, {pp(p['ci95'][1])}], "
             f"p = {pv(p['p'])} (원천 {p['n']}개)",
             f"- 사전등록 채택 규칙 충족: **{res['adopt']}**", "", "## 부 지표 (FC - 기존, Holm 보정)", ""]
    lines += [f"- {name[k]}: FC {pct(v[COND])} vs 기존 {pct(v[BASE_COND])}, 차이 {pp(v['diff'])}, "
              f"95% CI [{pp(v['ci95'][0])}, {pp(v['ci95'][1])}], Holm p = {pv(res['holm'][k])}" for k, v in s.items()]
    lines += ["", "## 기술 통계", "",
              f"- NLU 술어가 v4 F-M1P1 실행과 같은 비율: {pct(res['nlu_same_as_v4'])} (같은 seed, 같은 프롬프트)",
              f"- 주장 턴에서 fail-closed가 발동한 수: {json.dumps(res['fail_closed_triggers_claim_turn'])}",
              f"- 인사 턴에서 발동한 수: {res['fail_closed_triggers_greeting_turns']}",
              (f"- (사후) v4 F-M1P1 기록에 규칙을 적용한 오프라인 예측과 실제 결정의 일치율: {pct(res['offline_prediction_agreement'])}"
               if "offline_prediction_agreement" in res else "- (사후) 오프라인 예측 없음"),
              f"- 결정 분포: {json.dumps(res['decisions'], ensure_ascii=False)}", "",
              "## 해석에 주의할 점", "",
              "- fail-closed는 '주장 없음'으로 읽힌 주장을 증거 요구로 바꿀 뿐, 반박으로 바꾸지는 못한다. 날짜 불일치(d)에서 반박률은 오르지 않을 수 있다.",
              "- 거래 단서 목록은 사전에 고정한 정규식이다. 단서가 없는 주장은 여전히 놓친다.",
              "- 정답은 설계로 정해진다. A064의 날짜 결함은 v4 보고서에 공개되어 있다."]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"seal": seal, "pilot": pilot, "live": live, "grade": grade}[sys.argv[1]]()
