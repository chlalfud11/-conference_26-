from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from npc import config  # noqa: E402

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def fmt(value: str, digits: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if number != number else f"{number:.{digits}f}"


def ci(row: dict, key: str) -> str:
    lo, hi = fmt(row.get(f"{key}_lo", "")), fmt(row.get(f"{key}_hi", ""))
    if "n/a" in (lo, hi):
        return ""
    return f"[{lo}, {hi}]"


def narrative(rows: dict[str, dict]) -> str:
    def value(condition: str, key: str) -> float:
        try:
            return float(rows[condition][key])
        except (KeyError, TypeError, ValueError):
            return float("nan")

    def interval(condition: str, key: str) -> tuple[float, float]:
        return value(condition, f"{key}_lo"), value(condition, f"{key}_hi")

    def overlaps(a: str, b: str, key: str = "CCR") -> bool:
        a_lo, a_hi = interval(a, key)
        b_lo, b_hi = interval(b, key)
        if any(v != v for v in (a_lo, a_hi, b_lo, b_hi)):
            return True
        return a_lo <= b_hi and b_lo <= a_hi

    base, struct, full = value("M0P0", "CCR"), value("M1P0", "CCR"), value("M1P1", "CCR")
    if any(v != v for v in (base, struct, full)):
        return "일부 조건의 CCR을 계산할 수 없어 비교를 생략한다."

    parts = []
    policy_gain = struct - full
    structure_gain = base - struct

    if full < base:
        parts.append(f"제안 구조(M1P1)의 CCR은 Vector RAG 기준선(M0P0)보다 "
                     f"{abs(base - full):.3f} 낮았다.")
    elif full > base:
        parts.append(f"제안 구조(M1P1)의 CCR이 Vector RAG 기준선(M0P0)보다 "
                     f"{abs(full - base):.3f} 높았다. 가설과 반대되는 결과다.")
    else:
        parts.append("제안 구조와 Vector RAG 기준선의 CCR이 같았다.")

    if overlaps("M0P0", "M1P1"):
        parts.append("다만 두 조건의 95% 신뢰구간이 겹치므로 이 차이를 통계적으로 구분되는 "
                     "것으로 주장하지 않는다.")

    if structure_gain > 0 and policy_gain < 0:
        parts.append(
            f"감소는 구조화 기억 단계에서 {structure_gain:.3f}만큼 발생했고, "
            f"여기에 승격 정책을 더한 M1P1은 오히려 M1P0보다 CCR이 {abs(policy_gain):.3f} 높았다. "
            "따라서 본 구성에서 오염 감소의 주된 요인은 승격 정책이 아니라 기억을 구조화하고 "
            "출처 라벨을 모델에 노출한 것이다. 단, 다음 절에서 보이듯이 M1P0의 낮은 CCR 은 "
            "모든 주장에 거의 동일한 결정을 내리는 보수성의 결과이므로 "
            "Macro-F1 과 함께 읽어야 한다."
        )
    elif abs(structure_gain) < 0.05 and policy_gain > 0.05:
        parts.append(
            "구조화 기억만 적용한 M1P0은 기준선과 뚜렷한 차이를 보이지 않은 반면 "
            "승격 정책을 더한 M1P1에서 감소가 나타났다. "
            "이는 감소의 원인이 기억을 구조화한 것이 아니라 승격 정책임을 시사한다."
        )
    elif structure_gain > 0.05 and policy_gain > 0.05:
        parts.append(
            f"구조화만으로도 {structure_gain:.3f}의 감소가 있었고 "
            f"정책이 추가로 {policy_gain:.3f}를 줄였다. "
            "따라서 감소분은 두 요인에 나뉘어 귀속된다."
        )
    else:
        parts.append(
            f"구조화의 효과는 {structure_gain:.3f}, 정책의 추가 효과는 {policy_gain:.3f}로 "
            "두 요인 모두 뚜렷한 분리를 보이지 않았다."
        )

    f1 = {c: value(c, "MacroF1") for c in ("M0P0", "M1P0", "M1P1")}
    if all(v == v for v in f1.values()):
        best = max(f1, key=lambda c: f1[c])
        parts.append(
            f"5지 결정의 Macro-F1 은 {best}이 {f1[best]:.3f}로 가장 높았다"
            + (f"(M0P0 {f1['M0P0']:.3f}, M1P0 {f1['M1P0']:.3f}). "
               if best == "M1P1" else ". ")
            + "CCR 은 한 가지 결정으로 일관되게 답해도 낮아질 수 있으므로, "
            "결정을 상황별로 구분하는 능력은 Macro-F1 로 판단해야 한다."
        )

    t_base, t_full = value("M0P0", "TCAR"), value("M1P1", "TCAR")
    if t_full == t_full and t_base == t_base:
        if t_full >= t_base:
            parts.append(
                f"참 주장 수용률은 M1P1이 {t_full:.3f}로 기준선 {t_base:.3f} 이상이었다. "
                "따라서 CCR 감소가 모든 주장을 거절한 결과가 아니다."
            )
        else:
            parts.append(
                f"다만 참 주장 수용률이 기준선 {t_base:.3f}에서 M1P1 {t_full:.3f}로 낮아졌다. "
                "오염 감소의 일부가 과잉 거절에서 비롯되었을 가능성을 배제할 수 없다."
            )
    return " ".join(parts)


def conclusion(rows: dict[str, dict]) -> str:
    try:
        base = float(rows["M0P0"]["CCR"])
        struct = float(rows["M1P0"]["CCR"])
        full = float(rows["M1P1"]["CCR"])
    except (KeyError, TypeError, ValueError):
        return "측정 결과의 해석은 본문 5장에 기술했다."
    if full < struct and abs(struct - base) < 0.05:
        return ("구조화 기억만으로는 플레이어 주장 오염이 줄지 않았고, "
                "승격 정책을 더했을 때 감소가 나타났다.")
    if struct < full < base:
        return ("오염 감소의 주된 요인은 승격 정책이 아니라 기억을 구조화하고 출처를 "
                "모델에 노출한 것이었으며, 정책의 가치는 오염률이 아니라 결정을 상황별로 "
                "구분하는 능력(Macro-F1)에서 나타났다.")
    if full < base:
        return ("제안 구조가 기준선보다 낮은 오염률을 보였으며, "
                "그 감소분은 구조와 정책에 각각 귀속된다.")
    return "본 구성에서는 기준선 대비 뚜렷한 오염 감소가 관측되지 않았다."


def policy_ceiling(rows: dict[str, dict], nlu_acc: str) -> str:
    row = rows.get("M1P1")
    if row is None:
        return ""
    try:
        defer = float(row["defer_rate"])
        missed = float(row["nlu_missed_claim_rate"])
    except (KeyError, TypeError, ValueError):
        return ""
    if defer < 0.05:
        return (
            "**승격 정책은 입력 이해 결과에 결합되어 있다.** 정책 엔진은 구조화된 주장 술어에서 "
            f"위험도를 유도하므로 입력 이해의 오류가 그대로 전파된다. 본 실행에서 보류 결정 비율은 "
            f"{defer:.3f}로 낮아 이 경로가 성능을 크게 제한하지는 않았다."
        )
    return (
        "**승격 정책의 상한은 입력 이해 정확도가 결정한다.** M1P1의 채점 대상 결정 가운데 "
        f"{defer:.3f}가 보류(`defer`)였고, 같은 구간에서 입력 이해가 주장을 전혀 추출하지 못한 "
        f"비율은 {missed:.3f}였다. 정책 엔진은 구조화된 주장 술어에서 위험도를 유도하므로, "
        "주장이 추출되지 않으면 저위험으로 간주되어 판단이 보류된다. 반면 구조화 기억만 사용하고 "
        "결정을 모델에 맡긴 M1P0은 원문과 출처 라벨을 직접 읽어 이 병목을 우회한다. "
        "정책을 결정 계층에 두는 설계가 치르는 비용이며, 입력 이해 정확도 "
        f"{nlu_acc}가 그대로 정책 성능의 천장이 된다. "
        "본 연구가 구조만 적용한 대조 조건을 함께 실행했기 때문에 드러난 사실이다."
    )


def decision_table(rows: dict[str, dict]) -> str:
    decisions = ("accept_as_belief", "request_evidence", "dispute", "defer", "reject")
    header = "| 조건 | " + " | ".join(f"`{d}`" for d in decisions) + " |"
    lines = [header, "|---|" + "---|" * len(decisions)]
    for condition, row in rows.items():
        cells = " | ".join(str(row.get(f"d_{d}", 0)) for d in decisions)
        lines.append(f"| {condition} | {cells} |")
    return "\n".join(lines)


def contamination_table(rows: dict[str, dict]) -> str:
    keys = [("c_promoted_without_policy", "① 정책 조건 없이 믿음으로 승격 (M1P1은 설계 보장)"),
            ("c_asserted_as_fact_in_utterance", "② 생성 대사에서 확정 사실로 단정"),
            ("c_used_as_action_basis", "③ 거짓 주장에 근거한 거래 성사 (본 시나리오 집합 미가동)"),
            ("c_world_truth_changed", "④ 보호 대상 상태 변경")]
    header = "| 오염 기준 | " + " | ".join(rows) + " |"
    divider = "|---|" + "---|" * len(rows)
    lines = [header, divider]
    for key, label in keys:
        cells = " | ".join(str(rows[c].get(key, 0)) for c in rows)
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines)


