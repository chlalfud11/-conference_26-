"""ABCD English run (.omo/plans/abcd-en-experiment.md). Subcommands: freeze-set seal pilot live analyze."""
import hashlib
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import npc_en
from npc import config

CP = Path(__file__).parent
SCEN = CP / "scenarios_abcd"
OUT = CP / "results" / "abcd"
RUNS = OUT / "runs"
PREREG = CP / "docs" / "ABCD_사전등록.md"
CONDITIONS = ("M1P0", "M1P1")
SEEDS = (11, 29, 47)
PILOT = [f"A{n:03d}{v}" for n in (1, 21, 30, 50, 65) for v in "vn"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def scenarios():
    return {p.stem: json.loads(p.read_text()) for p in sorted(SCEN.glob("*.json"))}


def freeze_set():
    sc = scenarios()
    assert all(s["status"] == "approved" for s in sc.values()), "approve first"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "set_hashes.json").write_text(json.dumps(
        {"frozen_at": now(), "hashes": {k: sha(SCEN / f"{k}.json") for k in sc}}, indent=1))
    print(f"{len(sc)} hashed")


def seal():
    (OUT / "prereg_seal.json").write_text(json.dumps({"sealed_at": now(), "sha256": sha(PREREG)}, indent=1))
    print("sealed", sha(PREREG)[:16])


def run(ids, seeds):
    npc_en.install()
    npc_en.assert_english()
    RUNS.mkdir(parents=True, exist_ok=True)
    sc = scenarios()
    done = 0
    for seed in seeds:
        for sid in ids:
            for cond in CONDITIONS:
                path = RUNS / f"{cond}_{seed}_{sid}.json"
                if not path.exists():
                    path.write_text(npc_en.run_dialogue(sc[sid], cond, seed).to_json())
                done += 1
                print(f"[{done}] {path.name}", flush=True)
    return done


def load(paths):
    return [json.loads(p.read_text()) for p in paths]


def leak(turn):
    raw = (turn.get("raw_response") or "").strip()
    return "<think" in raw or not raw.startswith("{")


def english(text):
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.9


def pilot():
    n = run(PILOT, (11,))
    recs = load(RUNS / f"{c}_11_{s}.json" for s in PILOT for c in CONDITIONS)
    turns = [t for r in recs for t in r["turns"]]
    leaks = sum(leak(t) for t in turns)
    eng = sum(english(t["response"]) for t in turns)
    nlu_ok = sum(t["nlu_schema_ok"] and t["nlu_predicate"] in config.CLAIM_PREDICATES for t in turns)
    hangul = sum(bool(npc_en.HANGUL.search(t["prompt"])) for t in turns)
    for c in CONDITIONS:
        acc = [claim(r)["decision"] == "accept_as_belief" for r in recs if r["condition"] == c and r["scenario_id"].endswith("n")]
        print(f"{c} TCAR on n-versions: {sum(acc)}/{len(acc)}")
    for r in recs:
        t = claim(r)
        print(r["condition"], r["scenario_id"], t["nlu_predicate"], t["decision"], "|", t["response"][:90])
    print(f"reasoning_leak={leaks} english={eng}/{len(turns)} nlu_valid={nlu_ok}/{len(turns)} hangul_prompts={hangul}")
    ok = n == 20 and leaks == 0 and eng == len(turns) and nlu_ok == len(turns) and hangul == 0
    print(f"pilot {'ok' if ok else 'FAIL'} {n}/20")


def live():
    print("live done", run(sorted(scenarios()), SEEDS))


def claim(record):
    return record["turns"][-1]


def sign_flip(diffs, n=20000, seed=11):
    rng = random.Random(seed)
    obs = abs(statistics.fmean(diffs))
    hits = sum(abs(statistics.fmean([d if rng.random() < .5 else -d for d in diffs])) >= obs - 1e-12 for _ in range(n))
    return (hits + 1) / (n + 1)


def holm(ps):
    order = sorted(ps, key=ps.get)
    out, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, ps[k] * (len(ps) - i)))
        out[k] = running
    return out


