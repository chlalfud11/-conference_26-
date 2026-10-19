from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from npc import config, llm, root_cause_probe as probe, runner
from npc.adapters import MemoryItem, StructuredMemory
from npc.engine import GameEngine


@pytest.fixture
def frozen(tmp_path: Path) -> Path:
    probe.freeze(tmp_path)
    return tmp_path


def test_freeze_replays_all_actual_inputs_without_inference(frozen: Path) -> None:
    cards, labels = probe.load_frozen(frozen)
    manifest = probe.read_json(frozen / "manifest.json")

    assert manifest["matched"] == manifest["compared"] == 12
    assert len(labels) == len(cards) == 12
    assert manifest["source_sha256"] == probe.source_manifest(config.ROOT)
    assert all(runner._hash(c["original_messages"]) == c["original_prompt_hash"] for c in cards)
    assert all(c["action_phase"] == "not_executed" for c in cards)
    assert all(c["exposure_counts"]["npc_belief"] == 0 for c in cards)
    for card in cards:
        assert not ({"truth_predicate", "expected_decision", "forbidden_assertions"} & card.keys())
        ground = json.loads(card["grounding"])
        assert ground["world_truth"] == card["current_state"]
        assert ground["policy_inputs"]["claim_predicate"] == card["nlu_predicate"]
        assert card["decision"] == config.expected_decision(
            config.risk_of(card["nlu_predicate"]), card["policy_inputs"]["evidence"],
            card["policy_inputs"]["trust"], card["policy_inputs"]["contradicts_state"],
        )
    purchase = next(c for c in cards if c["card_id"] == "S05_v1/t6")
    assert purchase["pending_action"]["skill"] == "buy"
    assert purchase["current_state"]["player.inventory.여행용 빵"] == 0
    assert not any(row["turn_id"] >= purchase["turn"] for row in purchase["events"])


def test_freeze_restores_scoped_replay_and_is_idempotent(frozen: Path) -> None:
    chat, build = llm.chat, runner.build_memory
    before = probe.read_rows(frozen / "snapshots.jsonl")

    probe.freeze(frozen)

    assert llm.chat is chat
    assert runner.build_memory is build
    assert probe.read_rows(frozen / "snapshots.jsonl") == before


def test_frozen_state_tampering_is_rejected(frozen: Path) -> None:
    cards = probe.read_rows(frozen / "snapshots.jsonl")
    cards[0]["current_state"]["player.gold"] = 999
    probe.write_rows(frozen / "snapshots.jsonl", cards)

    with pytest.raises(ValueError, match="Frozen state"):
        probe.load_frozen(frozen)


def test_hash_mismatch_blocks_all_freeze_artifacts(tmp_path: Path, monkeypatch) -> None:
    cards, labels = probe.reconstruct(config.ROOT)
    cards[0]["reconstructed_prompt_hash"] = "mismatch"
    monkeypatch.setattr(probe, "reconstruct", lambda root: (cards, labels))

    with pytest.raises(ValueError, match="Freeze prerequisite"):
        probe.freeze(tmp_path)

    assert not (tmp_path / "snapshots.jsonl").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_H_structurally_filters_only_npc_utterances(frozen: Path) -> None:
    card = probe.load_frozen(frozen)[0][0]
    filtered = [item for item in card["memory_items"]
                if not (item["kind"] == "utterance" and item["source"] == "도르만")]
    context = "\n".join(MemoryItem(**item).render(tuple(card["fields"])) for item in filtered)

    result = probe.speech_messages(card, "H")

    assert result == probe._messages(card, context, runner.SOURCED_SPEECH_EXAMPLES)
    assert sum(item["kind"] == "player_claim" for item in filtered) == len(card["claims"])
    assert all(item in filtered for item in card["utterances"] if item["source"] == "손님")
    assert card["memory_items"] == probe.load_frozen(frozen)[0][0]["memory_items"]


