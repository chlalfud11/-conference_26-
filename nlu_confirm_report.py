from __future__ import annotations

import json
from pathlib import Path

CP = Path(__file__).resolve().parent
A = CP / "results/bottleneck/confirm_analysis.json"
OUT = CP / "results/bottleneck/confirm_report_tables.md"
V = ("B", "V1", "V4")
TYPES = ("claim", "insist", "rumor_after_claim", "rumor", "none")


def main() -> None:
    a = json.loads(A.read_text(encoding="utf-8"))
    s = a["summary"]
    lines = ["| 조건 | 위험도 정확도 | 술어 정확도 | 고→저 | 저→고 | 스키마 |", "|---|---|---|---:|---:|---|"]
    for v in V:
        m = s[v]
        lines.append(f"| {v} | {m['risk_ok']}/{m['n']} ({m['risk_acc']:.4f}) | {m['pred_ok']}/{m['n']} ({m['pred_acc']:.4f}) | "
                     f"{m['high_to_low']} | {m['low_to_high']} | {m['schema_ok']}/{m['n']} |")
    lines += ["", f"V4 게이트가 켜진 호출: {s['V4']['gate_on']}/{s['V4']['n']}", "",
              "| 유형 | " + " | ".join(V) + " |", "|---|---|---|---|"]
    for t in TYPES:
        lines.append(f"| {t} | " + " | ".join(f"{s[v]['by_type'][t]['ok']}/{s[v]['by_type'][t]['n']}" for v in V) + " |")
    p = a["primary_B_vs_V1"]
    lines += ["", "| 검정 | 평균 차이 | p (양측) | Holm | 95% CI | 차이 난 대화 |", "|---|---:|---:|---:|---|---:|",
              f"| 주: V1 vs B | {p['mean_diff']:+.4f} | {p['p_two_sided']:.4f} | — | [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}] | {p['discordant']}/{p['n_dialogues']} |"]
    for k, t in a["secondary"].items():
        lines.append(f"| 부: {k} | {t['mean_diff']:+.4f} | {t['p_two_sided']:.4f} | {t['holm']:.4f} | "
                     f"[{t['ci95'][0]:+.4f}, {t['ci95'][1]:+.4f}] | {t['discordant']}/{t['n_dialogues']} |")
    lines += ["", f"판정: adopt_V1 = **{a['adopt_V1']}**, prefer_V4_over_V1 = **{a['prefer_V4_over_V1']}**", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
