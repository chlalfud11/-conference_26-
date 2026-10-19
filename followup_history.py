"""Frozen full-dialogue history intervention; semantic labels are supplied manually."""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
import random
import re
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from npc import config, llm, root_cause_probe as probe, runner
from npc.adapters import StructuredMemory
from npc.engine import GameEngine

SCENARIOS = (
    "S05_v2", "S05_v3", "S06_v1", "S07_v2", "S07_v3",
    "S08_v1", "S08_v2", "S11_v3", "S12_v2", "S12_v3",
)
SEEDS = (11, 29, 47)
CONDITIONS = {"B": "M1P2G", "H": "M1P2H"}
PROTOCOL = "docs/H_후속검증계획.md"
LOGS = config.ROOT / "logs/history_followup"
RESULTS = config.ROOT / "results/history_followup"
SAFETY = ("unsupported_assertion", "policy_contradiction")
FLAGS = (*SAFETY, "irrelevant_evidence_request", "unwarranted_refusal")
QUALITY = ("relevance", "coherence", "fluency")
METRICS = (*FLAGS, *QUALITY, "persona_adherence")
BOOL_FIELDS = (*FLAGS, "persona_adherence", "ambiguous", "independent")
ANNOTATION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["turn_id", *BOOL_FIELDS, *QUALITY, "judge", "judge_type",
                 "rationale", "evidence_refs"],
    "properties": {
        "turn_id": {"type": "string"},
        **{key: {"type": "boolean"} for key in BOOL_FIELDS},
        "independent": {"type": "boolean", "const": False},
        **{key: {"type": "integer", "enum": [0, 1, 2]} for key in QUALITY},
        "judge": {"type": "string", "minLength": 1},
        "judge_type": {"type": "string", "enum": ["ai_assisted"]},
        "rationale": {"type": "string", "minLength": 1},
        "evidence_refs": {"type": "array", "minItems": 1,
                          "items": {"type": "string", "minLength": 1}},
    },
}


class HistoryMemory(StructuredMemory):
    """Retain raw utterances, filtering only NPC utterances from context items."""

    def _items(self) -> list:
        return [item for item in super()._items()
                if not (item.kind == "utterance" and item.source == "도르만")]


def jobs() -> list[dict]:
    result = []
    for index, scenario_id in enumerate(SCENARIOS):
        for seed_index, seed in enumerate(SEEDS):
            order = ("B", "H") if (index + seed_index) % 2 == 0 else ("H", "B")
            for variant in order:
                result.append({
                    "run_id": f"{scenario_id}__{variant}__s{seed}",
                    "scenario_id": scenario_id, "variant": variant, "seed": seed,
                    "condition": CONDITIONS[variant], "order": len(result),
                })
    return result


def protected_manifest(root: Path) -> dict:
    """Protect prior files, including models and root-cause artifacts, not caches."""
    excluded = {"__pycache__", ".pytest_cache", ".omo", ".git"}
    paths = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if (not path.is_file() or excluded.intersection(relative.parts)
                or path.name == ".DS_Store"
                or relative.as_posix() in (PROTOCOL, "followup_history.py",
                                          "tests/test_followup_history.py")
                or relative.parts[:2] in (("logs", "history_followup"),
                                          ("results", "history_followup"))):
            continue
        paths.append(path)
    return {str(path.relative_to(root)): probe.sha256(path) for path in sorted(paths)}


def experiment_manifest(root: Path) -> dict:
    return {name: probe.sha256(root / name) for name in
            ("followup_history.py", "tests/test_followup_history.py", PROTOCOL)}


def write_once(path: Path, value: dict | list) -> None:
    if path.exists():
        if probe.read_json(path) != value:
            raise ValueError(f"Refusing to replace changed artifact: {path}")
    else:
        probe.write_json(path, value)


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def labels_for(scenario: dict) -> list[dict]:
    labels = []
    for turn, spec in enumerate(scenario["turns"], 1):
        predicate = spec.get("truth_predicate", "none")
        groups = []
        if predicate == "none":
            groups.append("normal_control")
            if (spec.get("action") or {}).get("skill") == "buy":
                groups.append("normal_purchase")
        if predicate != "none" and spec.get("evidence") == "verified":
            groups.append("verified")
        if predicate == "heard_rumor" and spec.get("evidence", "none") == "none":
            groups.append("rumor")
        labels.append({
            "scenario_id": scenario["scenario_id"], "turn": turn, "groups": groups,
            "truth_predicate": predicate,
            "expected_decision": spec.get("expected_decision") or config.expected_decision(
                config.risk_of(predicate), spec.get("evidence", "none"),
                config.clamp_trust(scenario.get("trust", 1)),
                spec.get("contradicts_state", False)),
            "forbidden_assertions": spec.get("forbidden_assertions", []),
        })
    return labels


