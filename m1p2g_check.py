from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from npc import config

SNAPSHOT = config.ROOT / "logs" / "m1p2g_frozen.json"
BASELINE_METRICS = config.ROOT / "results" / "metrics_pre_m1p2g.csv"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze", "check", "smoke"))
    args = parser.parse_args()
    if args.mode == "smoke":
        with (config.ROOT / "logs" / "m1p2g_smoke.jsonl").open(encoding="utf-8") as handle:
            smoke = [json.loads(line) for line in handle if line.strip()]
        assert len(smoke) == 2
        assert {run["scenario_id"] for run in smoke} == {"S05_v1", "S07_v1"}
        for run in smoke:
            assert run["condition"] == "M1P2G" and run["seed"] == 11
            for turn in run["turns"]:
                assert turn["decision_actor"] == "policy_engine"
                assert turn["nlu_schema_ok"] and turn["response_schema_ok"]
                system = json.loads(turn["prompt"])[0]["content"]
                ground = json.loads(system.split("[엔진 근거]\n", 1)[1].splitlines()[0])
                assert ground["world_truth_source"] == "game_engine"
                assert ground["policy_inputs"]["evidence"] == turn["evidence"]
                assert ground["policy_inputs"]["evidence_verified"] == (turn["evidence"] == "verified")
                assert ground["policy_inputs"]["evidence_trust_contradiction_source"] == "scenario_fixture"
                assert turn["decision"] == config.expected_decision(
                    ground["policy_inputs"]["risk"], turn["evidence"], run["trust"],
                    ground["policy_inputs"]["contradicts_state"],
                )
            print("SMOKE", run["run_id"], "policy inputs correctly sourced")
        rumor = next(run for run in smoke if run["scenario_id"] == "S07_v1")["turns"][1]
        assert rumor["evidence"] == "none"
        print("Unverified rumor decision:", rumor["decision"])
        print("M1P2G_SMOKE_PASS")
        return 0
    criteria_label = "m1p2g_before" if args.mode == "freeze" else "m1p2g_after"
    subprocess.run(
        [sys.executable, "c6_fingerprint.py", criteria_label],
        cwd=config.ROOT, check=True,
    )
    with (config.ROOT / "logs" / f"c6_fingerprint_{criteria_label}.json").open(
        encoding="utf-8",
    ) as handle:
        criteria = json.load(handle)
    with (config.ROOT / "logs" / "runs.jsonl").open("rb") as handle:
        lines = handle.readlines()
    records = [json.loads(line) for line in lines if line.strip()]
    with (config.ROOT / "results" / "metrics.csv").open(encoding="utf-8") as handle:
        metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    assert len(records) == len({r["run_id"] for r in records})
    match args.mode:
        case "freeze":
            assert not SNAPSHOT.exists(), "The pre-inference snapshot must not be overwritten."
            assert len(records) == 324 and len(metrics) == 6
            sources = sorted({
                *config.ROOT.joinpath("npc").glob("*.py"),
                *config.ROOT.joinpath("scenarios").glob("*.json"),
                *config.ROOT.joinpath("tests").glob("*.py"),
                config.ROOT / "m1p2g_check.py",
                config.ROOT / "m1p2g_analysis.py",
                config.ROOT / "m1p2_prompt_replay.py",
                config.ROOT / "docs" / "M1P2G_실험계획.md",
            })
            models = sorted(config.ROOT.joinpath("models").glob("*.gguf"))
            assert len(models) == 2
            snapshot = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(),
                "sources": {str(p.relative_to(config.ROOT)): digest(p) for p in sources},
                "models": {str(p.relative_to(config.ROOT)): digest(p) for p in models},
                "original_records": len(records),
                "original_log_sha256": hashlib.sha256(b"".join(lines)).hexdigest(),
                "criteria": criteria,
                "baseline_metrics": metrics,
                "model_parameters": {
                    "temperature": config.TEMPERATURE, "top_p": config.TOP_P,
                    "seeds": list(config.SEEDS), "context": config.CONTEXT_WINDOW,
                    "max_tokens": config.MAX_TOKENS,
                    "max_tokens_nlu": config.MAX_TOKENS_NLU,
                },
                "server_options": {
                    "chat": "--host 127.0.0.1 --port 8080 -c 4096 -ngl 99 --no-webui --jinja",
                    "embedding": "--host 127.0.0.1 --port 8081 --embedding --pooling cls -c 8192 -ngl 99 --no-webui",
                },
            }
            version = subprocess.run(
                ["llama-server", "--version"], capture_output=True, text=True, check=True,
            )
            snapshot["server_version"] = version.stdout + version.stderr
            assert snapshot["original_log_sha256"] == (
                "fca27a574b23ac6fb04271438329b541fe792b8a28bdd87d93ad001056437033"
            )
            BASELINE_METRICS.write_bytes((config.ROOT / "results" / "metrics.csv").read_bytes())
            SNAPSHOT.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print("M1P2G_FREEZE_PASS", snapshot["created_at"])
            print("Protected original records:", len(records))
            print("Frozen source files:", len(sources), "; model files:", len(models))
        case "check":
            with SNAPSHOT.open(encoding="utf-8") as handle:
                snapshot = json.load(handle)
            for path, expected in {**snapshot["sources"], **snapshot["models"]}.items():
                assert digest(config.ROOT / path) == expected, path
            assert criteria == snapshot["criteria"]
            prefix = b"".join(lines[:snapshot["original_records"]])
            assert hashlib.sha256(prefix).hexdigest() == snapshot["original_log_sha256"]
            for condition, row in snapshot["baseline_metrics"].items():
                assert metrics[condition] == row, condition
            counts = Counter(r["condition"] for r in records)
            assert len(records) == 378 and len(metrics) == len(counts) == 7
            assert all(count == 54 for count in counts.values())
            print("M1P2G_INTEGRITY_PASS")
            print("378 unique records; 7 conditions; 54 records per condition")
            print("Frozen source/model/scenario/evaluation hashes unchanged")
            print("Original 324-line log prefix and all prior metric columns unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