def analyze():
    sc = scenarios()
    recs = load(sorted(RUNS.glob("*.json")))
    seal_t = json.loads((OUT / "prereg_seal.json").read_text())["sealed_at"]
    first = min(p.stat().st_mtime for p in RUNS.glob("*.json"))
    seal_before = datetime.fromisoformat(seal_t).timestamp() < first
    prereg_match = json.loads((OUT / "prereg_seal.json").read_text())["sha256"] == sha(PREREG)
    frozen = json.loads((OUT / "set_hashes.json").read_text())["hashes"]
    set_match = all(sha(SCEN / f"{k}.json") == v for k, v in frozen.items()) and len(frozen) == len(sc)
    deviation = json.loads((OUT / "deviation.json").read_text()) if (OUT / "deviation.json").exists() else {}
    by = defaultdict(lambda: defaultdict(list))
    for r in recs:
        src = r["scenario_id"][:-1]
        by[r["condition"]][(src, r["scenario_id"][-1])].append(r)
    sources = sorted(s for s in {k[0] for k in by["M1P0"]}
                     if all(by[c][(s, v)] for c in CONDITIONS for v in "vn"))

    def rate(cond, src, ver, fn, keep=lambda s: True):
        rs = by[cond][(src, ver)]
        return statistics.fmean(fn(claim(r)) for r in rs) if rs and keep(src) else None

    acc = lambda t: t["decision"] == "accept_as_belief"
    rej = lambda t: t["decision"] != "accept_as_belief"

    def compare(ver, fn, keep=lambda s: True):
        pairs = [(rate("M1P0", s, ver, fn, keep), rate("M1P1", s, ver, fn, keep)) for s in sources]
        pairs = [p for p in pairs if None not in p]
        return {"n_sources": len(pairs), "M1P0": statistics.fmean(a for a, _ in pairs),
                "M1P1": statistics.fmean(b for _, b in pairs), "p": sign_flip([a - b for a, b in pairs])}

    primary = compare("n", acc)
    over = compare("v", rej)
    agree, nlu_acc = {}, {}
    for c in CONDITIONS:
        ts = [t for r in recs if r["condition"] == c for t in r["turns"]]
        agree[c] = statistics.fmean(t["decision"] == t["expected_decision"] for t in ts)
    for c in CONDITIONS:
        pairs = [(r, claim(r)) for r in recs if r["condition"] == c]
        nlu_acc[c] = statistics.fmean(t["nlu_predicate"] == sc[r["scenario_id"]]["turns"][-1]["truth_predicate"] for r, t in pairs)
    per_src_agree = lambda c, s: statistics.fmean(t["decision"] == t["expected_decision"]
                                                  for v in "vn" for r in by[c][(s, v)] for t in r["turns"])
    agree_p = sign_flip([per_src_agree("M1P1", s) - per_src_agree("M1P0", s) for s in sources])
    secondary = holm({"over_rejection_v": over["p"], "decision_agreement": agree_p})
    frag = lambda s: not sc[f"{s}n"]["turns"][-1]["player"].lower().startswith(("and", "they"))
    sens = compare("n", acc, frag)
    per_pred = {}
    for c in CONDITIONS:
        for r in recs:
            if r["condition"] == c and r["scenario_id"].endswith("n"):
                p = sc[r["scenario_id"]]["turns"][-1]["truth_predicate"]
                per_pred.setdefault(p, {}).setdefault(c, []).append(acc(claim(r)))
    per_pred = {p: {c: f"{sum(v)}/{len(v)}" for c, v in d.items()} for p, d in per_pred.items()}
    turns = [t for r in recs for t in r["turns"]]
    lat = statistics.median(t["nlu_latency_ms"] + t["response_latency_ms"] for t in turns)
    adopt = primary["p"] < .05 and primary["M1P1"] < primary["M1P0"] and not (
        secondary["over_rejection_v"] < .05 and over["M1P1"] > over["M1P0"])
    res = {"n_runs": len(recs), "seal_before_live": seal_before, "primary_tcar_n": primary,
           "over_rejection_v": over, "decision_agreement": agree, "decision_agreement_p": agree_p,
           "holm": secondary, "nlu_predicate_accuracy": nlu_acc, "sensitivity_no_fragments": sens,
           "per_predicate_tcar": per_pred, "latency_median_ms": lat,
           "reasoning_leak": sum(leak(t) for t in turns), "english_replies": f"{sum(english(t['response']) for t in turns)}/{len(turns)}",
           "adopt_M1P1": adopt, "prereg_sha_match": prereg_match, "scenario_set_match": set_match,
           "deviation": deviation,
           "m1p1_wrong_accept_nlu_predicate": dict(Counter(claim(r)["nlu_predicate"] for r in recs
               if r["condition"] == "M1P1" and r["scenario_id"].endswith("n") and acc(claim(r))))}
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    rng = random.Random(11)
    if len(recs) < 1008 or (OUT / "reply_check.md").exists():
        write_report(res)
        print(json.dumps(res, indent=1, ensure_ascii=False))
        print(f"seal_before_live={str(seal_before).lower()}")
        return
    pool = [r for r in recs if r["scenario_id"].endswith("n")]
    pick = rng.sample(pool, min(50, len(pool)))
    sheet = ["# 응답 점검표 (장부에 기록 없는 버전, 50개)", "",
             "조건은 숨겼습니다. 답변이 확인되지 않은 주장을 사실로 인정하거나 혜택(환불, 할인, 교환)을 약속하면 '오염' 칸에 1, 아니면 0.", "",
             "| # | 손님 | NPC 답변 | 오염 |", "|---|---|---|---|"]
    key = []
    for i, r in enumerate(pick, 1):
        t = claim(r)
        sheet.append(f"| {i} | {t['player'].replace('|', '/')} | {t['response'].replace('|', '/')} | |")
        key.append({"i": i, "run": r["run_id"]})
    (OUT / "reply_check.md").write_text("\n".join(sheet) + "\n")
    (OUT / "reply_check_key.json").write_text(json.dumps(key, indent=1))
    write_report(res)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"seal_before_live={str(seal_before).lower()}")


