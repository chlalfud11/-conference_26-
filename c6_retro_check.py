from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="보존된 런 로그에 저장된 risk_truth·expected_decision 을 현재 기준값으로 "
                    "재계산해 대조한다. 전부 일치하면 그 런들이 기록된 이후 판정 기준이 "
                    "바뀌지 않았음이 소급 증명된다.")
    parser.add_argument("--runs", default=str(ROOT / "logs" / "runs.jsonl"))
    args = parser.parse_args()

    from npc import config

    scenarios = {}
    for path in sorted((ROOT / "scenarios").glob("S*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        scenarios[data.get("scenario_id", path.stem)] = data

    checked = collections.Counter()
    risk_bad, dec_bad = [], []

    with open(args.runs, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]

    for rec in records:
        spec = scenarios.get(rec["scenario_id"])
        if spec is None:
            checked["시나리오_없음"] += 1
            continue
        trust = rec["trust"]
        for turn in rec["turns"]:
            spec_turn = spec["turns"][turn["turn"] - 1]
            contradicts = spec_turn.get("contradicts_state", False)
            risk = config.risk_of(
                spec_turn.get("truth_predicate", turn.get("nlu_predicate", "none")))
            exp = spec_turn.get("expected_decision") or config.expected_decision(
                risk, turn["evidence"], trust, contradicts)

            checked[rec["condition"]] += 1
            if risk != turn["risk_truth"]:
                risk_bad.append((rec["run_id"], turn["turn"], risk, turn["risk_truth"]))
            if exp != turn["expected_decision"]:
                dec_bad.append(
                    (rec["run_id"], turn["turn"], exp, turn["expected_decision"]))

    total = sum(v for k, v in checked.items() if k != "시나리오_없음")
    print(f"레코드 {len(records)}개 / 검사한 턴 {total}개")
    print("조건별 턴:", dict(checked))
    print(f"risk_truth 불일치: {len(risk_bad)}")
    print(f"expected_decision 불일치: {len(dec_bad)}")
    for row in risk_bad[:5]:
        print("  risk:", row)
    for row in dec_bad[:5]:
        print("  dec :", row)

    ok = not risk_bad and not dec_bad
    print("\nC6_RETRO", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