def test_E_links_real_belief_evidence_not_policy_acceptance() -> None:
    engine = GameEngine()
    try:
        memory = StructuredMemory(engine)
        claim_id = engine.save_claim(1, "__RUMOR__", "heard_rumor", "__SUBJECT__", "none")
        engine.record_decision(1, claim_id, "accept_as_belief", "policy_engine")
        memory.remember(1, "도르만", "__NPC__")
        card = {
            "memory_items": [probe.asdict(item) for item in memory._items()],
            "claims": [dict(row) for row in engine.claims()],
            "beliefs": [dict(row) for row in engine.beliefs()],
        }

        items = probe.separated_memory(card)

        belief = next(item for item in items if item["kind"] == "npc_belief")
        assert belief["policy_acceptance"] == "accept_as_belief"
        assert belief["evidence_status"] == "none"
        assert belief["evidence_verified"] is False
        assert belief["evidence_source"] == "scenario_fixture"
        assert "verified" not in belief
        assert engine.world()["player.gold"] == config.INITIAL_GOLD
    finally:
        engine.close()


def test_E_zero_exposure_preserves_memory_rendering(frozen: Path) -> None:
    cards, _ = probe.load_frozen(frozen)
    for card in cards:
        result = probe.speech_messages(card, "E")
        # Compare derived sections, not pinned natural-language prompt wording.
        before = card["original_messages"][0]["content"].split("[기억]\n", 1)[1].split("\n\n[엔진 근거]", 1)[0]
        after = result[0]["content"].split("[기억]\n", 1)[1].split("\n\n[엔진 근거]", 1)[0]
        assert before == after
        assert result[1] == card["original_messages"][1]


def test_C_uses_pre_action_state_and_actual_policy(frozen: Path) -> None:
    card = next(c for c in probe.load_frozen(frozen)[0] if c["card_id"] == "S05_v1/t6")
    messages = probe.speech_messages(card, "C")
    payload = json.loads(messages[0]["content"].split("[현재 발화 계약]\n", 1)[1].split("\n", 1)[0])

    assert payload["current_facts"] == card["current_state"]
    assert payload["decision"] == card["decision"]
    assert payload["actual_nlu"] == card["parsed_nlu"]
    assert payload["action_phase"] == "not_executed"
    assert payload["pending_action"] == card["pending_action"]
    assert not ({"truth_predicate", "expected_decision"} & payload.keys())
    assert payload["committed_events"] == card["events"]


def test_nlu_targets_current_user_with_only_preceding_two_users(frozen: Path) -> None:
    card = probe.load_frozen(frozen)[0][1]
    messages = probe.nlu_messages(card, "context")
    context = json.loads(messages[0]["content"].split("[이전 사용자 최대 2턴]\n", 1)[1])

    assert len(context) == 2
    assert context == card["preceding_user_turns"]
    assert messages[-1] == {"role": "user", "content": card["player"]}
    assert probe.nlu_messages(card, "current") == [
        {"role": "system", "content": runner.NLU_INSTRUCTION},
        {"role": "user", "content": card["player"]},
    ]
    assert probe.speech_messages(card, "I")[0]["content"] == (
        probe.OFFICIAL_PREFIX + "\n" + card["original_messages"][0]["content"]
    )


def test_fixed_call_plan_counts_ids_rotation_and_runtime_separation(frozen: Path) -> None:
    cards, _ = probe.load_frozen(frozen)

    calls, repeated = probe.jobs(cards), probe.jobs(cards, runtime=True)

    assert len(calls) == len({c["call_id"] for c in calls}) == 288
    assert sum(c["task"] == "nlu" for c in calls) == 108
    assert sum(c["task"] == "speech" for c in calls) == 180
    assert len(repeated) == len({c["call_id"] for c in repeated}) == 12
    assert not ({c["call_id"] for c in calls} & {c["call_id"] for c in repeated})
    assert len({c["prompt_hash"] for c in repeated}) == 4
    assert [c["order"] for c in calls] == list(range(288))
    for card in cards:
        subset = [c for c in calls if c["card_id"] == card["card_id"] and c["task"] == "nlu"]
        assert {tuple(c["variant"] for c in subset[i:i + 3]) for i in (0, 3, 6)} == {
            ("current", "context", "prefix"), ("context", "prefix", "current"),
            ("prefix", "current", "context"),
        }
    with pytest.raises(ValueError, match="exactly seeds"):
        probe.jobs(cards, (11,))


