from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
import nlu_v3 as v3  # noqa: E402

OUT = CP / "results/bottleneck"
KO = {"reserved_item": "예약", "paid_deposit": "선금", "promised_reward": "보상약속", "promised_discount": "할인약속",
      "completed_errand": "심부름", "owns_item": "소유", "heard_rumor": "소문", "none": "없음"}
DEC = {"accept_as_belief": "수용", "request_evidence": "증거요구", "dispute": "반박", "defer": "보류", "reject": "거절"}
V = ("B", "V1", "V2", "V3")


def rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def cell(preds: list[str], truth: str) -> tuple[str, int]:
    ok = sum(cfg.risk_of(p) == cfg.risk_of(truth) for p in preds)
    mark = "" if ok == len(preds) else f" **✗{len(preds) - ok}**"
    return "·".join(KO[p] for p in preds) + mark, ok


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def conditions_section() -> list[str]:
    ex = ["지난주에 밧줄 두 묶음 맡겨 뒀잖아요.", "그나저나 북쪽 고개에 산적이 나타났대요."]
    out = ["## 1. 네 조건 한눈에 보기", "",
           "| 조건 | NLU가 보는 것 | 지시문 | 예시 | 실행된 곳 |", "|---|---|---|---|---|",
           "| B (원본) | 지금 손님 말 1개 | 술어 정의 목록 + \"과거 거래를 언급하면 해당 술어\" | 없음 | M1P1 본실험(라이브), M1P5 오프라인 dev/test, V3 새 세트 |",
           "| V1 | 지금 손님 말 1개 | 출처 먼저(손님 자신의 가게 거래 vs 남에게 들은 소식) + 술어 정의 | 11개(시나리오에 없는 물건) | M1P5 오프라인 dev/test, V3 새 세트 |",
           "| V2 | 직전 손님 말 최대 2개 + 지금 말 | V1 + \"앞선 말은 무엇을 가리키는지 알기 위해서만 쓴다\" | V1과 같음 | M1P5 오프라인 dev/test, **M1P5 라이브 81런**, V3 새 세트 |",
           "| V3 | 직전 손님 말 최대 2개 + 지금 말 | V1 + \"앞 주장을 가리키거나 되풀이할 때만 문맥을 보고, 새 화제면 지금 말만 본다\" | V1 11개 + 문맥 예시 3개 | V3 새 세트, 기존 27편(기술 평가) |",
           "", "모델(EXAONE-3.5-2.4B-Instruct Q4_K_M), temperature 0.2, top_p 0.9, seed 11/29/47, 출력 JSON 스키마(`runner.NLU_SCHEMA`), 정책은 네 조건 모두 같다. 정책은 NLU 술어의 위험도만 쓴다.", ""]
    for name in V:
        msgs = v3.messages(name, ex[1], [ex[0]])
        out += [f"### {name} 시스템 지시문 원문", "", "```text", msgs[0]["content"], "```", "",
                f"{name} 사용자 메시지 형식 (앞선 손님 말 \"{ex[0]}\" 다음에 \"{ex[1]}\"가 들어온 경우):", "",
                "```text", msgs[1]["content"], "```", ""]
    return out


def heldout_section() -> tuple[list[str], dict]:
    data = json.loads((CP / "nlu_heldout/heldout_set.json").read_text(encoding="utf-8"))
    preds = defaultdict(dict)
    for c in rows(CP / "logs/nlu_heldout/calls.jsonl"):
        preds[(c["did"], c["line"], c["variant"])][c["seed"]] = c["predicate"]
    tot = Counter()
    out = ["## 3. 새 문장 세트 대화 기록 (V3 검증, 네 조건 모두)", "",
           "출처 `nlu_heldout/heldout_set.json`(`draft_pending_user_approval`), 예측 `logs/nlu_heldout/calls.jsonl`. "
           "칸 안의 세 값은 seed 11·29·47의 예측 술어다. **✗n**은 위험도(고/저)를 틀린 seed 수다.", ""]
    for d in data["dialogues"]:
        out += [f"### {d['dialogue_id']}", "", "| 줄 | 손님 말 | 정답 | 유형 | B | V1 | V2 | V3 |", "|---:|---|---|---|---|---|---|---|"]
        for i, line in enumerate(d["lines"], start=1):
            cells = []
            for name in V:
                ps = [preds[(d["dialogue_id"], i, name)][s] for s in cfg.SEEDS]
                txt, ok = cell(ps, line["label"])
                tot[name] += ok
                cells.append(txt)
            out.append(f"| {i} | {esc(line['utterance'])} | {KO[line['label']]} | {line['type']} | " + " | ".join(cells) + " |")
        out.append("")
    return out, dict(tot)