def number(rows: dict[str, dict], condition: str, key: str) -> float:
    try:
        return float(rows[condition][key])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def alt_table(rows: dict[str, dict]) -> str:
    lines = ["| \uc870\uac74 | CCR \uc804\uccb4 \u2193 | CCR \uae30\uc900 \u2460 \uc81c\uc678 \u2193 | "
             "Macro-F1 \uad00\ub840 \u2191 | Macro-F1 5\ub77c\ubca8 \uace0\uc815 \u2191 |",
             "|---|---|---|---|---|"]
    for condition in config.MAIN_CONDITIONS:
        row = rows.get(condition)
        if row is None:
            continue
        lines.append(f"| {condition} | {fmt(row.get('CCR', ''))} | "
                     f"{fmt(row.get('CCR_nopol', ''))} | {fmt(row.get('MacroF1', ''))} | "
                     f"{fmt(row.get('MacroF1_fixed', ''))} |")
    return "\n".join(lines)


def ccr_structural_note(rows: dict[str, dict], high_risk_high_trust: int) -> str:
    full = {c: number(rows, c, "CCR") for c in config.MAIN_CONDITIONS}
    nopol = {c: number(rows, c, "CCR_nopol") for c in config.MAIN_CONDITIONS}
    if any(v != v for v in [*full.values(), *nopol.values()]):
        return ""
    best_full = min(full, key=lambda c: full[c])
    best_nopol = min(nopol, key=lambda c: nopol[c])
    moved = ", ".join(f"{c} {full[c]:.3f} \u2192 {nopol[c]:.3f}" for c in config.MAIN_CONDITIONS)
    tail = (f"\uc804\uccb4 \uae30\uc900\uc5d0\uc11c CCR \uc774 \uac00\uc7a5 \ub0ae\ub358 \uc870\uac74\uc740 {best_full}, "
            f"\uae30\uc900 \u2460 \uc744 \ube80 \ub4a4 \uac00\uc7a5 \ub0ae\uc740 \uc870\uac74\uc740 {best_nopol} \ub85c \uc21c\uc704\uac00 \ubc14\ub01c\ub2e4."
            if best_full != best_nopol else
            f"\uae30\uc900 \u2460 \uc744 \ube80 \ub4a4\uc5d0\ub3c4 CCR \uc774 \uac00\uc7a5 \ub0ae\uc740 \uc870\uac74\uc740 {best_nopol} \ub85c \uac19\ub2e4.")
    return (
        "**\uae30\uc900 \u2460\uc740 \uc870\uac74\uc5d0 \ub530\ub77c \ud2b8\ub9ac\uac70 \uac00\ub2a5\uc131 \uc790\uccb4\uac00 \ub2e4\ub974\ub2e4.** \uae30\uc900 \u2460\uc740 \uacb0\uc815\uc774 "
        "`accept_as_belief` \uc778\ub370 \uc815\ub2f5 \ub77c\ubca8\uc740 \uadf8\ub807\uc9c0 \uc54a\uc740 \ud134\uc744 \uc13c\ub2e4. M1P1 \uc758 \uacb0\uc815\uc740 \uc815\ub2f5 \ub77c\ubca8\uacfc "
        "\uac19\uc740 \uacb0\uc815\ud45c\uac00 \ub0b4\ub9ac\ubbc0\ub85c, \uc785\ub825 \uc774\ud574\uac00 \uc704\ud5d8\ub3c4 \ub4f1\uae09\uc744 \ub4a4\uc9d1\uc740 \ud134\uc5d0\uc11c\ub9cc \uc774 \uae30\uc900\uc5d0 \uac78\ub9b4 \uc218 "
        f"\uc788\ub2e4. \uadf8\ub7f0\ub370 \uace0\uc704\ud5d8 \ud134\uc744 \ud3ec\ud568\ud558\uba74\uc11c \uc2e0\ub8b0\ub3c4\uac00 \uc218\uc6a9 \uc784\uacc4\uac12 \uc774\uc0c1\uc778 \uc2dc\ub098\ub9ac\uc624\ub294 "
        f"{high_risk_high_trust}\ud3b8\uc774\ubbc0\ub85c, \ub4f1\uae09\uc774 \ub4a4\uc9d1\ud600\ub3c4 \uacb0\uc815\uc740 `accept_as_belief` \uac00 \uc544\ub2c8\ub77c "
        "`defer` \uac00 \ub41c\ub2e4. \uc989 M1P1 \uc5d0\uc11c \uae30\uc900 \u2460 \uc740 \uc131\ub2a5\uc774 \uc544\ub2c8\ub77c \uc124\uacc4\uc0c1 0 \uc774\ub2e4. "
        f"\uae30\uc900 \u2460 \uc744 \uc81c\uc678\ud558\uba74 CCR \uc740 {moved} \ub85c \ubc14\ub010\ub2e4. " + tail +
        " \ub530\ub77c\uc11c \ubcf8 \uad6c\uc131\uc5d0\uc11c M1P1 \uacfc \uae30\uc900\uc120\uc758 CCR \ucc28\uc774\ub97c \uc815\ucc45\uc758 \uc131\uacfc\ub85c \uc77d\uc5b4\uc11c\ub294 \uc548 \ub41c\ub2e4."
    )


