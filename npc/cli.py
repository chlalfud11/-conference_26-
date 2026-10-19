from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import config, llm
from .runner import run_dialogue

_log_override = os.environ.get("NPC_RUNS_LOG")
LOG_FILE = (Path(_log_override) if _log_override
            else config.ROOT / "logs" / "runs.jsonl")


def scenario_paths() -> list[Path]:
    return sorted((config.ROOT / "scenarios").glob("*.json"))


def load_scenario(name: str) -> dict:
    path = config.ROOT / "scenarios" / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"시나리오 없음: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def completed_run_ids() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    done = set()
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            done.add(json.loads(line)["run_id"])
    return done


def require_servers() -> None:
    chat_ok, embed_ok = llm.server_ready()
    if not chat_ok:
        raise SystemExit(f"추론 서버 응답 없음: {config.CHAT_ENDPOINT}")
    if not embed_ok:
        raise SystemExit(f"임베딩 서버 응답 없음: {config.EMBED_ENDPOINT}")


def append_log(record) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(record.to_json() + "\n")


def print_transcript(record) -> None:
    spec = config.CONDITIONS[record.condition]
    print(f"\n=== {record.run_id}  [{spec['label']}]  trust={record.trust} ===")
    for turn in record.turns:
        mark = "·" if turn.decision == turn.expected_decision else "✗"
        print(f"\n[{turn.turn}] 손님: {turn.player}")
        print(f"     도르만: {turn.response}")
        print(f"     결정={turn.decision} (기대={turn.expected_decision}) {mark} "
              f"actor={turn.decision_actor} nlu={turn.nlu_predicate} "
              f"지연={turn.nlu_latency_ms + turn.response_latency_ms}ms")
        if turn.action_result:
            print(f"     거래: {turn.action} -> {turn.action_result}")
    print(f"\n믿음 {record.belief_count}건 | 엔진 거부 {record.refusal_count}건")
    print(f"예약 재고(달빛 잼): {record.final_world.get('shop.reserved.달빛 잼')} | "
          f"손님 인벤(달빛 잼): {record.final_world.get('player.inventory.달빛 잼')}")


def cmd_run(args: argparse.Namespace) -> int:
    require_servers()
    scenario = load_scenario(args.scenario)
    record = run_dialogue(scenario, args.condition, args.seed)
    append_log(record)
    print_transcript(record)
    print(f"\n로그 기록: {LOG_FILE}")
    return 0


def cmd_runall(args: argparse.Namespace) -> int:
    require_servers()
    scenarios = [json.loads(p.read_text(encoding="utf-8")) for p in scenario_paths()]
    conditions = args.conditions or list(config.CONDITIONS)
    seeds = args.seeds or list(config.SEEDS)
    done = completed_run_ids() if args.resume else set()

    planned = [(s, c, seed) for s in scenarios for c in conditions for seed in seeds]
    print(f"계획: 시나리오 {len(scenarios)} × 조건 {len(conditions)} × seed {len(seeds)} "
          f"= {len(planned)}회 (완료 {len(done)}건 건너뜀)", flush=True)

    started = time.perf_counter()
    executed = 0
    for scenario, condition, seed in planned:
        run_id = f"{scenario['scenario_id']}__{condition}__s{seed}"
        if run_id in done:
            continue
        record = run_dialogue(scenario, condition, seed)
        append_log(record)
        executed += 1
        elapsed = time.perf_counter() - started
        print(f"[{executed}] {run_id} 완료 ({elapsed:.0f}s 경과)", flush=True)
    print(f"RUNALL_DONE executed={executed} total_records={len(completed_run_ids())}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    for path in scenario_paths():
        data = json.loads(path.read_text(encoding="utf-8"))
        scored = sum(1 for t in data["turns"] if t.get("scored"))
        print(f"{data['scenario_id']:<10} {data['type']:<5} turns={len(data['turns'])} "
              f"scored={scored} trust={data.get('trust')} status={data.get('status', 'final')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="npc.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--condition", required=True, choices=list(config.CONDITIONS))
    run.add_argument("--scenario", required=True)
    run.add_argument("--seed", type=int, default=config.SEEDS[0])
    run.set_defaults(func=cmd_run)

    runall = sub.add_parser("runall")
    runall.add_argument("--conditions", nargs="*", choices=list(config.CONDITIONS))
    runall.add_argument("--seeds", nargs="*", type=int)
    runall.add_argument("--resume", action="store_true")
    runall.set_defaults(func=cmd_runall)

    listing = sub.add_parser("list")
    listing.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
