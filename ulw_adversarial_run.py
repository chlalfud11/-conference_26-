#!/usr/bin/env python3
"""적대적 실험 실행기 — 사전등록 docs/ULW_정책검정_사전등록.md 집행.

`freeze` 가 먼저 실행되지 않으면 `run` 이 거부한다. 사전등록 해시 기록 시각이
첫 추론보다 앞선다는 것을 파일로 증명하기 위한 기계적 강제다.
기존 npc/ 는 한 줄도 수정하지 않고 run_dialogue 를 직접 호출하며,
원자료는 logs/adversarial/runs.jsonl 로 격리해 기존 432회를 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import time
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config, llm  # noqa: E402
from npc.runner import run_dialogue  # noqa: E402

SCEN_DIR = CP / "scenarios_adversarial"
LOG_DIR = CP / "logs" / "adversarial"
LOG_FILE = LOG_DIR / "runs.jsonl"
FREEZE = LOG_DIR / "preregistration_freeze.json"
PREREG = CP / "docs" / "ULW_정책검정_사전등록.md"
CONDITIONS = ("M0P0", "M1P0", "M1P1")

FROZEN_SOURCES = (
    "docs/ULW_정책검정_사전등록.md",
    "ulw_make_adversarial_scenarios.py",
    "ulw_adversarial_run.py",
    "ulw_adversarial_analysis.py",
    "ulw_policy_diagnostic.py",
    "tests/test_ulw_adversarial.py",
    "npc/config.py", "npc/eval.py", "npc/runner.py", "npc/adapters.py",
    "npc/llm.py", "npc/engine.py", "npc/speech.py",
    "logs/runs.jsonl", "results/metrics.csv",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def scenarios() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(SCEN_DIR.glob("*.json"))]


def completed() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    return {json.loads(line)["run_id"]
            for line in LOG_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}


def cmd_freeze(args: argparse.Namespace) -> int:
    if FREEZE.exists() and not args.force:
        print(f"이미 동결됨: {FREEZE}  (덮어쓰려면 --force, 단 추론 후 재동결은 금지)")
        return 1
    if not PREREG.exists():
        raise SystemExit(f"사전등록 문서 없음: {PREREG}")
    scen = scenarios()
    if len(scen) != 9:
        raise SystemExit(f"시나리오 9편이어야 한다. 현재 {len(scen)}편")

    payload = {
        "frozen_at_utc": utc_now(),
        "preregistration": str(PREREG.relative_to(CP)),
        "conditions": list(CONDITIONS),
        "seeds": list(config.SEEDS),
        "planned_runs": len(scen) * len(CONDITIONS) * len(config.SEEDS),
        "model": config.MODEL_NAME,
        "embed_model": config.EMBED_MODEL_NAME,
        "temperature": config.TEMPERATURE,
        "top_p": config.TOP_P,
        "trust_accept_threshold": config.TRUST_ACCEPT_THRESHOLD,
        "scenarios": {s["scenario_id"]: sha256(SCEN_DIR / f"{s['scenario_id']}.json")
                      for s in scen},
        "sources": {rel: sha256(CP / rel) for rel in FROZEN_SOURCES if (CP / rel).exists()},
        "first_inference_utc": None,
        "last_inference_utc": None,
        "stopping_rule": "81회 1회 실행. 결과를 근거로 seed·시나리오·조건을 추가하지 않는다.",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"동결 완료 {payload['frozen_at_utc']}")
    print(f"  시나리오 {len(payload['scenarios'])}편, 소스 {len(payload['sources'])}개")
    print(f"  계획 {payload['planned_runs']}회 = 시나리오 9 × 조건 {len(CONDITIONS)} × seed {len(config.SEEDS)}")
    print(f"  {FREEZE}")
    return 0


def cmd_verify(_: argparse.Namespace) -> int:
    if not FREEZE.exists():
        raise SystemExit(f"동결 파일 없음: {FREEZE}")
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    bad = []
    for rel, want in frozen["sources"].items():
        got = sha256(CP / rel) if (CP / rel).exists() else None
        if got != want:
            bad.append((rel, want[:12], (got or "MISSING")[:12]))
    for sid, want in frozen["scenarios"].items():
        got = sha256(SCEN_DIR / f"{sid}.json")
        if got != want:
            bad.append((sid, want[:12], got[:12]))
    print(f"동결 시각 : {frozen['frozen_at_utc']}")
    print(f"첫 추론    : {frozen['first_inference_utc']}")
    print(f"마지막 추론: {frozen['last_inference_utc']}")
    if frozen["first_inference_utc"]:
        ok = frozen["frozen_at_utc"] < frozen["first_inference_utc"]
        print(f"순서 증명  : 동결 < 첫 추론 = {ok}")
    print(f"지문 불일치: {bad if bad else '없음'}")
    return 1 if bad else 0


def cmd_run(args: argparse.Namespace) -> int:
    if not FREEZE.exists():
        raise SystemExit("사전등록이 동결되지 않았다. 먼저 `freeze` 를 실행한다.")
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    for sid, want in frozen["scenarios"].items():
        if sha256(SCEN_DIR / f"{sid}.json") != want:
            raise SystemExit(f"동결 후 시나리오가 변경됐다: {sid}")

    chat_ok, embed_ok = llm.server_ready()
    if not chat_ok:
        raise SystemExit(f"추론 서버 응답 없음: {config.CHAT_ENDPOINT}")
    if not embed_ok:
        raise SystemExit(f"임베딩 서버 응답 없음: {config.EMBED_ENDPOINT}")

    scen = scenarios()
    done = completed()
    planned = [(s, c, seed) for s in scen for c in CONDITIONS for seed in config.SEEDS]
    print(f"계획 {len(planned)}회 (완료 {len(done)}건 건너뜀)", flush=True)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    executed = 0
    for scenario, condition, seed in planned:
        run_id = f"{scenario['scenario_id']}__{condition}__s{seed}"
        if run_id in done:
            continue
        if frozen["first_inference_utc"] is None:
            frozen["first_inference_utc"] = utc_now()
            FREEZE.write_text(json.dumps(frozen, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        record = run_dialogue(scenario, condition, seed)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(record.to_json() + "\n")
        executed += 1
        print(f"[{executed}/{len(planned) - len(done)}] {run_id} "
              f"({time.perf_counter() - started:.0f}s)", flush=True)

    frozen["last_inference_utc"] = utc_now()
    FREEZE.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ADVERSARIAL_DONE executed={executed} total={len(completed())}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ulw_adversarial_run")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--force", action="store_true")
    f.set_defaults(func=cmd_freeze)
    sub.add_parser("verify").set_defaults(func=cmd_verify)
    sub.add_parser("run").set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
