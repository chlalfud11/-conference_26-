from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .cli import load_scenario, require_servers
from .runner import run_dialogue


def stored_runs(log_path: Path) -> dict[tuple[str, str, int], dict]:
    out: dict[tuple[str, str, int], dict] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            out[(record["scenario_id"], record["condition"], record["seed"])] = record
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="npc.repeat_check")
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=config.SEEDS[0])
    parser.add_argument("--log", default=str(config.ROOT / "logs" / "runs.jsonl"))
    parser.add_argument("--out",
                        default=str(config.ROOT / "results" / "reproducibility.json"))
    parser.add_argument("--repeat-log",
                        default=str(config.ROOT / "logs" / "repeat.jsonl"))
    args = parser.parse_args(argv)

    require_servers()
    stored = stored_runs(Path(args.log))

    turns = prompt_same = decision_same = response_same = 0
    runs = runs_identical = 0
    records = []
    for name in args.scenarios:
        scenario = load_scenario(name)
        for condition in config.CONDITIONS:
            key = (name, condition, args.seed)
            if key not in stored:
                continue
            fresh = json.loads(run_dialogue(scenario, condition, args.seed).to_json())
            records.append(fresh)
            runs += 1
            identical = True
            for old, new in zip(stored[key]["turns"], fresh["turns"]):
                turns += 1
                same_prompt = old["prompt_hash"] == new["prompt_hash"]
                same_decision = old["decision"] == new["decision"]
                same_response = old["response"] == new["response"]
                prompt_same += int(same_prompt)
                decision_same += int(same_decision)
                response_same += int(same_response)
                identical = identical and same_prompt and same_decision and same_response
            runs_identical += int(identical)
            print(f"{name} {condition} s{args.seed}: identical={identical}", flush=True)

    report = {
        "runs_compared": runs,
        "runs_identical": runs_identical,
        "turns_compared": turns,
        "prompt_hash_identical": prompt_same,
        "decision_identical": decision_same,
        "response_identical": response_same,
        "prompt_hash_rate": round(prompt_same / turns, 4) if turns else 0.0,
        "decision_rate": round(decision_same / turns, 4) if turns else 0.0,
        "response_rate": round(response_same / turns, 4) if turns else 0.0,
    }
    Path(args.repeat_log).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8")
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print("REPEAT_CHECK_DONE " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
