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

from m1p2g_check import digest
from npc import config, llm, runner
from npc.engine import GameEngine
from npc.speech import POLICY_LINES, TEMPLATES, SpeechPlan

SNAPSHOT = config.ROOT / "logs" / "m1p3_frozen.json"


def audit_runs(records: list[dict]) -> dict:
    total = replay_matches = 0
    original_chat = llm.chat
    for run in records:
        with (config.ROOT / "scenarios" / f"{run['scenario_id']}.json").open(
            encoding="utf-8",
        ) as handle:
            scenario = json.load(handle)
        engine = GameEngine()
        try:
            engine.reset(scenario.get("initial_facts"))
            for turn, spec in zip(run["turns"], scenario["turns"], strict=True):
                assert turn["output_actor"] == "engine_renderer"
                assert isinstance(turn["raw_response"], str)
                assert turn["response_schema_ok"]
                system = json.loads(turn["prompt"])[0]["content"]
                ground = json.loads(system.split("[엔진 근거]\n", 1)[1].splitlines()[0])
                assert ground["world_truth"] == engine.world()
                assert ground["world_truth_source"] == "game_engine"
                inputs = ground["policy_inputs"]
                assert inputs["evidence"] == turn["evidence"] == spec.get("evidence", "none")
                assert inputs["evidence_verified"] == (turn["evidence"] == "verified")
                assert inputs["claim_predicate"] == turn["nlu_predicate"]
                assert inputs["claim_object"] == (turn["nlu"].get("claim_object") or "")
                assert inputs["risk"] == config.risk_of(turn["nlu_predicate"])
                assert inputs["trust"] == run["trust"]
                assert inputs["contradicts_state"] == spec.get("contradicts_state", False)
                assert inputs["evidence_trust_contradiction_source"] == "scenario_fixture"
                assert turn["decision"] == config.expected_decision(
                    inputs["risk"], turn["evidence"], run["trust"],
                    inputs["contradicts_state"],
                )
                assert "truth_predicate" not in ground and "expected_decision" not in ground
                purchase = None
                if action := spec.get("action"):
                    purchase = engine.buy(turn["turn"], action["item"], action["quantity"])
                    assert turn["action_result"] == {
                        "ok": purchase.ok, "reason": purchase.reason,
                    }
                plan = SpeechPlan(**turn["output_plan"])
                assert plan.template_id in TEMPLATES
                policy_key = turn["decision"]
                if policy_key == "accept_as_belief":
                    policy_key = (
                        "accept_verified" if turn["evidence"] == "verified"
                        else "accept_unverified"
                    )
                if plan.template_id == "purchase_completed":
                    assert purchase is not None and purchase.ok
                    expected_values = {
                        key: purchase.payload[key]
                        for key in ("item", "quantity", "total_price")
                    }
                    assert plan.values == expected_values
                    assert plan.sources == {key: "buy_skill" for key in expected_values}
                    assert plan.policy_key is None
                elif plan.template_id.startswith("buy_"):
                    assert purchase is not None and not purchase.ok
                    assert plan.template_id == f"buy_{purchase.reason}"
                    assert plan.values == {} and plan.policy_key is None
                    assert plan.sources == {"template_id": "buy_skill"}
                elif plan.template_id == "stock_and_policy":
                    item = plan.values["item"]
                    assert item in config.PRICES
                    assert plan.values == {
                        "item": item, "stock": engine.fact(f"shop.stock.{item}"),
                        "reserved": engine.fact(f"shop.reserved.{item}"),
                        "unit_price": config.PRICES[item],
                    }
                    assert plan.policy_key == policy_key
                    assert plan.sources == {
                        "item": "price_table", "stock": "game_engine",
                        "reserved": "game_engine", "unit_price": "price_table",
                        "policy_key": "policy_engine",
                    }
                elif plan.template_id == "catalog":
                    assert plan.values == {"items": ", ".join(config.PRICES)}
                    assert plan.sources == {"items": "price_table"}
                    assert plan.policy_key is None
                elif plan.template_id in ("greeting", "farewell"):
                    assert plan.values == {} and plan.policy_key is None
                    assert plan.sources == {"template_id": "dialogue_act"}
                else:
                    assert plan.template_id == policy_key
                    assert plan.values == {} and plan.policy_key is None
                    assert plan.sources == {"template_id": "policy_engine"}
                values = dict(plan.values)
                if plan.policy_key is not None:
                    values["policy_line"] = POLICY_LINES[plan.policy_key]
                assert turn["response"] == TEMPLATES[plan.template_id].format_map(values)
                total += 1
            assert engine.world() == run["final_world"]
        finally:
            engine.close()

        turn_index, nlu_call = 0, True

        def changed_candidate_chat(
            messages: list[dict], seed: int, max_tokens: int = config.MAX_TOKENS,
            json_schema: dict | None = None,
        ) -> llm.Completion:
            nonlocal turn_index, nlu_call
            if nlu_call:
                parsed = run["turns"][turn_index]["nlu"]
                nlu_call = False
            else:
                parsed = {"utterance": "__UNTRUSTED_COUNTERFACTUAL_CANDIDATE__"}
                nlu_call = True
                turn_index += 1
            return llm.Completion(
                text=json.dumps(parsed, ensure_ascii=False), parsed=parsed,
                latency_ms=0, prompt_tokens=0, completion_tokens=0, schema_ok=True,
            )

        llm.chat = changed_candidate_chat
        try:
            replay = runner.run_dialogue(scenario, "M1P3", run["seed"])
        finally:
            llm.chat = original_chat
        assert turn_index == len(run["turns"])
        assert replay.final_world == run["final_world"]
        for actual, changed in zip(run["turns"], replay.turns, strict=True):
            assert actual["prompt_hash"] == changed.prompt_hash
            assert actual["response"] == changed.response
            assert actual["output_plan"] == changed.output_plan
            replay_matches += 1
    return {
        "runs": len(records), "turns": total, "fact_and_template_mismatches": 0,
        "counterfactual_candidate_prompt_matches": replay_matches,
        "counterfactual_scope": "Recorded NLU held fixed; all model candidates replaced.",
        "pass": total == replay_matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze", "check", "smoke", "audit"))
    args = parser.parse_args()
    if args.mode in ("smoke", "audit"):
        path = config.ROOT / "logs" / (
            "m1p3_smoke.jsonl" if args.mode == "smoke" else "runs.jsonl"
        )
        with path.open(encoding="utf-8") as handle:
            records = [
                run for line in handle if line.strip()
                if (run := json.loads(line))["condition"] == "M1P3"
            ]
        assert len(records) == (2 if args.mode == "smoke" else 54)
        result = audit_runs(records)
        assert result["pass"]
        (config.ROOT / "logs" / f"m1p3_{args.mode}_audit.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False))
        print(f"M1P3_{args.mode.upper()}_PASS")
        return 0

    criteria_label = "m1p3_before" if args.mode == "freeze" else "m1p3_after"
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
    assert len(records) == len({run["run_id"] for run in records})
    match args.mode:
        case "freeze":
            assert not SNAPSHOT.exists(), "The pre-inference snapshot must not be overwritten."
            assert len(records) == 378 and len(metrics) == 7
            sources = sorted({
                *config.ROOT.joinpath("npc").glob("*.py"),
                *config.ROOT.joinpath("scenarios").glob("*.json"),
                *config.ROOT.joinpath("tests").glob("*.py"),
                config.ROOT / "c6_fingerprint.py",
                config.ROOT / "m1p3_check.py",
                config.ROOT / "m1p3_analysis.py",
                config.ROOT / "m1p2_prompt_replay.py",
                config.ROOT / "docs" / "M1P3_실험계획.md",
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
                "criteria": criteria, "baseline_metrics": metrics,
                "speech_templates": TEMPLATES,
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
                "a6249e2b02f75e712b8541fdc74fc8d8649b6d900ae8037cee7f7688fb8c0369"
            )
            (config.ROOT / "results" / "metrics_pre_m1p3.csv").write_bytes(
                (config.ROOT / "results" / "metrics.csv").read_bytes(),
            )
            SNAPSHOT.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print("M1P3_FREEZE_PASS", snapshot["created_at"])
            print("Protected original records:", len(records))
            print("Frozen sources:", len(sources), "; models:", len(models))
        case "check":
            with SNAPSHOT.open(encoding="utf-8") as handle:
                snapshot = json.load(handle)
            for path, expected in {**snapshot["sources"], **snapshot["models"]}.items():
                assert digest(config.ROOT / path) == expected, path
            assert criteria == snapshot["criteria"]
            assert TEMPLATES == snapshot["speech_templates"]
            prefix = b"".join(lines[:snapshot["original_records"]])
            assert hashlib.sha256(prefix).hexdigest() == snapshot["original_log_sha256"]
            for condition, row in snapshot["baseline_metrics"].items():
                assert metrics[condition] == row, condition
            counts = Counter(run["condition"] for run in records)
            assert len(records) == 432 and len(metrics) == len(counts) == 8
            assert all(count == 54 for count in counts.values())
            print("M1P3_INTEGRITY_PASS")
            print("432 unique records; 8 conditions; 54 records per condition")
            print("Frozen source/model/scenario/evaluation/template hashes unchanged")
            print("Original 378-line log prefix and all seven prior metric rows unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
