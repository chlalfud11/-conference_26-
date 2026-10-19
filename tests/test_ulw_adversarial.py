from __future__ import annotations

from pathlib import Path

import pytest

from npc import config
from npc import eval as ev

ADVERSARIAL_DIR = config.ROOT / "scenarios_adversarial"
EXISTING_DIR = config.ROOT / "scenarios"

HIGH_RISK_UNVERIFIED = "high_risk"


def _load(folder: Path) -> dict[str, dict]:
    return ev.load_scenarios(folder)


def _scored(scenario: dict) -> list[dict]:
    return [turn for turn in scenario["turns"] if turn.get("scored")]


def _criterion1_eligible_turns(scenario: dict) -> int:
    trust = config.clamp_trust(scenario.get("trust", 1))
    if trust < config.TRUST_ACCEPT_THRESHOLD:
        return 0
    return sum(
        1 for turn in _scored(scenario)
        if config.risk_of(turn["truth_predicate"]) == HIGH_RISK_UNVERIFIED
        and turn["evidence"] == "none"
    )


@pytest.fixture(scope="module")
def adversarial() -> dict[str, dict]:
    return _load(ADVERSARIAL_DIR)


@pytest.fixture(scope="module")
def existing() -> dict[str, dict]:
    return _load(EXISTING_DIR)


def test_adversarial_set_has_nine_scenarios(adversarial):
    assert len(adversarial) == 9


def test_every_adversarial_scenario_has_eight_turns(adversarial):
    for sid, scenario in adversarial.items():
        assert len(scenario["turns"]) == 8, sid


def test_every_adversarial_scenario_sits_at_the_acceptance_threshold(adversarial):
    for sid, scenario in adversarial.items():
        assert scenario["trust"] == config.TRUST_ACCEPT_THRESHOLD, sid


def test_every_adversarial_scenario_can_trigger_unsupported_promotion(adversarial):
    for sid, scenario in adversarial.items():
        assert _criterion1_eligible_turns(scenario) > 0, sid


def test_existing_set_cannot_trigger_unsupported_promotion(existing):
    assert sum(_criterion1_eligible_turns(s) for s in existing.values()) == 0


def test_adversarial_set_reuses_existing_forbidden_patterns(adversarial, existing):
    allowed: dict[str, set[str]] = {}
    for scenario in existing.values():
        for turn in scenario["turns"]:
            allowed.setdefault(turn["truth_predicate"], set()).update(
                turn.get("forbidden_assertions") or [])
    for sid, scenario in adversarial.items():
        for turn in _scored(scenario):
            novel = set(turn.get("forbidden_assertions") or []) - allowed.get(
                turn["truth_predicate"], set())
            assert not novel, (sid, turn["truth_predicate"], novel)


def test_every_adversarial_scenario_keeps_a_low_risk_control_turn(adversarial):
    for sid, scenario in adversarial.items():
        rumors = [t for t in _scored(scenario) if t["truth_predicate"] == "heard_rumor"]
        assert rumors, sid
        for turn in rumors:
            assert config.expected_decision(
                "low_risk", turn["evidence"], scenario["trust"]
            ) == "accept_as_belief", sid


def test_every_adversarial_scenario_keeps_a_normal_purchase(adversarial):
    for sid, scenario in adversarial.items():
        actions = [t["action"] for t in scenario["turns"] if t.get("action")]
        assert actions, sid
        for action in actions:
            assert action["skill"] == "buy", sid
            assert action["item"] in config.PRICES, sid


def test_every_adversarial_scenario_keeps_unscored_turns(adversarial):
    for sid, scenario in adversarial.items():
        unscored = [t for t in scenario["turns"] if not t.get("scored")]
        assert len(unscored) >= 3, sid


def test_purchased_items_are_never_the_protected_invariant_items(adversarial):
    for sid, scenario in adversarial.items():
        protected = " ".join(scenario["invariants"].values())
        for turn in scenario["turns"]:
            action = turn.get("action")
            if action:
                assert action["item"] not in protected, sid


def test_every_adversarial_scenario_protects_the_claimed_item(adversarial):
    for sid, scenario in adversarial.items():
        assert scenario["invariants"], sid
        for fact_id in scenario["invariants"].values():
            assert fact_id.startswith(("shop.reserved.", "player.inventory.")), sid


def test_adversarial_scenarios_start_from_an_empty_world(adversarial):
    for sid, scenario in adversarial.items():
        assert scenario["initial_facts"] == {}, sid


def test_adversarial_scenarios_are_not_marked_approved(adversarial):
    for sid, scenario in adversarial.items():
        assert scenario["status"] == "draft_pending_user_approval", sid
        assert scenario["approved_on"] is None, sid


def test_adversarial_scenario_ids_do_not_collide_with_existing(adversarial, existing):
    assert not set(adversarial) & set(existing)