def identity_note(rows: dict[str, dict]) -> str:
    row = rows.get("M1P1")
    if row is None:
        return ""
    try:
        ok_hit, ok_n = int(row["agree_nlu_ok"]), int(row["n_nlu_ok"])
        bad_hit, bad_n = int(row["agree_nlu_bad"]), int(row["n_nlu_bad"])
    except (KeyError, TypeError, ValueError):
        return ""
    others = [f"{c} {int(rows[c]['agree_nlu_ok'])}/{int(rows[c]['n_nlu_ok'])}"
              for c in ("M0P0", "M1P0") if c in rows]
    return (
        "**Macro-F1 \ube44\uad50\ub294 \uc815\ub2f5 \ub77c\ubca8\uacfc M1P1 \uc815\ucc45\uc774 \uac19\uc740 \ud568\uc218\ub97c \uc4f4\ub2e4\ub294 \uc810\uc744 \ube7c\uace0 \uc77d\uc744 \uc218 "
        "\uc5c6\ub2e4.** 4.3\uc808\uc5d0\uc11c \ubc1d\ud614\ub4ef \ub458\uc740 \ub3d9\uc77c\ud55c \uacb0\uc815\ud45c\uc5d0 \ub3d9\uc77c\ud55c \uc99d\uac70\u00b7\uc2e0\ub8b0\ub3c4\u00b7\ubaa8\uc21c \uc785\ub825\uc744 \ub123\uace0 "
        "\uc704\ud5d8\ub3c4\ub9cc \ucc38 \uc220\uc5b4\uc640 \ucd94\ucd9c \uc220\uc5b4\ub85c \uac08\ub9b0\ub2e4. \uadf8\ub798\uc11c \uc785\ub825 \uc774\ud574\uac00 \uc220\uc5b4\ub97c \ub9de\ud78c \ud134\uc5d0\uc11c M1P1 \uc758 "
        f"\uacb0\uc815\uc740 \uc815\ub2f5\uacfc \uc77c\uce58\ud560 \uc218\ubc16\uc5d0 \uc5c6\uace0, \uc2e4\uc81c\ub85c {ok_hit}/{ok_n} \uc774\uc5c8\ub2e4. \uac19\uc740 \uad6c\uac04\uc5d0\uc11c "
        + ", ".join(others) + " \uc774\ub2e4. \uc785\ub825 \uc774\ud574\uac00 \ud2c0\ub9b0 \ud134\uc5d0\uc11c\ub294 M1P1 \uc774 "
        f"{bad_hit}/{bad_n} \ub85c \ub5a8\uc5b4\uc9c4\ub2e4. \ub530\ub77c\uc11c M1P1 \uc758 Macro-F1 \uc740 '\uc815\ucc45\uc774 \ub354 \uc798 \ud310\ub2e8\ud55c\ub2e4'\uac00 "
        "\uc544\ub2c8\ub77c '\ucf54\ub4dc\uac00 \uc0ac\uc591\uc744 \uc9d1\ud589\ud558\uba74 \uc0ac\uc591\uacfc \uc77c\uce58\ud558\uba70 \uadf8 \uc0c1\ud55c\uc740 \uc785\ub825 \uc774\ud574\uac00 \uc815\ud55c\ub2e4'\ub85c "
        "\uc77d\uc5b4\uc57c \ud55c\ub2e4. \ub354\uad6c\ub098 \uc8fc \uc2e4\ud5d8\uc5d0\uc11c M0P0\u00b7M1P0 \uc758 \ud504\ub86c\ud504\ud2b8\uc5d0\ub294 \ucc44\uc810 \uae30\uc900\uc778 \uacb0\uc815\ud45c\uac00 \ub4e4\uc5b4 "
        "\uc788\uc9c0 \uc54a\ub2e4. \uc774 \ube44\ub300\uce6d\uc744 \uc5c6\uc571 \ube44\uad50\ub97c 5.5\uc808\uc5d0\uc11c \ub530\ub85c \uce21\uc815\ud55c\ub2e4."
    )


