from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CHECKS: list[tuple[str, str, list[str]]] = [
    ("수정1 CCR 기준① 구조적 한계",
     "§5.1에 기준①이 M1P1에서 설계상 0임과 기준① 제외 CCR 병기",
     [r"기준 ?①", r"설계상 0", r"기준 ?① ?을? ?제외하면 CCR", r"0\.\d{3} ?→ ?0\.\d{3}"]),
    ("수정2 표4 행 표기",
     "표 4의 기준① 행에 설계 보장, 기준③ 행에 미가동 표기",
     [r"①[^|\n]*설계 보장", r"③[^|\n]*미가동"]),
    ("수정3 Macro-F1 항등성",
     "정답 라벨과 M1P1 정책이 같은 함수, NLU 정답 턴 일치율, 비교 조건은 결정표 미수령",
     [r"같은 함수", r"101/101", r"결정표가 들어 ?있지 않다|결정표를 받지 못"]),
    ("수정4 5라벨 고정 분모",
     "표 3-1에 5라벨 고정 분모 Macro-F1 병기",
     [r"5라벨 고정", r"대체 보고 관례"]),
    ("수정5 오라클 입력 명시",
     "§4.1 verified·confidence 동시 제거, §4.3·§5.3 오라클 필드명",
     [r"`verified`·`confidence`", r"`evidence`", r"`trust`", r"`contradicts_state`",
      r"시나리오 오라클"]),
    ("6번 공정 비교 반영",
     "§5.5 공정 비교 절과 표 7, 사후 조정 없음 공개",
     [r"결정표를 모델에게 고지한 공정 비교", r"M0P0R", r"M1P0R",
      r"프롬프트의 순서·문구·길이를 조정하지 않았다"]),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="논문 초안에 감사 공개 항목 1~5와 공정 비교가 실제로 렌더됐는지 판정한다.")
    parser.add_argument("--draft", default=str(ROOT / "paper" / "draft.md"))
    args = parser.parse_args()

    text = Path(args.draft).read_text(encoding="utf-8")
    failed = 0
    for name, intent, patterns in CHECKS:
        misses = [p for p in patterns if not re.search(p, text)]
        status = "PASS" if not misses else "FAIL"
        failed += bool(misses)
        print(f"[{status}] {name} — {intent}")
        for pattern in misses:
            print(f"         미검출: {pattern}")

    print(f"\nC4_DISCLOSURE {'PASS' if not failed else 'FAIL'} "
          f"({len(CHECKS) - failed}/{len(CHECKS)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