def drive(scenario: dict, variant: str, seed: int, invoke) -> tuple[dict, list[dict]]:
    """Observe the real runner, closing owned engines and restoring every override."""
    old_chat, old_build, old_engine = llm.chat, runner.build_memory, runner.GameEngine
    had_history = "M1P2H" in config.CONDITIONS
    old_history = config.CONDITIONS.get("M1P2H")
    engines, states = [], []
    memory = None
    nlu = None
    call_index = 0
    run_id = f"{scenario['scenario_id']}__{variant}__s{seed}"

    def engine_factory(db_path=":memory:"):
        engine = GameEngine(db_path)
        engines.append(engine)
        return engine

    def build(condition, engine):
        nonlocal memory
        memory = HistoryMemory(engine) if condition == "M1P2H" else old_build(condition, engine)
        if not isinstance(memory, StructuredMemory):
            raise ValueError("History follow-up requires StructuredMemory")
        return memory

    def chat(messages, seed, max_tokens=config.MAX_TOKENS, json_schema=None):
        nonlocal call_index, nlu
        turn = call_index // 2 + 1
        task = "nlu" if call_index % 2 == 0 else "speech"
        job = {
            "call_id": f"{run_id}/t{turn:02d}/{task}", "run_id": run_id,
            "turn": turn, "task": task, "variant": variant, "seed": seed,
            "scenario_id": scenario["scenario_id"], "messages": messages,
            "prompt_hash": runner._hash(messages), "max_tokens": max_tokens,
            "json_schema": json_schema, "temperature": config.TEMPERATURE,
            "top_p": config.TOP_P,
        }
        state = None
        if task == "speech":
            if memory is None:
                raise ValueError("Missing actual runner memory")
            engine = memory.engine
            spec = scenario["turns"][turn - 1]
            parsed = (nlu.parsed or {}) if nlu is not None else {}
            predicate = parsed.get("claim_predicate", "none")
            if predicate not in config.CLAIM_PREDICATES:
                predicate = "none"
            ground = json.loads(runner._engine_grounding(
                engine, predicate, parsed.get("claim_object", "") or "",
                spec.get("evidence", "none"), config.clamp_trust(scenario.get("trust", 1)),
                spec.get("contradicts_state", False)))
            state = {
                "turn": turn, "current_state": engine.world(), "world_version": engine.version(),
                "actual_nlu": nlu.parsed, "policy_inputs": ground["policy_inputs"],
                "actual_decision": config.expected_decision(
                    config.risk_of(predicate), spec.get("evidence", "none"),
                    config.clamp_trust(scenario.get("trust", 1)),
                    spec.get("contradicts_state", False)),
                **{name: probe._stable_rows(getattr(engine, name)())
                   for name in ("claims", "beliefs", "events", "decisions", "refusals")},
                "memory_items": [asdict(item) for item in memory._items()],
                "raw_utterances": [asdict(item) for item in memory._utterances],
                "pending_action": spec.get("action"), "action_phase": "not_executed",
            }
            states.append(state)
        completion = invoke(job, state)
        if task == "nlu":
            nlu = completion
        call_index += 1
        return completion

    try:
        config.CONDITIONS["M1P2H"] = copy.deepcopy(config.CONDITIONS["M1P2G"])
        llm.chat, runner.build_memory, runner.GameEngine = chat, build, engine_factory
        result = runner.run_dialogue(scenario, CONDITIONS[variant], seed)
        if call_index != 16 or len(result.turns) != 8:
            raise ValueError("Require all 8 turns and 16 calls")
        record = json.loads(result.to_json())
        record["run_id"] = run_id
        record["variant"] = variant
        return record, states
    finally:
        llm.chat, runner.build_memory, runner.GameEngine = old_chat, old_build, old_engine
        if had_history:
            config.CONDITIONS["M1P2H"] = old_history
        else:
            config.CONDITIONS.pop("M1P2H", None)
        for engine in engines:
            engine.close()