def scenario_appendix() -> tuple[list[str], dict, dict]:
    calls = defaultdict(dict)
    for c in rows(CP / "logs/nlu_improve/calls.jsonl"):
        calls[(c["sid"], c["turn"], c["variant"])][c["seed"]] = c["predicate"]
    for c in rows(CP / "logs/nlu_heldout/seen_calls.jsonl"):
        calls[(c["sid"], c["turn"], "V3")][c["seed"]] = c["predicate"]
    risk_ok, agree = Counter(), Counter()
    out = ["# 부록 A. 기존 27편 채점턴 NLU 기록 (B·V1·V2·V3)", "",
           "출처: B·V1·V2는 `logs/nlu_improve/calls.jsonl`(M1P5 오프라인, dev=`*_v1`, test=`*_v2`·`*_v3`), "
           "V3는 `logs/nlu_heldout/seen_calls.jsonl`. 이 자료는 V1~V3 설계에 쓰였으므로 일반화 근거가 아니다. "
           "칸 안의 세 값은 seed 11·29·47의 예측 술어이고, **✗n**은 위험도를 틀린 seed 수다. "
           "'결정'은 그 술어를 M1P1 정책에 넣었을 때 정답 결정과 일치한 seed 수다.", ""]
    for split in ("dev", "test"):
        items = ni.scored_items(split)
        cur = None
        for it in items:
            if it["sid"] != cur:
                cur = it["sid"]
                out += ["", f"## {cur} ({split}, trust={it['trust']})", "",
                        "| 턴 | 손님 말 | 정답 술어 | 증거 | 정답 결정 | B | V1 | V2 | V3 |", "|---:|---|---|---|---|---|---|---|---|"]
            cells = []
            for name in V:
                ps = [calls[(it["sid"], it["turn"], name)][s] for s in cfg.SEEDS]
                txt, ok = cell(ps, it["truth"])
                dec_ok = sum(cfg.expected_decision(cfg.risk_of(p), it["evidence"], it["trust"], it["contradicts"]) == it["expected"] for p in ps)
                risk_ok[(name, split)] += ok
                agree[(name, split)] += dec_ok
                cells.append(f"{txt} (결정 {dec_ok}/3)")
            out.append(f"| {it['turn']} | {esc(it['utterance'])} | {KO[it['truth']]} | {it['evidence']} | {DEC[it['expected']]} | " + " | ".join(cells) + " |")
    return out, {f"{k[0]}_{k[1]}": v for k, v in risk_ok.items()}, {f"{k[0]}_{k[1]}": v for k, v in agree.items()}


def live_appendix() -> list[str]:
    live = {}
    for p, cond in ((CP / "logs/runs.jsonl", "M1P1"), (CP / "logs/adversarial/runs.jsonl", "M1P1"),
                    (CP / "logs/nlu_improve/runs.jsonl", "M1P5")):
        for r in rows(p):
            if r["condition"] == cond and r["seed"] == 11:
                live.setdefault((cond, r["scenario_id"]), r)
    out = ["# 부록 B. 라이브 대화 기록: M1P1(NLU=B) vs M1P5(NLU=V2), seed 11", "",
           "출처: M1P1 `logs/runs.jsonl`·`logs/adversarial/runs.jsonl`, M1P5 `logs/nlu_improve/runs.jsonl`. "
           "두 조건은 NLU만 다르고 기억·정책·대사 프롬프트는 같다(스텁 재생 81/81 일치). "
           "**V1과 V3는 라이브 대화를 돌린 적이 없어 NPC 대사 기록이 없다.** seed 29·47 대화는 같은 파일에 있다.", ""]
    for sid in sorted({k[1] for k in live}):
        a, b = live[("M1P1", sid)], live[("M1P5", sid)]
        out += [f"## {sid} (trust={a['trust']})", "",
                "| 턴 | 손님 말 | 정답 결정 | B: 술어 → 결정 | 도르만 대사 (M1P1) | V2: 술어 → 결정 | 도르만 대사 (M1P5) |",
                "|---:|---|---|---|---|---|---|"]
        for ta, tb in zip(a["turns"], b["turns"]):
            ma = "" if ta["decision"] == ta["expected_decision"] else " ✗"
            mb = "" if tb["decision"] == tb["expected_decision"] else " ✗"
            out.append(f"| {ta['turn']} | {esc(ta['player'])} | {DEC[ta['expected_decision']]} | "
                       f"{KO[ta['nlu_predicate']]} → {DEC[ta['decision']]}{ma} | {esc(ta['response'])} | "
                       f"{KO[tb['nlu_predicate']]} → {DEC[tb['decision']]}{mb} | {esc(tb['response'])} |")
        out.append("")
    return out


