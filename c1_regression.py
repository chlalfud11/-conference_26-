from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONDITIONS = ("M0P0", "M1P0", "M1P1")


def load(path: str, scenario: str, seed: int) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    if not Path(path).exists():
        print(f"로그 없음: {path}")
        return out
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            rec = json.loads(line)
            if (rec["scenario_id"] == scenario and rec["seed"] == seed
                    and rec["condition"] in CONDITIONS):
                out[rec["condition"]] = {
                    t["turn"]: t["prompt_hash"] for t in rec["turns"]}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="기존 3조건의 프롬프트가 조건 추가 이후에도 바이트 단위로 같은지, "
                    "보존된 로그의 저장 해시와 재실행 해시를 턴별로 대조한다.")
    parser.add_argument("--baseline", default=str(ROOT / "logs" / "runs.jsonl"))
    parser.add_argument("--rerun", default=str(ROOT / "logs" / "c1_regression.jsonl"))
    parser.add_argument("--scenario", default="S05_v1")
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    base = load(args.baseline, args.scenario, args.seed)
    rerun = load(args.rerun, args.scenario, args.seed)

    total = matched = 0
    for condition in CONDITIONS:
        stored = base.get(condition, {})
        fresh = rerun.get(condition, {})
        if not stored:
            print(f"{condition}: 기준 레코드 없음")
        for turn in sorted(stored):
            total += 1
            got = fresh.get(turn)
            ok = stored[turn] == got
            matched += ok
            mark = "" if ok else "   <-- 불일치"
            print(f"{condition:5s} t{turn}  저장={stored[turn]}  재실행={got or '(없음)'}{mark}")

    print(f"\n일치 {matched}/{total} (기대 24/24)")
    ok = total == 24 and matched == 24
    print("C1_REGRESSION", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