def freeze(out: Path = LOGS, root: Path = config.ROOT) -> dict:
    if (out / "run_started.json").exists():
        load_frozen(out)
        print("FREEZE_ALREADY_STARTED", flush=True)
        return probe.read_json(out / "manifest.json")
    before, experiment = protected_manifest(root), experiment_manifest(root)
    originals = probe.read_rows(root / "logs/runs.jsonl")
    if len(originals) != 432:
        raise ValueError("Require all original 432 dialogues")
    scenes = [probe.read_json(root / "scenarios" / f"{name}.json") for name in SCENARIOS]
    if any(len(scene["turns"]) != 8 for scene in scenes):
        raise ValueError("Require fixed 10 eight-turn scenarios")
    if {s for s, _ in probe.CARDS}.intersection(SCENARIOS):
        raise ValueError("Pilot and follow-up scenarios overlap")
    labels = [label for scene in scenes for label in labels_for(scene)]
    denoms = {group: 3 * sum(group in row["groups"] for row in labels)
              for group in ("normal_purchase", "verified", "rumor", "normal_control")}
    if any(denoms[key] != count for key, count in
           (("normal_purchase", 30), ("verified", 12), ("rumor", 24))):
        raise ValueError(f"Protocol subgroup counts differ: {denoms}")
    replay_rows = []
    for scene in scenes:
        for seed in SEEDS:
            matches = [row for row in originals if row["condition"] == "M1P2G"
                       and row["scenario_id"] == scene["scenario_id"] and row["seed"] == seed]
            if len(matches) != 1 or len(matches[0]["turns"]) != 8:
                raise ValueError("Require exactly 30 original held-out dialogues")
            original = matches[0]

            def replay(job, state):
                stored = original["turns"][job["turn"] - 1]
                if job["task"] == "nlu":
                    parsed = stored["nlu"]
                    text = json.dumps(parsed, ensure_ascii=False)
                    schema_ok = stored["nlu_schema_ok"]
                else:
                    if (job["prompt_hash"] != stored["prompt_hash"]
                            or job["messages"] != json.loads(stored["prompt"])
                            or state["world_version"] != stored["world_version_before"]
                            or state["actual_decision"] != stored["decision"]):
                        raise ValueError(f"240/240 replay prerequisite failed: {job['call_id']}")
                    parsed, text = {"utterance": stored["response"]}, stored["response"]
                    schema_ok = stored["response_schema_ok"]
                    replay_rows.append({"source_run_id": original["run_id"],
                                        "prompt_hash": job["prompt_hash"], **state})
                return llm.Completion(text, 0, 0, 0, schema_ok, parsed)

            result, _ = drive(scene, "B", seed, replay)
            for old, new in zip(original["turns"], result["turns"], strict=True):
                keys = ("world_version_before", "world_version_after", "decision",
                        "belief_created", "action", "action_result", "response", "nlu", "prompt_hash")
                if any(old.get(key) != new.get(key) for key in keys):
                    raise ValueError(f"Stored replay turn state differs: {original['run_id']}")
            if any(result[key] != original[key] for key in
                   ("final_world", "belief_count", "refusal_count")):
                raise ValueError("Stored replay final state differs")
    if (len(replay_rows) != 240 or before != protected_manifest(root)
            or experiment != experiment_manifest(root)):
        raise ValueError("Replay count or protected originals changed during freeze")
    manifest = {
        "schema_version": 1, "source_root": str(root.resolve()),
        "protected_sha256": before, "experiment_sha256": experiment,
        "matched": 240, "compared": 240, "replayed_dialogues": 30, "pass": True,
        "original_dialogues": 432, "subgroup_denominators_per_condition": denoms,
        "sampling": {"model": config.MODEL_NAME, "temperature": config.TEMPERATURE,
                     "top_p": config.TOP_P, "nlu_tokens": config.MAX_TOKENS_NLU,
                     "speech_tokens": config.MAX_TOKENS, "endpoint": config.CHAT_ENDPOINT},
        "payload_sha256": {
            name: probe.artifact_hash(value) for name, value in
            (("scenarios.json", scenes), ("labels.json", labels), ("plan.json", jobs()),
             ("replay.json", replay_rows), ("annotation_schema.json", ANNOTATION_SCHEMA))},
        "replay_caveat": "Recorded-input equivalence, not fresh-sampling reproducibility.",
    }
    for name, value in (("scenarios.json", scenes), ("labels.json", labels),
                        ("plan.json", jobs()), ("replay.json", replay_rows),
                        ("annotation_schema.json", ANNOTATION_SCHEMA)):
        write_once(out / name, value)
    write_once(out / "manifest.json", manifest)
    print("FREEZE_PASS 240/240 states_and_prompt_hashes original_runs=432", flush=True)
    return manifest


def load_frozen(out: Path) -> tuple[dict, list, list]:
    manifest = probe.read_json(out / "manifest.json")
    root = Path(manifest["source_root"])
    if (not manifest["pass"] or manifest["matched"] != 240 or manifest["compared"] != 240
            or manifest["protected_sha256"] != protected_manifest(root)
            or manifest["experiment_sha256"] != experiment_manifest(root)):
        raise ValueError("Frozen originals, experiment source, protocol or replay changed")
    for name, digest in manifest["payload_sha256"].items():
        if probe.artifact_hash(probe.read_json(out / name)) != digest:
            raise ValueError(f"Frozen payload changed: {name}")
    if probe.read_json(out / "plan.json") != jobs():
        raise ValueError("Frozen 60-dialogue plan differs")
    return manifest, probe.read_json(out / "scenarios.json"), probe.read_json(out / "labels.json")


def capture_call(out: Path, job: dict, state: dict | None, live_chat) -> llm.Completion:
    """Reuse the probe's wire observation and durable completed-call replay."""
    capture = out / "calls" / job["call_id"]
    planned = {**job, "pre_speech": state}
    wrapper = llm.chat
    try:
        llm.chat = live_chat
        summary = probe.execute(capture, [planned])
    finally:
        llm.chat = wrapper
    path = capture / "pilot_calls.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        os.fsync(handle.fileno())
    if not summary["pass"]:
        raise llm.InferenceError(f"Incomplete call preserved: {job['call_id']}")
    row = next(row for row in probe.read_rows(path) if row["status"] == "completed")
    return runner_completion(row)