def test_executor_observes_wire_response_and_never_reruns_completed(
    frozen: Path, monkeypatch,
) -> None:
    planned = probe.jobs(probe.load_frozen(frozen)[0])[:2]
    seen = []

    def post(url: str, payload: dict, timeout: int = 180) -> dict:
        seen.append(payload)
        return {
            "choices": [{"message": {"content": json.dumps({
                "intent": "claim_reservation", "speech_act": "claim",
                "claim_predicate": "reserved_item", "claim_object": "달빛 잼", "confidence": 0.9,
            })}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 160},
            "truncated": False, "timings": {"prompt_n": 42},
        }

    monkeypatch.setattr(llm, "_post", post)
    original_chat = llm.chat

    first = probe.execute(frozen, planned)
    second = probe.execute(frozen, planned)

    rows = probe.read_rows(frozen / "pilot_calls.jsonl")
    assert first["completed"] == second["completed"] == len(seen) == 2
    assert len(rows) == 2
    assert all(row["usage"]["prompt_tokens"] == 42 for row in rows)
    assert all(row["output_truncated"] is True and row["input_truncated"] is False for row in rows)
    assert all(row["observation"]["raw_response"]["timings"]["prompt_n"] == 42 for row in rows)
    assert llm.chat is original_chat
    assert llm._post is post
    assert all(p["temperature"] == 0.2 and p["top_p"] == 0.9 for p in seen)


def test_transport_failure_is_preserved_but_completed_malformed_is_not_resampled(
    frozen: Path, monkeypatch,
) -> None:
    planned = probe.jobs(probe.load_frozen(frozen)[0])[:1]
    count = 0

    def post(url: str, payload: dict, timeout: int = 180) -> dict:
        nonlocal count
        count += 1
        if count == 1:
            raise llm.InferenceError("transport unavailable")
        return {"choices": []}

    monkeypatch.setattr(llm, "_post", post)

    first = probe.execute(frozen, planned)
    second = probe.execute(frozen, planned)
    third = probe.execute(frozen, planned)

    rows = probe.read_rows(frozen / "pilot_calls.jsonl")
    assert not first["pass"] and second["pass"] and third["pass"]
    assert count == 2
    assert [row["status"] for row in rows] == ["failed", "completed"]
    assert rows[0]["attempt_id"] != rows[1]["attempt_id"]
    assert rows[1]["schema_ok"] is False
    assert llm._post is post


def _synthetic_calls(cards: list[dict], runtime: bool = False) -> list[dict]:
    rows = []
    for job in probe.jobs(cards, runtime=runtime):
        rows.append({
            **job, "status": "completed", "response": "__OUTPUT__", "schema_ok": True,
            "parsed": {"claim_predicate": "none"}, "output_truncated": False,
            "input_truncated": None,
        })
    return rows


def test_blind_review_and_report_require_all_reviews_and_expose_denominators(frozen: Path) -> None:
    cards, _ = probe.load_frozen(frozen)
    probe.write_rows(frozen / "pilot_calls.jsonl", _synthetic_calls(cards))
    probe.write_rows(frozen / "runtime_calls.jsonl", _synthetic_calls(cards, runtime=True))
    probe.write_json(frozen / "runtime_metadata.json", {"interface_caveat": "unconfirmed test fixture"})

    summary = probe.review_pack(frozen)

    visible = probe.read_rows(frozen / "review_pack.jsonl")
    mapping = probe.read_rows(frozen / "review_mapping.jsonl")
    assert summary == {"speech_reviews": 180, "nlu_programmatic": 108}
    assert len(visible) == len(mapping) == 180
    assert not any({"variant", "call_id", "seed", "prompt_hash", "messages"} & row.keys() for row in visible)
    annotations = probe.read_rows(frozen / "annotations.jsonl")
    with pytest.raises(ValueError, match="Incomplete semantic flags"):
        probe.validate_annotations(annotations, mapping)
    for row in annotations:
        row.update({flag: False for flag in probe.SEMANTIC_FLAGS})
        row.update(ambiguous=False, judge="executor", judge_type="ai_assisted",
                   independent=False, rationale="Fixture evidence audit", evidence_refs=["current_state"])
    probe.write_rows(frozen / "annotations.jsonl", annotations)
    result = probe.report(frozen / "report", frozen / "annotations.jsonl", frozen)

    assert result["denominators"] == {"speech": 180, "nlu": 108, "runtime": 12, "semantic_review": 180}
    assert all(row["denominator"] == 36 for row in result["speech"].values())
    assert all(row["denominator"] == 36 for row in result["nlu"].values())
    assert not any(row["eligible"] for row in result["speech"].values())
    assert result["review_provenance"]["independent_human_evaluation"] is False
    assert result["cause_evidence"][0]["status"] == "unconfirmed_zero_belief_exposure"
    assert (frozen / "report/report.md").exists()
    with pytest.raises(ValueError, match="all 180"):
        probe.validate_annotations(annotations[:-1], mapping)
    duplicated = copy.deepcopy(annotations)
    duplicated[-1] = duplicated[0]
    with pytest.raises(ValueError, match="all 180"):
        probe.validate_annotations(duplicated, mapping)


def test_runtime_metadata_preserves_four_rendered_inputs_and_eos_without_generation(
    frozen: Path, monkeypatch,
) -> None:
    cards, _ = probe.load_frozen(frozen)
    planned = probe.jobs(cards, runtime=True)
    endpoints = []

    def metadata_probe(url: str, payload: dict | None = None) -> dict:
        endpoints.append((url, payload))
        return {"status": "observed", "body": {"prompt": "__RENDERED__", "tokens": [361]}}

    monkeypatch.setattr(probe, "probe", metadata_probe)
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)
    model = config.ROOT / "npc/config.py"

    result = probe.runtime_metadata(frozen, planned, model)

    assert len(result["rendered_inputs"]) == 4
    assert sum(url.endswith("/apply-template") for url, _ in endpoints) == 4
    assert sum(url.endswith("/tokenize") for url, _ in endpoints) == 5
    assert result["eos"]["body"]["tokens"] == [361]
    assert result["template_comparison"] == "unconfirmed"
    assert result["model_sha256"] == probe.sha256(model)
    assert not any(url.endswith("/chat/completions") for url, _ in endpoints)
    assert all(payload["with_pieces"] for url, payload in endpoints if url.endswith("/tokenize"))


