from __future__ import annotations

import json
from pathlib import Path

CP = Path(__file__).resolve().parent
A = CP / "results/bottleneck/v3_analysis.json"
OUT = CP / "results/bottleneck/v3_report_tables.md"
TYPES = ("claim", "insist", "rumor_after_claim", "rumor", "none")


def main() -> None:
    a = json.loads(A.read_text(encoding="utf-8"))
    s = a["summary"]
    lines = ["| 변형 | 위험도 정확도 | 술어 정확도 | 고→저 | 저→고 | 스키마 |", "|---|---|---|---:|---:|---|"]
    for v in ("B", "V1", "V2", "V3"):
        m = s[v]
        lines.append(f"| {v} | {m['risk_ok']}/{m['n']} ({m['risk_acc']:.4f}) | {m['pred_ok']}/{m['n']} ({m['pred_acc']:.4f}) | "
                     f"{m['high_to_low']} | {m['low_to_high']} | {m['schema_ok']}/{m['n']} |")
    lines += ["", "| 유형 | " + " | ".join(("B", "V1", "V2", "V3")) + " |", "|---|---|---|---|---|"]
    for t in TYPES:
        cells = [f"{s[v]['by_type'][t]['ok']}/{s[v]['by_type'][t]['n']}" if t in s[v]["by_type"] else "-" for v in ("B", "V1", "V2", "V3")]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    p = a["primary_B_vs_V3"]
    lines += ["", "| 검정 | 평균 차이 | p (양측) | Holm | 95% CI | 차이 난 대화 |", "|---|---:|---:|---:|---|---:|",
              f"| 주: V3 vs B | {p['mean_diff']:+.4f} | {p['p_two_sided']:.4f} | — | [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}] | {p['discordant']}/{p['n_dialogues']} |"]
    for k, t in a["secondary"].items():
        lines.append(f"| 부: {k} | {t['mean_diff']:+.4f} | {t['p_two_sided']:.4f} | {t['holm']:.4f} | "
                     f"[{t['ci95'][0]:+.4f}, {t['ci95'][1]:+.4f}] | {t['discordant']}/{t['n_dialogues']} |")
    lines += ["", f"채택 규칙 결과 adopt_V3 = **{a['adopt_V3']}**", ""]
    seen = a.get("seen_27_scenarios_V3_descriptive")
    if seen:
        lines.append(f"기존 27편(설계에 쓰인 자료, 기술 통계): dev 일치 {seen['dev_agree']}/{seen['dev_n']}, "
                     f"test 일치 {seen['test_agree']}/{seen['test_n']}, 고→저 dev {seen['dev_high_to_low']}·test {seen['test_high_to_low']}, "
                     f"저→고 dev {seen['dev_low_to_high']}·test {seen['test_low_to_high']}, "
                     f"정당 수용 dev {seen['dev_accepted_ok']}·test {seen['test_accepted_ok']}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