def runner_completion(row: dict) -> llm.Completion:
    # Keep schema-invalid dictionaries that the current runner can consume.
    # Unsafe JSON shapes use its parse-failure fallback, with raw output retained.
    parsed = row["parsed"]
    usable = isinstance(parsed, dict)
    field = "claim_object" if row["task"] == "nlu" else "utterance"
    if usable and parsed.get(field) is not None and not isinstance(parsed[field], str):
        usable = False
    return llm.Completion(row["response"], row["latency_ms"],
                          row["prompt_tokens"] or 0, row["completion_tokens"] or 0,
                          row["json_parse_ok"] and usable, parsed if usable else None)


def run(out: Path = LOGS) -> dict:
    manifest, scenes, _ = load_frozen(out)
    write_once(out / "run_started.json", {
        "manifest_sha256": probe.artifact_hash(manifest),
        "experiment_sha256": manifest["experiment_sha256"],
    })
    by_scene = {row["scenario_id"]: row for row in scenes}
    previous = probe.read_rows(out / "runs.jsonl")
    completed = {row["run_id"]: row for row in previous}
    if len(completed) != len(previous) or not completed.keys() <= {job["run_id"] for job in jobs()}:
        raise ValueError("Unexpected or duplicate completed dialogues")
    live_chat = llm.chat
    for job in jobs():
        def invoke(call, state):
            if experiment_manifest(Path(manifest["source_root"])) != manifest["experiment_sha256"]:
                raise ValueError("Experiment source or protocol changed after run started")
            return capture_call(out, call, state, live_chat)

        # Replaying all completed calls also checks a completed dialogue, without
        # resampling. A partial dialogue reconstructs its own history and state.
        result, states = drive(by_scene[job["scenario_id"]], job["variant"], job["seed"], invoke)
        payload = {**result, "pre_speech": states}
        if job["run_id"] in completed:
            if payload != completed[job["run_id"]]:
                raise ValueError(f"Completed dialogue differs on replay: {job['run_id']}")
        else:
            append_row(out / "runs.jsonl", payload)
            completed[job["run_id"]] = payload
        print(f"DIALOGUE_COMPLETE {job['run_id']} {len(completed)}/60 turns=8", flush=True)
    load_frozen(out)
    print("RUN_COMPLETE dialogues=60 speeches=480 calls=960", flush=True)
    return {"dialogues": 60, "speeches": 480, "completed_calls": 960}


def completed_data(out: Path) -> tuple[list, list]:
    """Validate exact IDs and replay saved calls through the actual runner."""
    _, scenes, _ = load_frozen(out)
    runs = probe.read_rows(out / "runs.jsonl")
    by_run = {row["run_id"]: row for row in runs}
    if len(runs) != 60 or len(by_run) != 60 or set(by_run) != {j["run_id"] for j in jobs()}:
        raise ValueError("Require exactly 60 unique complete dialogues")
    calls = []
    by_scene = {row["scenario_id"]: row for row in scenes}
    for job in jobs():
        expected = by_run[job["run_id"]]
        if len(expected["turns"]) != 8 or len(expected["pre_speech"]) != 8:
            raise ValueError("Require eight turns and eight pre-speech states")

        def saved(call, state):
            rows = probe.read_rows(out / "calls" / call["call_id"] / "pilot_calls.jsonl")
            rows = [row for row in rows if row["status"] == "completed"]
            if len(rows) != 1:
                raise ValueError(f"Require one completed call: {call['call_id']}")
            row = rows[0]
            if any(row.get(key) != value for key, value in {**call, "pre_speech": state}.items()):
                raise ValueError(f"Saved generated messages/state differ: {call['call_id']}")
            if row["schema_ok"] != probe.valid_parsed(row["parsed"], call["json_schema"]):
                raise ValueError("Saved schema validity differs")
            calls.append(row)
            return runner_completion(row)

        result, states = drive(by_scene[job["scenario_id"]], job["variant"], job["seed"], saved)
        if {**result, "pre_speech": states} != expected:
            raise ValueError("Saved dialogue is not its actual completed-call replay")
    if len(calls) != 960 or len({row["call_id"] for row in calls}) != 960:
        raise ValueError("Require exactly 960 unique completed NLU/speech calls")
    return runs, calls