@pytest.mark.parametrize("ambiguous", (False, True))
def test_report_selection_uses_error_counts_without_unplanned_ambiguity_gate(
    frozen: Path, ambiguous: bool,
) -> None:
    cards, _ = probe.load_frozen(frozen)
    probe.write_rows(frozen / "pilot_calls.jsonl", _synthetic_calls(cards))
    probe.write_rows(frozen / "runtime_calls.jsonl", _synthetic_calls(cards, runtime=True))
    probe.write_json(frozen / "runtime_metadata.json", {"interface_caveat": "test fixture"})
    probe.review_pack(frozen)
    mapping = {row["blind_id"]: row for row in probe.read_rows(frozen / "review_mapping.jsonl")}
    annotations = probe.read_rows(frozen / "annotations.jsonl")
    for row in annotations:
        row.update({flag: False for flag in probe.SEMANTIC_FLAGS})
        row.update(ambiguous=ambiguous, judge="executor", judge_type="ai_assisted",
                   independent=False, rationale="Fixture evidence audit", evidence_refs=["current_state"])
        row["unsupported_assertion"] = mapping[row["blind_id"]]["variant"] == "B"
    probe.write_rows(frozen / "annotations.jsonl", annotations)

    result = probe.report(frozen / "report", frozen / "annotations.jsonl", frozen)

    assert result["speech"]["C"]["eligible"] is True
    assert result["speech"]["C"]["ambiguous"] == (36 if ambiguous else 0)