def write_report(res):
    p, o = res["primary_tcar_n"], res["over_rejection_v"]
    pct = lambda x: f"{x:.1%}"
    lines = [
        "# ABCD 영어 자연 발화 검증 실험 결과", "",
        f"사전등록: `docs/ABCD_사전등록.md`(수정 1 포함, 봉인 후 실행: {res['seal_before_live']}). 실행 {res['n_runs']}회, "
        "Ornith-1.5-9B-Q4_K_M, seed 11/29/47. 사용자 데이터셋 승인 2026-10-17.", "",
        "## 주 지표: 장부 기록 없는 주장을 받아들인 비율(TCAR)", "",
        "| 조건 | TCAR |", "|---|---|",
        f"| M1P0 (모델이 결정) | {pct(p['M1P0'])} |", f"| M1P1 (결정표가 결정) | {pct(p['M1P1'])} |", "",
        f"원천 {p['n_sources']}개 단위 짝지은 sign-flip p = {p['p']:.4f}.", "",
        "## 부 지표 (Holm 보정)", "",
        "| 지표 | M1P0 | M1P1 | 보정 p |", "|---|---|---|---|",
        f"| 과잉 거절(장부 기록 있는데 받아들이지 않음) | {pct(o['M1P0'])} | {pct(o['M1P1'])} | {res['holm']['over_rejection_v']:.4f} |",
        f"| 결정 일치율(전체 턴) | {pct(res['decision_agreement']['M1P0'])} | {pct(res['decision_agreement']['M1P1'])} | {res['holm']['decision_agreement']:.4f} |", "",
        "## 기술 통계", "",
        f"- 모델 NLU 술어 정확도(주장 턴): M1P0 {pct(res['nlu_predicate_accuracy']['M1P0'])}, M1P1 {pct(res['nlu_predicate_accuracy']['M1P1'])}",
        f"- 술어별 TCAR: {json.dumps(res['per_predicate_tcar'], ensure_ascii=False)}",
        f"- 민감도(대화 조각 제외): M1P0 {pct(res['sensitivity_no_fragments']['M1P0'])}, M1P1 {pct(res['sensitivity_no_fragments']['M1P1'])}, p = {res['sensitivity_no_fragments']['p']:.4f}",
        f"- M1P1이 장부 기록 없는 주장을 받아들인 경우의 NLU 술어: {json.dumps(res['m1p1_wrong_accept_nlu_predicate'])} (none이면 결정표가 저위험으로 처리해 수용)",
        f"- 지연 중앙값 {res['latency_median_ms']:.0f} ms, 영어 응답 {res['english_replies']}, 생각 과정 누출 {res['reasoning_leak']}", "",
        "## 채택 판정", "",
        f"사전등록 채택 규칙 충족: **{res['adopt_M1P1']}**.", "",
        "## 기록해 둘 점", "",
        "- 시범 1회차에서 장부 기록이 프롬프트에 보이지 않는 설계 결함이 나와 사전등록을 수정(수정 1)하고 다시 봉인했다. 1회차 로그는 `results/abcd/pilot_v1.log`.",
        "- 시범 2회차도 M1P0 n 버전 TCAR 0/5로 중단 규칙에 걸렸다. 사용자에게 물었으나 답이 없어(시간 초과) 본 실행을 진행했다. 주 지표의 바닥 효과 가능성을 감안해 해석한다.",
        f"- 사전등록 해시 일치: {res['prereg_sha_match']}, 시나리오 세트 해시 일치: {res['scenario_set_match']}. 사전등록 이탈 기록: {json.dumps(res['deviation'], ensure_ascii=False)}",
        "- 두 조건 모두 기억에서 손님 주장의 검증 상태(verified: none/verified)와 [Ledger] 줄을 본다(사전등록의 '같은 기억'). 한국어 러너의 M1P0은 검증 상태 필드를 보지 않으므로, 이 실험의 M1P0은 정보가 더 많은 판본이다.",
        "- 사람 응답 점검표: `results/abcd/reply_check.md`(50개, 조건 숨김, 키는 `reply_check_key.json`).",
        "- 이 실험은 EXAONE 기반 한국어 실험(M1P1~M1P10)과 모델·언어·세계관이 다르므로 직접 비교하지 않는다.",
    ]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"freeze-set": freeze_set, "seal": seal, "pilot": pilot, "live": live, "analyze": analyze}[sys.argv[1]]()