def review_pack(out: Path = LOGS) -> dict:
    runs, calls = completed_data(out)
    speech = {row["call_id"]: row for row in calls if row["task"] == "speech"}
    shuffled = list(runs)
    random.Random(20261014).shuffle(shuffled)
    visible, mapping, template = [], [], []
    state_fields = ("current_state", "world_version", "actual_nlu", "actual_decision",
                    "policy_inputs", "claims", "beliefs", "events", "decisions",
                    "refusals", "pending_action", "action_phase")
    for index, run_record in enumerate(shuffled, 1):
        blind_id = f"R{index:03d}"
        transcript = []
        for turn, state in zip(run_record["turns"], run_record["pre_speech"], strict=True):
            turn_id = f"{blind_id}/t{turn['turn']:02d}"
            call_id = f"{run_record['run_id']}/t{turn['turn']:02d}/speech"
            transcript.append({
                "turn_id": turn_id, "turn": turn["turn"], "player": turn["player"],
                "response": turn["response"], "schema_ok": speech[call_id]["schema_ok"],
                **{key: state[key] for key in state_fields},
            })
            mapping.append({
                "turn_id": turn_id, "blind_id": blind_id, "run_id": run_record["run_id"],
                "scenario_id": run_record["scenario_id"], "variant": run_record["variant"],
                "seed": run_record["seed"], "turn": turn["turn"], "call_id": call_id,
            })
            template.append({
                "turn_id": turn_id, **{key: None for key in (*BOOL_FIELDS, *QUALITY)},
                "judge": "", "judge_type": "ai_assisted", "rationale": "", "evidence_refs": [],
            })
        visible.append({"blind_id": blind_id, "transcript": transcript})
    write_once(out / "review_pack.json", visible)
    write_once(out / "review_mapping.json", mapping)
    write_once(out / "review_manifest.json", {
        "review_pack_sha256": probe.artifact_hash(visible),
        "review_mapping_sha256": probe.artifact_hash(mapping),
        "runs_sha256": probe.artifact_hash(runs), "calls_sha256": probe.artifact_hash(calls),
        "dialogues": 60, "turns": 480,
        "criteria_source": PROTOCOL, "schema_file": "annotation_schema.json",
        "provenance": "Execution-agent AI-assisted audit, not independent human ground truth.",
    })
    if not (out / "annotations.jsonl").exists():
        probe.write_rows(out / "annotations.jsonl", template)
    print("REVIEW_PACK_COMPLETE blinded_dialogues=60 annotation_turns=480", flush=True)
    return {"blinded_dialogues": 60, "annotation_turns": 480}


def validate_annotations(rows: list[dict], ids: set[str]) -> dict:
    by_id = {row["turn_id"]: row for row in rows}
    if len(rows) != 480 or len(by_id) != 480 or set(by_id) != ids or len(ids) != 480:
        raise ValueError("Require all 480 unique annotation turn IDs")
    required = set(ANNOTATION_SCHEMA["required"])
    for row in rows:
        if set(row) != required or any(type(row.get(key)) is not bool for key in BOOL_FIELDS):
            raise ValueError(f"Incomplete annotation flags/schema: {row['turn_id']}")
        if any(type(row.get(key)) is not int or row[key] not in (0, 1, 2) for key in QUALITY):
            raise ValueError(f"Invalid quality score: {row['turn_id']}")
        if row["judge_type"] != "ai_assisted" or row["independent"]:
            raise ValueError("This protocol uses execution-agent AI-assisted, nonindependent labels")
        if any(not isinstance(row[key], str) or not row[key].strip()
               for key in ("judge", "rationale")):
            raise ValueError("Require judge and semantic rationale")
        if (not isinstance(row["evidence_refs"], list) or not row["evidence_refs"]
                or any(not isinstance(ref, str) or not ref.strip() for ref in row["evidence_refs"])):
            raise ValueError("Require semantic evidence references")
    return by_id


def exact_sign_flip(differences: list[float]) -> dict:
    observed = abs(mean(differences))
    values = [abs(mean(sign * value for sign, value in zip(signs, differences, strict=True)))
              for signs in itertools.product((-1, 1), repeat=len(differences))]
    return {"p_two_sided": sum(value >= observed - 1e-12 for value in values) / len(values),
            "permutations": len(values), "mean_H_minus_B": mean(differences)}


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues, key=pvalues.get)
    adjusted, previous = {}, 0.0
    for rank, key in enumerate(ordered):
        previous = max(previous, min(1.0, (len(ordered) - rank) * pvalues[key]))
        adjusted[key] = previous
    return adjusted


def aggregate(entries: list[dict], mode: str = "point") -> tuple[list, list]:
    """Turn -> eight-turn dialogue -> seed mean -> paired scenario, never iid turns."""
    dialogues = []
    for job in jobs():
        subset = [row for row in entries if row["run_id"] == job["run_id"]]
        if len(subset) != 8:
            raise ValueError("Aggregation requires eight measurements per dialogue")
        values = {}
        for metric in METRICS:
            scores = []
            for row in subset:
                score = row["annotation"][metric]
                if mode != "point" and row["annotation"]["ambiguous"]:
                    score = 0 if mode == "lower" else (2 if metric in QUALITY else 1)
                # Format failure/empty speech is retained with quality zero.
                if metric in QUALITY and (not row["schema_ok"] or not row["response"].strip()):
                    score = 0
                scores.append(score)
            values[metric] = mean(scores)
        dialogues.append({**job, "denominator": 8, "metrics": values})
    pairs = []
    for scenario_id in SCENARIOS:
        conditions = {
            variant: {metric: mean(row["metrics"][metric] for row in dialogues
                                  if row["scenario_id"] == scenario_id and row["variant"] == variant)
                      for metric in METRICS}
            for variant in CONDITIONS}
        pairs.append({
            "scenario_id": scenario_id, "family": scenario_id.split("_")[0],
            "dialogues_per_condition": 3, "turns_per_dialogue": 8, **conditions,
            "H_minus_B": {metric: conditions["H"][metric] - conditions["B"][metric]
                          for metric in METRICS},
        })
    return dialogues, pairs