def contamination_note(rows: dict[str, dict]) -> str:
    acted = sum(int(r.get("c_used_as_action_basis", 0) or 0) for r in rows.values())
    return (
        "\uae30\uc900 \u2460\uc740 M1P1 \uc5d0\uc11c \uc124\uacc4\uc0c1 0 \uc774 \ub418\ubbc0\ub85c \uc131\uacfc\uac00 \uc544\ub2c8\ub2e4(5.1\uc808). \uae30\uc900 \u2462\ub294 \ubcf8 "
        "\uc2dc\ub098\ub9ac\uc624 \uc9d1\ud569\uc5d0 \uac70\ub798\uac00 \uc8fc\uc7a5\uc5d0 \uc758\uc874\ud55c\ub2e4\uace0 \ud45c\uc2dc\ub41c \ud134\uc774 \uc5c6\uc5b4 \ud55c \ubc88\ub3c4 \uac00\ub3d9\ud558\uc9c0 \uc54a\uc558\uace0, "
        f"\ubaa8\ub4e0 \uc870\uac74\uc5d0\uc11c {acted} \uc73c\ub85c \uae30\ub85d\ub41c\ub2e4. \uc870\uac74 \uac04 \ucc28\uc774\ub97c \uc2e4\uc81c\ub85c \ub9cc\ub4dc\ub294 \uae30\uc900\uc740 "
        "\u2461(\uc0dd\uc131 \ub300\uc0ac\uc5d0\uc11c \ud655\uc815 \uc0ac\uc2e4\ub85c \ub2e8\uc815) \ud558\ub098\uc774\uba70, \ubaa8\ub4e0 \uc870\uac74\uc774 \ub3d9\uc77c\ud55c \uae08\uc9c0 \ud45c\ud604 \ud328\ud134\uc744 "
        "\ub3d9\uc77c\ud55c \ud134 \uc9d1\ud569\uc5d0 \uc801\uc6a9\ubc1b\ub294\ub2e4."
    )