def main() -> None:
    held, held_tot = heldout_section()
    appA, seen_risk, seen_agree = scenario_appendix()
    a3 = json.loads((OUT / "v3_analysis.json").read_text(encoding="utf-8"))
    off = json.loads((OUT / "nlu_offline.json").read_text(encoding="utf-8"))
    checks = [(f"새 세트 {v} 위험도 정답", held_tot[v], a3["summary"][v]["risk_ok"]) for v in V]
    for v in ("B", "V1", "V2"):
        for s in ("dev", "test"):
            checks.append((f"기존 {s} {v} 위험도 정답", seen_risk[f"{v}_{s}"], off[s][v]["risk_ok"]))
            checks.append((f"기존 {s} {v} 결정 일치", seen_agree[f"{v}_{s}"], off[s][v]["agree"]))
    seen = a3["seen_27_scenarios_V3_descriptive"]
    for s in ("dev", "test"):
        checks.append((f"기존 {s} V3 결정 일치", seen_agree[f"V3_{s}"], seen[f"{s}_agree"]))
    summary = ["## 2. 조건별 요약 (원자료에서 다시 센 값)", "",
               "| 조건 | 새 세트 위험도 정답 (/360) | 기존 dev 결정 일치 (/120) | 기존 test 결정 일치 (/234) |", "|---|---:|---:|---:|"]
    for v in V:
        summary.append(f"| {v} | {held_tot[v]} | {seen_agree[f'{v}_dev']} | {seen_agree[f'{v}_test']} |")
    summary += ["", "대조: 아래 값은 이 표를 분석 JSON(`v3_analysis.json`, `nlu_offline.json`)과 맞춘 결과다.", "",
                "| 항목 | 기록에서 센 값 | 분석 JSON | 일치 |", "|---|---:|---:|---|"]
    summary += [f"| {n} | {a} | {b} | {'✓' if a == b else '✗'} |" for n, a, b in checks]
    head = ["# NLU 조건(B·V1·V2·V3)과 대화 기록 보고서", "",
            "자동 생성: `python3 nlu_variant_record.py`. 모든 표는 원자료 로그에서 직접 만든다.",
            "부록 A: `부록A_기존시나리오_NLU기록.md`, 부록 B: `부록B_라이브대화기록.md`.", "",
            "읽는 법: 술어(무엇을 주장했나)는 예약·선금·보상약속·할인약속·심부름·소유(고위험), 소문·없음(저위험)으로 나뉜다. "
            "정책은 위험도만 보므로 위험도를 맞히면 결정도 맞는다.", ""]
    (OUT / "NLU조건_대화기록_보고서.md").write_text("\n".join(head + conditions_section() + summary + [""] + held), encoding="utf-8")
    (OUT / "부록A_기존시나리오_NLU기록.md").write_text("\n".join(appA), encoding="utf-8")
    (OUT / "부록B_라이브대화기록.md").write_text("\n".join(live_appendix()), encoding="utf-8")
    bad = [c for c in checks if c[1] != c[2]]
    print(f"checks {len(checks)} mismatches {len(bad)}", bad)


if __name__ == "__main__":
    main()
