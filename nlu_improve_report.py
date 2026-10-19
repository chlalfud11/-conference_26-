from __future__ import annotations

import json
from pathlib import Path

CP = Path(__file__).resolve().parent
LOG, OUT = CP / "logs/nlu_improve", CP / "results/bottleneck"


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f(x, nd=4):
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def offline_table(split: dict) -> str:
    head = "| 변형 | 결정 일치 | 위험도 정확도 | 술어 정확도 | 고→저 | 저→고 | 정당 수용(TCAR) | 기준① | NLU 지연 중앙값(ms) | 스키마 |\n|---|---|---|---|---:|---:|---|---:|---:|---|\n"
    rows = []
    for v in ("B", "V1", "V2"):
        m = split.get(v)
        if not m:
            rows.append(f"| {v} | 미실행 |||||||||")
            continue
        rows.append(f"| {v} | {m['agree']}/{m['n']} ({f(m['agree_rate'])}) | {m['risk_ok']}/{m['n']} ({f(m['risk_acc'])}) | "
                    f"{m['pred_ok']}/{m['n']} | {m['high_to_low']} | {m['low_to_high']} | "
                    f"{m['accepted_ok']}/{m['should_accept']} | {m['promoted_without_policy']} | {m['latency_median_ms']} | "
                    f"{m['schema_ok']}/{m['n']} |")
    return head + "\n".join(rows)


def main() -> None:
    diag, freeze = load(OUT / "diagnosis.json"), load(LOG / "freeze.json")
    sel, offline = load(LOG / "selection.json"), load(OUT / "nlu_offline.json")
    replay, ana = load(LOG / "replay_check.json"), load(OUT / "nlu_improve_analysis.json")
    lines = ["# 병목 진단과 NLU 개선 실험 (M1P5) 결과", "",
             "자동 생성: `python3 nlu_improve_report.py`. 수치는 아래 JSON에서 그대로 옮긴다.", "",
             "## 1. 병목 진단 (`results/bottleneck/diagnosis.json`, 추론 0건)", ""]
    if diag:
        a = diag["decision_attribution"]["M1P1"]
        lines += [f"- 채점턴 고유 NLU {diag['unique_scored_nlu_calls']}회: 위험도 정확도 {f(diag['nlu_risk_accuracy'])}, "
                  f"술어 정확도 {f(diag['nlu_predicate_accuracy'])}",
                  f"- 위험도 혼동: {diag['risk_confusion']}",
                  f"- M1P1 결정 귀속: {a}",
                  "- 지연(ms, 중앙값/p95): " + "; ".join(
                      f"{c} NLU {v['nlu']['median']}/{v['nlu']['p95']}, 발화 {v['speech']['median']}/{v['speech']['p95']}"
                      for c, v in diag["latency_ms"].items() if c in ("M1P1", "M1P4")), ""]
    lines += ["## 2. 사전등록·동결", "",
              f"- 동결 시각 {freeze['frozen_at_utc'] if freeze else '없음'} (`logs/nlu_improve/freeze.json`, 동결 시 호출 존재 여부={freeze and freeze['calls_exist']})",
              f"- 스텁 재생: {replay}", ""]
    if sel:
        lines += ["## 3. dev 선택 (`logs/nlu_improve/selection.json`)", "",
                  f"- 기록 시각 {sel['at_utc']}, 선택 변형 **{sel['selected']}**, 라이브 진행 **{sel['go_live']}**", "",
                  offline_table(sel["dev"]), ""]
    if offline:
        lines += ["## 4. 오프라인 결과 전체 (`results/bottleneck/nlu_offline.json`)", "", "### dev (v1, 9편)", "",
                  offline_table(offline["dev"]), "", "### test (v2·v3, 18편)", "", offline_table(offline["test"]), ""]
    if ana:
        s, p = ana["summary"], ana["primary_agree_M1P1_vs_M1P5"]
        lines += ["## 5. 라이브 M1P5 vs M1P1 (`results/bottleneck/nlu_improve_analysis.json`)", "",
                  "| 조건 | 런 | 결정 일치율 | 위험도 정확도 | TCAR | 기준① 비율 | 기준② 비율 | 턴 지연 중앙값/p95(ms) |",
                  "|---|---:|---|---|---|---|---|---|"]
        for c in ("M1P1", "M1P5"):
            m = s[c]
            lines.append(f"| {c} | {m['runs']} | {m['agree']}/{m['n']} ({f(m['agree_rate'])}) | {f(m['risk_acc'])} | "
                         f"{m['accepted_ok']}/{m['should_accept']} ({f(m['TCAR'])}) | {m['promoted_without_policy']}/{m['inj']} ({f(m['c1_rate'])}) | "
                         f"{m['asserted_as_fact_in_utterance']}/{m['inj']} ({f(m['c2_rate'])}) | {m['turn_latency_median_ms']}/{m['turn_latency_p95_ms']} |")
        lines += ["", f"**주 검정 (결정 일치율, 시나리오 부호뒤집기, 양측)**: 평균 차이 {f(p['mean_diff'])}, "
                  f"p={f(p['p_two_sided'], 6)}, 95% CI [{f(p['ci95'][0])}, {f(p['ci95'][1])}], "
                  f"차이 난 시나리오 {p['discordant']}/{p['n_scenarios']}", "", "**부 검정 (Holm 3개)**", ""]
        for k, t in ana["secondary"].items():
            extra = f", 평균 차이 {f(t['mean_diff'])}, CI [{f(t['ci95'][0])}, {f(t['ci95'][1])}], k={t['discordant']}" if "mean_diff" in t else ""
            lines.append(f"- {k}: p={f(t['p_two_sided'], 6)}, Holm={f(t['holm'], 6)}{extra}")
        lines.append("")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report_tables.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