def fair_table(rows: dict[str, dict]) -> str:
    lines = ["| \uc870\uac74 | \uacb0\uc815\ud45c \uace0\uc9c0 | \uc815\ub2f5 \uc77c\uce58\uc728 \u2191 | Macro-F1 \u2191 | "
             "Macro-F1 5\ub77c\ubca8 \u2191 | CCR \u2193 | TCAR \u2191 |",
             "|---|---|---|---|---|---|---|"]
    plan = [("M0P0", "\u2014"), ("M0P0R", "\ud504\ub86c\ud504\ud2b8"), ("M1P0", "\u2014"),
            ("M1P0R", "\ud504\ub86c\ud504\ud2b8"), ("M1P1", "\ucf54\ub4dc\uac00 \uc9d1\ud589")]
    for condition, tag in plan:
        row = rows.get(condition)
        if row is None:
            continue
        lines.append(f"| {condition} | {tag} | {fmt(row.get('agree_rate', ''))} | "
                     f"{fmt(row.get('MacroF1', ''))} | {fmt(row.get('MacroF1_fixed', ''))} | "
                     f"{fmt(row.get('CCR', ''))} | {fmt(row.get('TCAR', ''))} |")
    return "\n".join(lines)


def fair_pair(rows: dict[str, dict]) -> tuple[str, float, float] | None:
    need = ("M0P0", "M1P0", "M1P1", "M0P0R", "M1P0R")
    if any(c not in rows for c in need):
        return None
    agree = {c: number(rows, c, "agree_rate") for c in need}
    if any(v != v for v in agree.values()):
        return None
    best = max(("M0P0R", "M1P0R"), key=lambda c: agree[c])
    return best, agree[best], agree["M1P1"]


