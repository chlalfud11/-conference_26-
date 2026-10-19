from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PENDING = "draft_pending_user_approval"
APPROVED = "approved"


def scenario_files(ids: list[str]) -> list[Path]:
    if not ids:
        return sorted(HERE.glob("*.json"))
    paths = [HERE / f"{scenario_id}.json" for scenario_id in ids]
    missing = [str(p.name) for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"없는 시나리오: {', '.join(missing)}")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="approve",
        description="시나리오 승인 상태를 바꾼다. ID 를 비우면 18개 전부에 적용한다.",
    )
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--revert", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)

    paths = scenario_files(args.ids)

    if args.list:
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            print(f"{data['scenario_id']:<8} {data.get('status', 'final')}")
        pending = sum(
            json.loads(p.read_text(encoding="utf-8")).get("status") == PENDING
            for p in paths
        )
        print(f"APPROVE_LIST total={len(paths)} pending={pending}")
        return 0

    status = PENDING if args.revert else APPROVED
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = status
        if args.revert:
            data.pop("approved_on", None)
        else:
            data["approved_on"] = date.today().isoformat()
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{data['scenario_id']:<8} {status}")

    print(f"APPROVE_DONE count={len(paths)} status={status}")
    print("검토 문서 갱신: python3 scenarios/render_review.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
