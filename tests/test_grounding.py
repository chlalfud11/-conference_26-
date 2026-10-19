from __future__ import annotations

import json

import pytest

from npc import config
from npc.engine import GameEngine
from npc.runner import _engine_grounding


@pytest.fixture
def engine():
    instance = GameEngine()
    yield instance
    instance.close()


@pytest.mark.parametrize("reserved", [0, 2])
def test_grounding_reads_actual_reservation_even_for_noncanonical_object(engine, reserved):
    engine.reset({"shop.reserved.달빛 잼": reserved})

    data = json.loads(_engine_grounding(
        engine, "reserved_item", "달빛 잼 두 병", "none", 1, False,
    ))

    assert data["world_truth"]["shop.reserved.달빛 잼"] == reserved
    assert data["world_truth_source"] == "game_engine"
    assert data["policy_inputs"]["claim_object"] == "달빛 잼 두 병"


@pytest.mark.parametrize(
    "evidence,verified",
    [("none", False), ("verified", True), ("contradicting", False)],
)
def test_grounding_preserves_evidence_status_and_provenance(engine, evidence, verified):
    data = json.loads(_engine_grounding(
        engine, "heard_rumor", "늑대", evidence, 2, False,
    ))

    assert data["policy_inputs"]["evidence"] == evidence
    assert data["policy_inputs"]["evidence_verified"] is verified
    assert data["policy_inputs"]["evidence_trust_contradiction_source"] == "scenario_fixture"


def test_high_trust_belief_does_not_turn_unverified_evidence_into_verified(engine):
    before = engine.world()
    assert config.expected_decision("low_risk", "none", 3) == "accept_as_belief"

    data = json.loads(_engine_grounding(
        engine, "heard_rumor", "늑대", "none", 3, False,
    ))

    assert data["policy_inputs"]["evidence_verified"] is False
    assert data["policy_inputs"]["trust"] == 3
    assert data["world_truth"] == before
    assert engine.world() == before


def test_grounding_reflects_committed_trade_not_initial_inventory(engine):
    assert engine.buy(1, "여행용 빵", 2).ok

    data = json.loads(_engine_grounding(
        engine, "none", "", "none", 1, False,
    ))

    assert data["world_truth"]["player.gold"] == 30
    assert data["world_truth"]["shop.stock.여행용 빵"] == 3
    assert data["world_truth"]["player.inventory.여행용 빵"] == 2