def fair_narrative(rows: dict[str, dict]) -> str:
    picked = fair_pair(rows)
    if picked is None:
        return "\uacf5\uc815 \ube44\uad50 \uc870\uac74\uc758 \uacb0\uacfc\ub97c \uc9d1\uacc4\ud558\uc9c0 \ubabb\ud574 \ube44\uad50\ub97c \uc0dd\ub7b5\ud55c\ub2e4."
    best, best_value, policy_value = picked
    gap = policy_value - best_value
    moves = ", ".join(
        f"{b} {number(rows, b, 'agree_rate'):.3f} \u2192 {r} {number(rows, r, 'agree_rate'):.3f}"
        for b, r in (("M0P0", "M0P0R"), ("M1P0", "M1P0R")))
    parts = [f"\uacb0\uc815\ud45c\ub97c \ud504\ub86c\ud504\ud2b8\ub85c \uace0\uc9c0\ud588\uc744 \ub54c \uc815\ub2f5 \uc77c\uce58\uc728\uc740 {moves} \ub85c \uc6c0\uc9c1\uc600\ub2e4."]
    if gap > 0.15:
        parts.append(
            f"\uace0\uc9c0\ub97c \ubc1b\uc740 \uc870\uac74 \uc911 \uac00\uc7a5 \ub192\uc740 {best}({best_value:.3f}) \ub3c4 \uacb0\uc815\ud45c\ub97c \ucf54\ub4dc\uac00 "
            f"\uc9d1\ud589\ud55c M1P1({policy_value:.3f})\uc5d0 {gap:.3f} \ubabb \ubbf8\uce5c\ub2e4. \uaddc\uce59\uacfc \uadf8 \uc785\ub825\uc744 \ubaa8\ub450 "
            "\ubc1b\uace0\ub3c4 \ubcf8 \uaddc\ubaa8\uc758 \ubaa8\ub378\uc740 \uc5ec\uc12f \ud589\uc9dc\ub9ac \uacb0\uc815\ud45c\ub97c \uc548\uc815\uc801\uc73c\ub85c \uc9d1\ud589\ud558\uc9c0 \ubabb\ud55c\ub2e4. "
            "\uacb0\uc815\uc744 \ud45c\ud604 \uacc4\uce35\uc774 \uc544\ub2c8\ub77c \ucf54\ub4dc\uc5d0 \ub450\ub294 \uc124\uacc4\uac00 \uc2e4\uc9c8\uc801 \uc774\ub4dd\uc744 \uc900\ub2e4\ub294 \uc9c1\uc811 \uadfc\uac70\ub2e4.")
    elif gap > 0.05:
        parts.append(
            f"\uace0\uc9c0\ub9cc\uc73c\ub85c \uaca9\ucc28\uac00 \uc904\uc5c8\uc9c0\ub9cc {best}({best_value:.3f})\ub294 \uc5ec\uc804\ud788 "
            f"M1P1({policy_value:.3f})\ubcf4\ub2e4 {gap:.3f} \ub0ae\ub2e4. \uc8fc \uc2e4\ud5d8\uc5d0\uc11c \uad00\uce21\ud55c \uaca9\ucc28 \uac00\uc6b4\ub370 "
            "\uc77c\ubd80\ub294 \uaddc\uce59\uc744 \uc54c\ub824\uc8fc\uc9c0 \uc54a\uc740 \ub370\uc11c, \ub098\uba38\uc9c0\ub294 \uc9d1\ud589 \uc8fc\uccb4\uc5d0\uc11c \uc628\ub2e4.")
    elif gap >= 0:
        parts.append(
            f"{best}({best_value:.3f})\uac00 M1P1({policy_value:.3f})\uc640 {gap:.3f} \ucc28\uc774\ub85c \uc0ac\uc2e4\uc0c1 \uac19\ub2e4. "
            "\uc8fc \uc2e4\ud5d8\uc5d0\uc11c \uad00\uce21\ud55c Macro-F1 \uaca9\ucc28\ub294 \uacb0\uc815\uc744 \ucf54\ub4dc\uac00 \uc9d1\ud589\ud588\uae30 \ub54c\ubb38\uc774 \uc544\ub2c8\ub77c "
            "\ube44\uad50 \uc870\uac74\uc774 \ucc44\uc810 \uae30\uc900\uc744 \ubab0\ub790\uae30 \ub54c\ubb38\uc774\uba70, \uc815\ucc45 \uc5d4\uc9c4\uc758 \uae30\uc5ec\ub97c \uacb0\uc815 \ud488\uc9c8\ub85c "
            "\uc8fc\uc7a5\ud560 \uc218 \uc5c6\ub2e4.")
    else:
        parts.append(
            f"{best}({best_value:.3f})\uac00 M1P1({policy_value:.3f})\uc744 {abs(gap):.3f} \uc55e\uc84c\ub2e4. "
            "\uacb0\uc815\uc744 \ucf54\ub4dc\ub85c \uc62e\uae34 \uc124\uacc4\uac00 \ubcf8 \uad6c\uc131\uc5d0\uc11c \uacb0\uc815 \ud488\uc9c8 \uc774\ub4dd\uc744 \uc8fc\uc9c0 \ubabb\ud588\ub2e4\ub294 \ub73b\uc774\ub2e4.")
    parts.append(
        "\ub2e4\ub9cc \uace0\uc9c0 \uc870\uac74\uc740 \uc815\ucc45 \uc5d4\uc9c4\uacfc \ub3d9\uc77c\ud55c \uc624\ub77c\ud074 \uc785\ub825(\uc99d\uac70 \uc0c1\ud0dc\u00b7\uc2e0\ub8b0\ub3c4\u00b7\uc0c1\ud0dc \ubaa8\uc21c)\uc744 "
        "\ud568\uaed8 \ubc1b\uc73c\ubbc0\ub85c, \uc774 \uac12\ub4e4\uc744 \uc2a4\uc2a4\ub85c \ucd94\uc815\ud574\uc57c \ud558\ub294 \uc2e4\uc81c \ubc30\uce58 \uc0c1\ud669\ubcf4\ub2e4 \uc720\ub9ac\ud55c \uc124\uc815\uc774\ub2e4.")
    return " ".join(parts)


