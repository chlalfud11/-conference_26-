"""M1P4 중단 재개. 봉인된 run_dialogue_v2 를 같은 순서로 호출하되 runs.jsonl 에 없는 run_id 만 실행한다.

봉인 파일(ulw_policy_v2_run.py 등)은 수정하지 않는다. 시작 전 봉인 해시를 대조하고,
중단·재개 사실을 logs/policy_v2/resume_receipt.json 에 남긴다.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

from npc import config
from ulw_policy_v2_run import load_scenarios, run_dialogue_v2

CP = Path(__file__).parent
OUT = CP / "logs/policy_v2/runs.jsonl"
FREEZE = CP / "logs/policy_v2/preregistration_freeze.json"
RECEIPT = CP / "logs/policy_v2/resume_receipt.json"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


if __name__ == "__main__":
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    bad = [s for s, h in freeze["source_hashes"].items()
           if hashlib.sha256((CP / s).read_bytes()).hexdigest() != h]
    if bad:
        raise SystemExit(f"seal mismatch: {bad}")

    scenarios = {}
    for d in ("scenarios", "scenarios_adversarial"):
        scenarios.update(load_scenarios(CP / d))
    planned = [(sid, seed) for sid in sorted(scenarios) for seed in config.SEEDS]
    if len(planned) != freeze["planned_runs"]:
        raise SystemExit(f"planned {len(planned)} != frozen {freeze['planned_runs']}")

    done = [json.loads(line)["run_id"] for line in OUT.read_text(encoding="utf-8").splitlines()]
    if len(done) != len(set(done)):
        raise SystemExit("duplicate run_id in runs.jsonl")
    missing = [(sid, seed) for sid, seed in planned if f"{sid}__M1P4__s{seed}" not in set(done)]

    receipt = {
        "reason": "추론 세션 종료로 run 프로세스와 llama-server 가 함께 중단됨. 결과 열람 없이 남은 run 만 재개.",
        "rows_before_resume": len(done),
        "runs_sha256_before_resume": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "missing_run_ids": [f"{s}__M1P4__s{k}" for s, k in missing],
        "resume_started_utc": now(),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(OUT, "a", encoding="utf-8") as f:
        for sid, seed in missing:
            print(f"Running {sid}__M1P4__s{seed}...", flush=True)
            f.write(run_dialogue_v2(scenarios[sid], seed).to_json() + "\n")
            f.flush()

    rows = [json.loads(line)["run_id"] for line in OUT.read_text(encoding="utf-8").splitlines()]
    receipt.update(resume_finished_utc=now(), rows_after_resume=len(rows),
                   unique_after_resume=len(set(rows)),
                   complete=sorted(rows) == sorted(f"{s}__M1P4__s{k}" for s, k in planned))
    RECEIPT.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
