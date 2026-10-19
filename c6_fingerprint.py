from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def canonical(obj: object) -> object:
    if isinstance(obj, (set, frozenset)):
        return sorted(canonical(v) for v in obj)
    if isinstance(obj, dict):
        return {str(k): canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [canonical(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def sha(obj: object) -> str:
    blob = json.dumps(canonical(obj), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="판정 기준값의 해시 지문을 찍는다. 작업 전·후 동일 스크립트로 두 번 실행해 "
        "_ALL 값이 같은지 대조하면 사후 튜닝 여부가 가린다.")
    parser.add_argument("label", help="지문 시점 라벨 (예: before, after)")
    args = parser.parse_args()

    from npc import config

    items: dict[str, object] = {}
    for name in ("TRUST_ACCEPT_THRESHOLD", "HIGH_RISK_PREDICATES"):
        items[name] = getattr(config, name, "<MISSING>")

    items["expected_decision_src"] = inspect.getsource(config.expected_decision)

    trust, forbidden, turn_specs = {}, {}, {}
    for path in sorted((ROOT / "scenarios").glob("S*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sid = data.get("scenario_id", path.stem)
        trust[sid] = data.get("trust")
        forbidden[sid] = [t.get("forbidden_assertions") for t in data.get("turns", [])]
        turn_specs[sid] = [
            (t.get("truth_predicate"), t.get("evidence"), t.get("scored"),
             t.get("expected_decision"), t.get("action_depends_on_claim"))
            for t in data.get("turns", [])
        ]
    items["scenario_trust"] = trust
    items["forbidden_assertions"] = forbidden
    items["scenario_turn_specs"] = turn_specs

    pat_turns = sum(1 for pats in forbidden.values() for p in pats if p)
    uniq = len({p for pats in forbidden.values() for lst in pats if lst for p in lst})
    print(f"시나리오 {len(trust)}개 / 금지표현 보유 턴 {pat_turns}개 / 고유 정귀식 {uniq}개")

    out = {k: sha(v) for k, v in items.items()}
    out["_ALL"] = sha(out)
    dest = ROOT / "logs" / f"c6_fingerprint_{args.label}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for k, v in out.items():
        print(f"{k:24s} {v}")
    print(f"\n기록: {dest}")
    if "<MISSING>" in str(items.values()):
        print("경고: 누락된 기준값이 있다")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
