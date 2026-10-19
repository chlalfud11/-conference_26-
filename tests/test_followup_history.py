from __future__ import annotations

import copy
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

import followup_history as history
from npc import config, llm, root_cause_probe as probe, runner
from npc.adapters import StructuredMemory
from npc.engine import GameEngine

REAL_MANIFEST = history.protected_manifest


@pytest.fixture(scope="module")
def frozen(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("history-freeze")
    with pytest.MonkeyPatch.context() as patch:
        # Hash coverage is checked separately on a small real filesystem. The
        # replay fixture still uses the actual original logs, scenarios and code.
        patch.setattr(history, "protected_manifest", probe.source_manifest)
        patch.setattr(llm, "_post", lambda *args, **kwargs: pytest.fail("No inference during replay"))
        history.freeze(out)
        yield out


def wire_body(payload: dict) -> dict:
    schema = payload["response_format"]["json_schema"]["schema"]
    parsed = ({"intent": "other", "speech_act": "other", "claim_predicate": "none",
               "claim_object": "", "confidence": 0.9}
              if "intent" in schema["properties"] else {"utterance": "__NPC_OUTPUT__"})
    return {"choices": [{"message": {"content": json.dumps(parsed)}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 12}, "truncated": False}


@pytest.fixture(scope="module")
def completed(frozen: Path, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("history-completed") / "experiment"
    shutil.copytree(frozen, out)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(llm, "_post", lambda url, payload, timeout=180: wire_body(payload))
        history.run(out)
        history.review_pack(out)
    return out


def annotations_for(out: Path) -> list[dict]:
    rows = probe.read_rows(out / "annotations.jsonl")
    mapping = {row["turn_id"]: row for row in probe.read_json(out / "review_mapping.json")}
    for row in rows:
        row.update({key: False for key in history.BOOL_FIELDS})
        row.update({key: 2 for key in history.QUALITY})
        row.update(judge="fixture-executor", judge_type="ai_assisted", rationale="Synthetic audit",
                   evidence_refs=["transcript", "current_state"])
        row["unsupported_assertion"] = mapping[row["turn_id"]]["variant"] == "B"
    return rows


def test_fixed_dialogue_plan_and_balanced_order() -> None:
    planned = history.jobs()
    assert len(planned) == len({row["run_id"] for row in planned}) == 60
    assert {row["scenario_id"] for row in planned} == set(history.SCENARIOS)
    assert {row["seed"] for row in planned} == {11, 29, 47}
    assert [row["order"] for row in planned] == list(range(60))
    assert sum(row["variant"] == "B" for row in planned) == 30
    assert {tuple(row["variant"] for row in planned[index:index + 2])
            for index in range(0, 60, 2)} == {("B", "H"), ("H", "B")}
    assert not {name for name, _ in probe.CARDS}.intersection(history.SCENARIOS)


def test_history_filters_only_npc_utterances_and_preserves_raw_audit() -> None:
    engine = GameEngine()
    try:
        memory = history.HistoryMemory(engine)
        claim_id = engine.save_claim(1, "__CLAIM__", "heard_rumor", "__OBJECT__", "none")
        engine.record_decision(1, claim_id, "accept_as_belief", "policy_engine")
        assert engine.buy(2, "여행용 빵", 1).ok
        memory.remember(1, "손님", "__USER__")
        memory.remember(1, "도르만", "__NPC__")
        memory.remember(2, "another", "__OTHER__")
        original = StructuredMemory._items(memory)

        filtered = memory._items()

        assert filtered == [item for item in original
                            if not (item.kind == "utterance" and item.source == "도르만")]
        assert {"player_claim", "npc_belief", "committed_event", "utterance"} <= {
            item.kind for item in filtered}
        assert any(item.source == "도르만" for item in memory._utterances)
        assert "__NPC__" not in memory.context("", config.CONDITIONS["M1P2G"]["fields"])
        assert "__USER__" in memory.context("", config.CONDITIONS["M1P2G"]["fields"])
    finally:
        engine.close()


def test_freeze_matches_30_actual_original_dialogues_240_turns(frozen: Path) -> None:
    manifest, scenes, labels = history.load_frozen(frozen)
    replay = probe.read_json(frozen / "replay.json")
    assert manifest["matched"] == manifest["compared"] == len(replay) == 240
    assert manifest["replayed_dialogues"] == len({row["source_run_id"] for row in replay}) == 30
    assert manifest["original_dialogues"] == 432
    assert len(scenes) == 10 and len(labels) == 80
    assert manifest["subgroup_denominators_per_condition"] == {
        "normal_purchase": 30, "verified": 12, "rumor": 24, "normal_control": 120}
    purchase = next(row for row in replay if row["source_run_id"].startswith("S05_v2")
                    and row["turn"] == 6)
    assert purchase["current_state"]["player.inventory.여행용 빵"] == 0
    assert purchase["action_phase"] == "not_executed"
    assert all(row["turn_id"] < 6 for row in purchase["events"])
    assert not ({"truth_predicate", "expected_decision", "forbidden_assertions"} & purchase.keys())


def test_freeze_mismatch_writes_no_artifacts(frozen: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "_hash", lambda messages: "wrong-hash")
    with pytest.raises(ValueError, match="240/240"):
        history.freeze(tmp_path)
    assert not list(tmp_path.iterdir())


def test_protected_manifest_includes_all_prior_artifact_classes(tmp_path: Path) -> None:
    included = ("npc/engine.py", "tests/test_policy.py", "scenarios/S05_v2.json",
                "models/model.gguf", "results/metrics.csv", "paper/paper.pdf", "slides/slides.pdf",
                "logs/runs.jsonl", "logs/root_cause/pilot_calls.jsonl",
                "results/slm_root_cause/report.md", "prior.py")
    excluded = ("followup_history.py", "tests/test_followup_history.py", history.PROTOCOL,
                "logs/history_followup/calls.jsonl", "results/history_followup/report.md",
                "npc/__pycache__/engine.pyc")
    for name in (*included, *excluded):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    assert set(REAL_MANIFEST(tmp_path)) == set(included)


def test_drive_restores_all_overrides_and_closes_engine_on_exception(
    frozen: Path, monkeypatch,
) -> None:
    scene = probe.read_json(frozen / "scenarios.json")[0]
    engines = []
    def owned(db_path):
        engine = GameEngine(db_path)
        engines.append(engine)
        return engine
    monkeypatch.setattr(history, "GameEngine", owned)
    sentinel = {"__EXISTING__": True}
    monkeypatch.setitem(config.CONDITIONS, "M1P2H", sentinel)
    before = (llm.chat, runner.build_memory, runner.GameEngine)
    def fail(job, state):
        raise RuntimeError("test-interruption")

    with pytest.raises(RuntimeError, match="test-interruption"):
        history.drive(scene, "H", 11, fail)

    assert before == (llm.chat, runner.build_memory, runner.GameEngine)
    assert config.CONDITIONS["M1P2H"] is sentinel
    with pytest.raises(sqlite3.ProgrammingError):
        engines[0].conn.execute("SELECT 1")


def test_partial_resume_keeps_completed_malformed_and_checks_generated_messages(
    frozen: Path, tmp_path: Path, monkeypatch,
) -> None:
    scene = probe.read_json(frozen / "scenarios.json")[0]
    sent = []
    def post(url, payload, timeout=180):
        sent.append(payload)
        if len(sent) == 2:
            return {"choices": []}
        if len(sent) == 3:
            raise llm.InferenceError("transport-interruption")
        return wire_body(payload)
    monkeypatch.setattr(llm, "_post", post)
    live_chat = llm.chat
    def invoke(job, state):
        return history.capture_call(tmp_path, job, state, live_chat)
    with pytest.raises(llm.InferenceError, match="Incomplete"):
        history.drive(scene, "B", 11, invoke)
    result, states = history.drive(scene, "B", 11, invoke)
    assert len(sent) == 17  # 16 completed calls and one failed transport, never resampling.
    assert result["turns"][0]["response"] == ""
    assert len(states) == 8
    malformed_path = tmp_path / "calls/S05_v2__B__s11/t01/speech/pilot_calls.jsonl"
    malformed = probe.read_rows(malformed_path)
    assert len(malformed) == 1 and malformed[0]["status"] == "completed"
    assert malformed[0]["observation"]["raw_response"] == {"choices": []}
    assert malformed[0]["schema_ok"] is False
    assert states[1]["raw_utterances"][1]["source"] == "도르만"
    assert states[1]["raw_utterances"][1]["text"] == "도르만: "
    changed = copy.deepcopy(scene)
    changed["turns"][0]["player"] = "__CHANGED_INPUT__"
    with pytest.raises(ValueError, match="Resume plan differs"):
        history.drive(changed, "B", 11, invoke)
    assert len(sent) == 17


def test_safe_schema_invalid_dictionaries_keep_runner_behavior() -> None:
    row = {"response": "__TEXT__", "latency_ms": 0, "prompt_tokens": 1,
           "completion_tokens": 1, "json_parse_ok": True, "schema_ok": False,
           "task": "nlu", "parsed": {"claim_predicate": "heard_rumor", "claim_object": "wolf"}}
    assert history.runner_completion(row).parsed == row["parsed"]
    row["parsed"] = ["invalid shape"]
    assert history.runner_completion(row).parsed is None


def test_truth_labels_never_enter_actual_generated_messages(frozen: Path) -> None:
    scene = copy.deepcopy(probe.read_json(frozen / "scenarios.json")[0])
    scene["turns"][0].update(truth_predicate="__TRUTH_LABEL__",
                            expected_decision="__EXPECTED_LABEL__",
                            forbidden_assertions=["__REGEX_LABEL__"])
    messages = []
    def invoke(job, state):
        messages.extend(job["messages"])
        payload = {"response_format": {"json_schema": {"schema": job["json_schema"]}}}
        parsed = json.loads(wire_body(payload)["choices"][0]["message"]["content"])
        return llm.Completion(json.dumps(parsed), 0, 0, 0, True, parsed)

    record, states = history.drive(scene, "H", 11, invoke)

    assert record["turns"][0]["expected_decision"] == "__EXPECTED_LABEL__"
    assert states[0]["policy_inputs"]["claim_predicate"] == "none"
    assert all(token not in json.dumps(messages) for token in
               ("__TRUTH_LABEL__", "__EXPECTED_LABEL__", "__REGEX_LABEL__"))


def test_blinded_pack_contains_60_full_dialogues_and_no_model_metadata(completed: Path) -> None:
    visible = probe.read_json(completed / "review_pack.json")
    assert len(visible) == len({row["blind_id"] for row in visible}) == 60
    assert all(len(row["transcript"]) == 8 for row in visible)
    assert len({turn["turn_id"] for row in visible for turn in row["transcript"]}) == 480
    forbidden = {"variant", "condition", "seed", "run_id", "scenario_id", "messages",
                 "prompt_hash", "memory_items", "raw_utterances", "model"}
    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for nested in value.values():
                check(nested)
        elif isinstance(value, list):
            for nested in value:
                check(nested)
    check(visible)
    assert len(probe.read_rows(completed / "annotations.jsonl")) == 480


def test_all_completed_calls_replay_without_inference(completed: Path, monkeypatch) -> None:
    monkeypatch.setattr(llm, "_post", lambda *args, **kwargs: pytest.fail("Completed call rerun"))
    before = probe.read_rows(completed / "runs.jsonl")
    assert history.run(completed)["completed_calls"] == 960
    assert probe.read_rows(completed / "runs.jsonl") == before
    runs, calls = history.completed_data(completed)
    assert len(runs) == 60 and len(calls) == 960
    assert all(row["observation"]["request"]["temperature"] == 0.2 for row in calls)
    assert all(row["usage"]["prompt_tokens"] == 42 for row in calls)
    assert all(not ({"truth_predicate", "expected_decision", "forbidden_assertions"} &
                    row["observation"]["request"].keys()) for row in calls)


def test_frozen_payload_tampering_is_blocked(frozen: Path, tmp_path: Path) -> None:
    out = tmp_path / "changed"
    shutil.copytree(frozen, out)
    scenes = probe.read_json(out / "scenarios.json")
    scenes[0]["turns"][0]["player"] = "__TAMPERED__"
    probe.write_json(out / "scenarios.json", scenes)
    with pytest.raises(ValueError, match="Frozen payload"):
        history.load_frozen(out)


def test_experiment_or_protocol_change_blocks_resume(completed: Path, monkeypatch) -> None:
    monkeypatch.setattr(history, "experiment_manifest", lambda root: {"changed": "changed"})
    with pytest.raises(ValueError, match="experiment source, protocol"):
        history.run(completed)


def test_source_change_during_run_blocks_next_saved_or_live_call(
    completed: Path, monkeypatch,
) -> None:
    actual = history.experiment_manifest(config.ROOT)
    checks = []
    def source_manifest(root):
        checks.append(root)
        return actual if len(checks) == 1 else {"changed": "changed"}
    monkeypatch.setattr(history, "experiment_manifest", source_manifest)
    monkeypatch.setattr(llm, "_post", lambda *args, **kwargs: pytest.fail("Inference after source change"))
    with pytest.raises(ValueError, match="changed after run started"):
        history.run(completed)
    assert len(checks) == 2


def test_annotation_completeness_types_and_provenance(completed: Path) -> None:
    rows = annotations_for(completed)
    ids = {row["turn_id"] for row in rows}
    assert len(history.validate_annotations(rows, ids)) == 480
    with pytest.raises(ValueError, match="480 unique"):
        history.validate_annotations(rows[:-1], ids)
    duplicate = [*rows[:-1], rows[0]]
    with pytest.raises(ValueError, match="480 unique"):
        history.validate_annotations(duplicate, ids)
    rows[0]["relevance"] = True
    with pytest.raises(ValueError, match="quality score"):
        history.validate_annotations(rows, ids)
    rows[0]["relevance"] = 2
    rows[0]["independent"] = True
    with pytest.raises(ValueError, match="nonindependent"):
        history.validate_annotations(rows, ids)


def test_report_counts_pairs_exact_tests_and_point_criteria(
    completed: Path, tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setattr(llm, "_post", lambda *args, **kwargs: pytest.fail("Report inference"))
    labels = tmp_path / "annotations.jsonl"
    rows = annotations_for(completed)
    rows[0]["ambiguous"] = True
    probe.write_rows(labels, rows)
    result = history.report(tmp_path / "report", labels, completed)
    assert result["checks"] == {
        "completed_calls": 960, "dialogues": 60, "speech_turns": 480,
        "complete_annotation_ids": 480, "turns_per_dialogue": 8,
        "original_replay_matched": 240, "original_replay_compared": 240,
        "original_runs_preserved": 432}
    assert result["metrics"]["unsupported_assertion"]["p_two_sided"] == 2 / 1024
    assert result["metrics"]["unsupported_assertion"]["holm_two_safety_p"] == 4 / 1024
    assert result["metrics"]["unsupported_assertion"]["family_sensitivity"]["p_two_sided"] == 2 / 64
    assert result["adoption"]["point_candidate"] is True
    assert all(result["metrics"][key]["permutations"] == 1024 for key in history.METRICS)
    assert all(result["metrics"][key]["family_sensitivity"]["permutations"] == 64
               for key in history.METRICS)
    assert len(probe.read_rows(tmp_path / "report/scene_pairs.jsonl")) == 10
    assert len(probe.read_rows(tmp_path / "report/dialogue_metrics.jsonl")) == 60
    assert len(probe.read_rows(tmp_path / "report/input_output_pairs.jsonl")) == 960
    assert result["controls"]["H"]["normal_purchase"]["turn_denominator"] == 30
    assert result["controls"]["B"]["verified"]["turn_denominator"] == 12
    assert result["controls"]["H"]["rumor"]["turn_denominator"] == 24
    assert result["scripted_purchase_outcomes"]["B"]["completed"] == 30
    assert result["provenance"]["independent_human_evaluation"] is False
    assert (completed / "annotation_seal.json").exists()


def test_statistics_use_equal_scenario_weights_not_pooled_turns(completed: Path) -> None:
    mapping = probe.read_json(completed / "review_mapping.json")
    labels = {(row["scenario_id"], row["turn"]): row for row in probe.read_json(completed / "labels.json")}
    annotations = {row["turn_id"]: row for row in annotations_for(completed)}
    entries = [{**row, "schema_ok": True, "response": "__OUTPUT__",
                "annotation": annotations[row["turn_id"]],
                "groups": labels[(row["scenario_id"], row["turn"])]["groups"]}
               for row in mapping]
    for row in entries:
        row["annotation"]["relevance"] = 0 if row["scenario_id"] == "S06_v1" else 2
    dialogues, pairs = history.aggregate(entries)
    assert len(dialogues) == 60 and len(pairs) == 10
    assert mean_for_metric(pairs, "B", "relevance") == 1.8
    controls = history.subgroup_summary(entries)
    assert controls["B"]["normal_control"]["quality"]["relevance"] == 1.8
    assert history.exact_sign_flip([0.0] * 10)["p_two_sided"] == 1


def mean_for_metric(pairs: list, variant: str, metric: str) -> float:
    return sum(row[variant][metric] for row in pairs) / len(pairs)


def test_adoption_requires_both_safety_all_quality_and_controls() -> None:
    metrics = {key: {"mean_H_minus_B": 0} for key in history.METRICS}
    metrics["unsupported_assertion"]["mean_H_minus_B"] = -0.1
    controls = {variant: {group: {"counts": {
        "irrelevant_evidence_request": 0, "unwarranted_refusal": 0}}
        for group in ("normal_purchase", "normal_control")} for variant in ("B", "H")}
    assert history.adoption(metrics, controls)["point_candidate"]
    metrics["fluency"]["mean_H_minus_B"] = -0.01
    assert not history.adoption(metrics, controls)["point_candidate"]
    metrics["fluency"]["mean_H_minus_B"] = 0
    metrics["policy_contradiction"]["mean_H_minus_B"] = 0.01
    assert not history.adoption(metrics, controls)["point_candidate"]
    metrics["policy_contradiction"]["mean_H_minus_B"] = 0
    controls["H"]["normal_control"]["counts"]["unwarranted_refusal"] = 1
    assert not history.adoption(metrics, controls)["point_candidate"]