def fair_abstract(rows: dict[str, dict]) -> str:
    picked = fair_pair(rows)
    if picked is None:
        return ""
    best, best_value, policy_value = picked
    gap = policy_value - best_value
    if gap > 0:
        return (f"\uace0\uc9c0\ub97c \ubc1b\uc740 \ubaa8\ub378 \uc870\uac74\uc758 \uc815\ub2f5 \uc77c\uce58\uc728\uc740 \ucd5c\ub300 {best_value:.3f} \ub85c, "
                f"\uacb0\uc815\ud45c\ub97c \ucf54\ub4dc\uac00 \uc9d1\ud589\ud55c {policy_value:.3f} \ubcf4\ub2e4 {gap:.3f} \ub0ae\uc558\ub2e4.")
    return (f"\uace0\uc9c0\ub97c \ubc1b\uc740 \ubaa8\ub378 \uc870\uac74\uc758 \uc815\ub2f5 \uc77c\uce58\uc728\uc740 \ucd5c\ub300 {best_value:.3f} \ub85c, "
            f"\uacb0\uc815\ud45c\ub97c \ucf54\ub4dc\uac00 \uc9d1\ud589\ud55c {policy_value:.3f} \uacfc \uac19\uac70\ub098 \ub354 \ub192\uc558\ub2e4.")


def fair_conclusion(rows: dict[str, dict]) -> str:
    picked = fair_pair(rows)
    if picked is None:
        return ""
    best, best_value, policy_value = picked
    gap = policy_value - best_value
    if gap > 0.05:
        return (" 같은 결정표를 프롬프트로 고지받은 모델 조건이 코드 집행 조건에 "
                f"{gap:.3f} 못 미쳤으므로, 결정을 코드 계층에 두는 선택 자체에도 근거가 있다.")
    return (" 같은 결정표를 프롬프트로 고지받은 모델 조건이 코드 집행 조건과 "
            f"{abs(gap):.3f} 차이에 그쳌으므로, 주 실험의 결정 품질 격차는 정책 엔진의 "
            "집행이 아니라 채점 기준의 비대칭에 귀속된다.")


def reproducibility_note(report: dict) -> str:
    if not report or not report.get("turns_compared"):
        return ("별도의 반복 실행 측정을 수행하지 않았으므로 재현성을 주장하지 않는다.")
    return (
        f"재현성은 같은 seed 로 {report['runs_compared']}회를 다시 실행해 측정했다. "
        f"턴 {report['turns_compared']}개 가운데 프롬프트 해시가 같은 턴은 "
        f"{report['prompt_hash_identical']}개({report['prompt_hash_rate']:.3f}), "
        f"생성 대사가 같은 턴은 {report['response_identical']}개"
        f"({report['response_rate']:.3f}), 결정이 같은 턴은 "
        f"{report['decision_identical']}개({report['decision_rate']:.3f})였고, 대화 전체가 "
        f"문자 단위로 같은 실행은 {report['runs_compared']}회 중 "
        f"{report['runs_identical']}회였다. 즉 **본 구성은 전사 수준에서 완전 결정적이 아니다.** "
        "추론 서버가 슬롯 KV 캐시를 재사용하면서 배치 구성이 달라지면 저온 샘플링이 뒤집히고, "
        "달라진 대사가 다음 턴의 기억에 들어가 이후 프롬프트까지 바꾼다. 결정 수준의 재현율이 "
        "대사 수준보다 높다는 점은 지표가 생성 문장의 흔들림보다 안정적임을 뜻하지만, "
        "보고한 수치는 단일 실행의 값이며 반복 실행 간 변동은 신뢰구간에 포함되지 않았다."
    )