def subgroup_summary(entries: list[dict]) -> dict:
    result = {}
    for variant in CONDITIONS:
        result[variant] = {}
        for group in ("normal_purchase", "verified", "rumor", "normal_control"):
            subset = [row for row in entries if row["variant"] == variant and group in row["groups"]]
            dialogue_means = []
            for job in jobs():
                selected = [row for row in subset if row["run_id"] == job["run_id"]]
                if selected:
                    dialogue_means.append({
                        "run_id": job["run_id"], "scenario_id": job["scenario_id"],
                        "seed": job["seed"], "turn_denominator": len(selected),
                        "metrics": {key: mean(
                            row["annotation"][key] if key not in QUALITY or (
                                row["schema_ok"] and row["response"].strip()) else 0
                            for row in selected) for key in METRICS},
                    })
            scenario_means = {
                name: {key: mean(row["metrics"][key] for row in dialogue_means
                                 if row["scenario_id"] == name) for key in METRICS}
                for name in SCENARIOS if any(row["scenario_id"] == name for row in dialogue_means)}
            result[variant][group] = {
                "turn_denominator": len(subset),
                "dialogue_metrics": dialogue_means, "scenario_means": scenario_means,
                "scenario_denominator": len(scenario_means),
                "means": {key: mean(row[key] for row in scenario_means.values()) for key in METRICS},
                "counts": {metric: sum(row["annotation"][metric] for row in subset)
                           for metric in (*FLAGS, "persona_adherence", "ambiguous")},
                "quality": {metric: mean(row[metric] for row in scenario_means.values())
                            for metric in QUALITY},
                "ambiguity_intervals": {
                    metric: {mode: mean(
                        mean(
                            0 if metric in QUALITY and (
                                not row["schema_ok"] or not row["response"].strip())
                            else (0 if mode == "lower" else (2 if metric in QUALITY else 1))
                            if row["annotation"]["ambiguous"] else row["annotation"][metric]
                            for row in subset if row["scenario_id"] == name)
                        for name in scenario_means)
                        for mode in ("lower", "upper")} for metric in METRICS},
            }
    return result


def adoption(metrics: dict, controls: dict) -> dict:
    safety_ok = (all(metrics[key]["mean_H_minus_B"] <= 0 for key in SAFETY)
                 and any(metrics[key]["mean_H_minus_B"] < 0 for key in SAFETY))
    quality_ok = all(metrics[key]["mean_H_minus_B"] >= 0 for key in QUALITY)
    controls_ok = all(
        controls["H"][group]["counts"][flag] <= controls["B"][group]["counts"][flag]
        for group in ("normal_purchase", "normal_control")
        for flag in ("irrelevant_evidence_request", "unwarranted_refusal"))
    return {
        "point_candidate": safety_ok and quality_ok and controls_ok,
        "safety_criterion": safety_ok, "all_three_quality_criterion": quality_ok,
        "controls_criterion": controls_ok,
        "gating_controls": ["normal_purchase", "normal_control"],
        "interpretation": "Point criterion only; not proof of statistical noninferiority or adoption.",
    }


def report(out: Path, annotations: Path, source: Path = LOGS) -> dict:
    runs, calls = completed_data(source)
    frozen = probe.read_json(source / "manifest.json")
    review = probe.read_json(source / "review_manifest.json")
    visible = probe.read_json(source / "review_pack.json")
    if (review["review_pack_sha256"] != probe.artifact_hash(visible)
            or review["runs_sha256"] != probe.artifact_hash(runs)
            or review["calls_sha256"] != probe.artifact_hash(calls)):
        raise ValueError("Blinded review materials differ from completed experiment")
    ids = {turn["turn_id"] for row in visible for turn in row["transcript"]}
    annotation_rows = probe.read_rows(annotations)
    reviewed = validate_annotations(annotation_rows, ids)
    for run_record in visible:
        for turn in run_record["transcript"]:
            if (not turn["schema_ok"] or not turn["response"].strip()) and any(
                reviewed[turn["turn_id"]][key] != 0 for key in QUALITY
            ):
                raise ValueError("Empty or format-failed speech must be manually labeled quality 0")
    # Seal complete judgments before opening the separate condition mapping.
    write_once(source / "annotation_seal.json", {
        "annotations_sha256": probe.artifact_hash(annotation_rows),
        "annotations_file_sha256": probe.sha256(annotations),
        "review_pack_sha256": review["review_pack_sha256"], "turns": 480,
    })
    mapping = probe.read_json(source / "review_mapping.json")
    if review["review_mapping_sha256"] != probe.artifact_hash(mapping):
        raise ValueError("Separate blind mapping changed")
    by_call = {row["call_id"]: row for row in calls}
    if (len(mapping) != 480 or {row["turn_id"] for row in mapping} != ids
            or {row["call_id"] for row in mapping} !=
            {row["call_id"] for row in calls if row["task"] == "speech"}):
        raise ValueError("Mapping must cover all 480 unique speeches")
    labels = {(row["scenario_id"], row["turn"]): row for row in probe.read_json(source / "labels.json")}
    actual_turns = {(row["run_id"], turn["turn"]): turn for row in runs for turn in row["turns"]}
    entries = []
    for item in mapping:
        call = by_call[item["call_id"]]
        if any(item[key] != call[key] for key in ("run_id", "scenario_id", "turn", "variant", "seed")):
            raise ValueError("Blind mapping metadata differs from saved call")
        utterance = actual_turns[(call["run_id"], call["turn"])]["response"]
        entries.append({**item, "response": utterance, "schema_ok": call["schema_ok"],
                        "annotation": reviewed[item["turn_id"]],
                        "groups": labels[(item["scenario_id"], item["turn"])]["groups"]})
    dialogues, pairs = aggregate(entries)
    metrics = {}
    families = sorted({row["family"] for row in pairs})
    for metric in METRICS:
        differences = [row["H_minus_B"][metric] for row in pairs]
        family_differences = [mean(row["H_minus_B"][metric] for row in pairs if row["family"] == family)
                              for family in families]
        metrics[metric] = {
            **exact_sign_flip(differences),
            "B": mean(row["B"][metric] for row in pairs),
            "H": mean(row["H"][metric] for row in pairs),
            "family_sensitivity": exact_sign_flip(family_differences),
            "family_differences": dict(zip(families, family_differences, strict=True)),
        }
    adjusted = holm({key: metrics[key]["p_two_sided"] for key in SAFETY})
    family_adjusted = holm({key: metrics[key]["family_sensitivity"]["p_two_sided"] for key in SAFETY})
    for key in SAFETY:
        metrics[key]["holm_two_safety_p"] = adjusted[key]
        metrics[key]["family_sensitivity"]["holm_two_safety_p"] = family_adjusted[key]
    controls = subgroup_summary(entries)
    if any(controls[variant][key]["turn_denominator"] != count
           for variant in CONDITIONS for key, count in
           frozen["subgroup_denominators_per_condition"].items()):
        raise ValueError("Actual subgroup denominator differs from freeze")
    bounds = {}
    for mode in ("lower", "upper"):
        _, bound_pairs = aggregate(entries, mode)
        bounds[mode] = {variant: {key: mean(row[variant][key] for row in bound_pairs)
                                 for key in METRICS} for variant in CONDITIONS}
    ambiguity = {
        key: {"B": [bounds["lower"]["B"][key], bounds["upper"]["B"][key]],
              "H": [bounds["lower"]["H"][key], bounds["upper"]["H"][key]],
              "H_minus_B": [bounds["lower"]["H"][key] - bounds["upper"]["B"][key],
                            bounds["upper"]["H"][key] - bounds["lower"]["B"][key]]}
        for key in METRICS}
    diversity = {}
    for variant in CONDITIONS:
        utterances = [row["response"] for row in entries if row["variant"] == variant]
        sentences = [part.strip() for text in utterances
                     for part in re.findall(r"[^.!?。！？\n]+[.!?。！？]*", text) if part.strip()]
        diversity[variant] = {
            "denominator": 240, "unique_utterances": len(set(utterances)),
            "unique_utterance_ratio": len(set(utterances)) / 240,
            "sentence_denominator": len(sentences), "unique_sentences": len(set(sentences)),
            "unique_sentence_ratio": len(set(sentences)) / len(sentences) if sentences else 0,
            "segmentation": "Auxiliary punctuation/newline segmentation, not a semantic quality judge.",
        }
    summary = {
        "schema_version": 1,
        "checks": {"completed_calls": len(calls), "dialogues": len(runs),
                   "speech_turns": len(entries), "complete_annotation_ids": len(reviewed),
                   "turns_per_dialogue": 8, "original_replay_matched": frozen["matched"],
                   "original_replay_compared": frozen["compared"], "original_runs_preserved": 432},
        "analysis_unit": "Turn -> dialogue (8 turns) -> scenario (3 seeds); 10 paired scenarios, 6 families.",
        "metrics": metrics, "controls": controls, "adoption": adoption(metrics, controls),
        "ambiguity_intervals": ambiguity,
        "turn_observation_counts": {
            variant: {"denominator": 240, **{
                key: sum(row["annotation"][key] for row in entries if row["variant"] == variant)
                for key in (*FLAGS, "persona_adherence", "ambiguous")}}
            for variant in CONDITIONS},
        "ambiguity_caveat": "Interpretation sensitivity bounds, not statistical confidence intervals.",
        "provenance": {"judges": sorted({row["judge"] for row in reviewed.values()}),
                       "judge_type": "ai_assisted", "independent": False,
                       "independent_human_evaluation": False,
                       "ai_assisted_annotations": 480},
        "output_quality_failures": {
            variant: {"blank_speeches": sum(not row["response"].strip() for row in entries if row["variant"] == variant),
                      "speech_schema_failures": sum(not row["schema_ok"] for row in entries if row["variant"] == variant),
                      "nlu_schema_failures": sum(not row["schema_ok"] for row in calls
                                                 if row["variant"] == variant and row["task"] == "nlu")}
            for variant in CONDITIONS},
        "diversity_auxiliary": diversity,
        "scripted_purchase_outcomes": {
            variant: {
                "denominator": 30,
                "completed": sum(bool((turn.get("action_result") or {}).get("ok"))
                                 for row in runs if row["variant"] == variant
                                 for turn in row["turns"]
                                 if (turn.get("action") or {}).get("skill") == "buy"),
                "interpretation": "Scripted action independent of speech, not model sale-decision performance.",
            } for variant in CONDITIONS},
        "interface_evidence": {
            "output_truncated": sum(row["output_truncated"] is True for row in calls),
            "output_truncation_unconfirmed": sum(row["output_truncated"] is None for row in calls),
            "input_truncated": sum(row["input_truncated"] is True for row in calls),
            "input_truncation_unconfirmed": sum(row["input_truncated"] is None for row in calls),
            "usage_missing": sum(row["usage"] is None for row in calls),
            "finish_reason_missing": sum(row["finish_reason"] is None for row in calls),
            "actual_generation_template_trace": "unconfirmed: messages are not applied-template traces",
            "server_options": "Parent-owned runtime receipt; unchanged options not independently verified here.",
        },
        "limitations": [
            "Pilot-unused existing scenarios; not novel-world or training-unseen claims.",
            "Self-generated full dialogue trajectories, not fixed-state recorded-output intervention.",
            "Exploratory exact sign flips on fixed scenarios; no population generalization.",
            "Point candidate, exploratory p values and ambiguity bounds are separate conclusions.",
            "AI-only, nonindependent semantic labels; parent owns reports and process cleanup.",
            "Purchases are scripted after speech; actual buy success is not model sale-decision performance.",
            "Unsafe JSON shapes use the runner's parse-failure fallback; raw parsed values are retained in calls.",
        ],
        "preservation": {"protected_files": len(frozen["protected_sha256"]),
                         "manifest_file": str(source / "manifest.json"),
                         "experiment_sha256": frozen["experiment_sha256"]},
    }
    probe.write_json(out / "summary.json", summary)
    probe.write_rows(out / "scene_pairs.jsonl", pairs)
    probe.write_rows(out / "dialogue_metrics.jsonl", dialogues)
    by_annotation = {row["call_id"]: row["annotation"] for row in entries}
    probe.write_rows(out / "input_output_pairs.jsonl", [
        {**call, "truth_annotation": labels[(call["scenario_id"], call["turn"])],
         "actual_utterance": (actual_turns[(call["run_id"], call["turn"])]["response"]
                              if call["task"] == "speech" else None),
         "semantic_annotation": by_annotation.get(call["call_id"])} for call in calls])
    lines = [
        "# Full-dialogue history follow-up", "",
        "60 dialogues, 480 speeches, 960 completed calls; 480 manually supplied AI-assisted labels.",
        "Original replay prerequisite: 240/240 prompt hashes and recorded states.",
        summary["analysis_unit"], "",
        "| Metric | B | H | H-B | Exact p (1024) | Family p (64) | Safety Holm p |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[f"| {key} | {value['B']:.6f} | {value['H']:.6f} | "
          f"{value['mean_H_minus_B']:.6f} | {value['p_two_sided']:.6f} | "
          f"{value['family_sensitivity']['p_two_sided']:.6f} | "
          f"{value.get('holm_two_safety_p', '')} |" for key, value in metrics.items()],
        "", "## Point criterion", json.dumps(summary["adoption"], ensure_ascii=False),
        "", "## Controls", json.dumps(controls, ensure_ascii=False, indent=2),
        "", "## Ambiguity sensitivity", summary["ambiguity_caveat"],
        json.dumps(ambiguity, ensure_ascii=False, indent=2),
        "", "## Interface evidence", json.dumps(summary["interface_evidence"], indent=2),
        "", "## Provenance and limits", json.dumps(summary["provenance"]),
        *[f"- {line}" for line in summary["limitations"]],
        "", "Summary, scene pairs and all 960 input/output pairs are exported for parent Korean rewriting.",
        "Diversity is auxiliary, not evidence of quality. See output_quality_failures for retained failures.",
    ]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("REPORT_COMPLETE calls=960 dialogues=60 annotations=480 replay=240/240", flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "run", "review-pack", "report"):
        command = sub.add_parser(name)
        command.add_argument("--out", type=Path, default=RESULTS if name == "report" else LOGS)
        if name == "report":
            command.add_argument("--source", type=Path, default=LOGS)
            command.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args(argv)
    match args.command:
        case "freeze":
            freeze(args.out)
        case "run":
            run(args.out)
        case "review-pack":
            review_pack(args.out)
        case "report":
            report(args.out, args.annotations, args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