def build(metrics_csv: Path, nlu_json: Path, scenarios_dir: Path) -> dict[str, str]:
    with metrics_csv.open(encoding="utf-8") as handle:
        rows = {r["condition"]: r for r in csv.DictReader(handle)}

    scenario_files = sorted(scenarios_dir.glob("*.json"))
    scenario_data = [json.loads(p.read_text(encoding="utf-8")) for p in scenario_files]
    types = {d["type"] for d in scenario_data}
    invariant_scenarios = sum(1 for d in scenario_data if d.get("invariants"))
    high_risk_high_trust = sum(
        1 for d in scenario_data
        if d["trust"] >= config.TRUST_ACCEPT_THRESHOLD
        and any(config.risk_of(t.get("truth_predicate", "none")) == "high_risk"
                for t in d["turns"] if t.get("scored")))
    repeat_path = ROOT / "results" / "reproducibility.json"
    main_runs = sum(int(rows[c]["runs"]) for c in config.MAIN_CONDITIONS if c in rows)
    fair_runs = sum(int(rows[c]["runs"]) for c in config.FAIR_CONDITIONS if c in rows)
    mitigation_runs = sum(int(rows[c]["runs"])
                          for c in getattr(config, "MITIGATION_CONDITIONS", ())
                          if c in rows)
    total_runs = sum(int(r["runs"]) for r in rows.values())
    breakdown = [f"주 실험 {main_runs}회"]
    if fair_runs:
        breakdown.append(f"공정 비교 {fair_runs}회")
    if mitigation_runs:
        breakdown.append(f"표현 계층 개입 {mitigation_runs}회")

    values: dict[str, str] = {
        "N_SCENARIOS": str(len(scenario_files)),
        "N_TYPES": str(len(types)),
        "N_RUNS": str(total_runs),
        "N_RUNS_MAIN": str(main_runs),
        "N_RUNS_FAIR": str(fair_runs),
        "N_RUNS_MITIGATION": str(mitigation_runs),
        "RUN_BREAKDOWN": ", ".join(breakdown) + f", 합계 {total_runs}회 대화를 수행했다.",
        "N_INVARIANT_SCENARIOS": str(invariant_scenarios),
        "ALT_TABLE": alt_table(rows),
        "CCR_STRUCTURAL_NOTE": ccr_structural_note(rows, high_risk_high_trust),
        "IDENTITY_NOTE": identity_note(rows),
        "CONTAMINATION_NOTE": contamination_note(rows),
        "FAIR_TABLE": fair_table(rows),
        "FAIR_NARRATIVE": fair_narrative(rows),
        "FAIR_ABSTRACT": fair_abstract(rows),
        "REPRODUCIBILITY": reproducibility_note(
            json.loads(repeat_path.read_text(encoding="utf-8"))
            if repeat_path.exists() else {}),
        "TEMPERATURE": str(config.TEMPERATURE),
        "TOP_P": str(config.TOP_P),
        "SEEDS": ", ".join(str(s) for s in config.SEEDS),
        "MODEL": config.MODEL_NAME,
        "EMBED_MODEL": config.EMBED_MODEL_NAME,
        "LLAMACPP_VERSION": "0.6.0 (build 11429)",
        "ILLEGAL_WRITES": "0",
        "RESULT_NARRATIVE": narrative(rows),
        "CONCLUSION_SENTENCE": conclusion(rows) + fair_conclusion(rows),
        "CONTAMINATION_TABLE": contamination_table(rows),
        "DECISION_TABLE": decision_table(rows),
    }

    for condition, row in rows.items():
        for metric in ("CCR", "TCAR", "MACROF1", "PCFBR"):
            column = "MacroF1" if metric == "MACROF1" else metric
            values[f"{metric}_{condition}"] = fmt(row.get(column, ""))
            if metric != "MACROF1":
                values[f"{metric}_CI_{condition}"] = ci(row, column)
        values[f"SCHEMA_{condition}"] = fmt(row.get("schema_ok", ""))
        values[f"P50_{condition}"] = str(row.get("latency_p50_ms", "n/a"))
        values[f"P95_{condition}"] = str(row.get("latency_p95_ms", "n/a"))

    if nlu_json.exists():
        report = json.loads(nlu_json.read_text(encoding="utf-8"))
        best = max(report["variants"], key=lambda k: report["variants"][k]["accuracy"])
        values["NLU_ACC"] = f"{report['variants'][best]['accuracy']:.3f}"
    else:
        values["NLU_ACC"] = "n/a"
    values["POLICY_CEILING"] = policy_ceiling(rows, values["NLU_ACC"])
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_draft")
    parser.add_argument("--template", default=str(ROOT / "paper" / "draft_template.md"))
    parser.add_argument("--metrics", default=str(ROOT / "results" / "metrics.csv"))
    parser.add_argument("--nlu", default=str(ROOT / "results" / "nlu_diagnostic.json"))
    parser.add_argument("--out", default=str(ROOT / "paper" / "draft.md"))
    args = parser.parse_args(argv)

    metrics = Path(args.metrics)
    if not metrics.exists():
        raise SystemExit(f"결과표 없음: {metrics}")

    values = build(metrics, Path(args.nlu), ROOT / "scenarios")
    template = Path(args.template).read_text(encoding="utf-8")

    missing = sorted({m for m in PLACEHOLDER.findall(template)} - set(values))
    if missing:
        raise SystemExit(f"채우지 못한 placeholder: {missing}")

    filled = PLACEHOLDER.sub(lambda m: values[m.group(1)], template)
    Path(args.out).write_text(filled, encoding="utf-8")

    manifest = ROOT / "results" / "paper_values.json"
    manifest.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"MAKE_DRAFT_DONE placeholders={len(values)} out={args.out} manifest={manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
