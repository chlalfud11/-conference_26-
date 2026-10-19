from __future__ import annotations

import pytest

from npc import config

DECISION_TABLE = [
    ("high_risk", "contradicting", 0, False, "dispute"),
    ("high_risk", "none", 3, False, "request_evidence"),
    ("high_risk", "verified", 0, False, "accept_as_belief"),
    ("low_risk", "none", 2, False, "accept_as_belief"),
    ("low_risk", "none", 1, False, "defer"),
    ("high_risk", "verified", 3, True, "reject"),
]


@pytest.mark.parametrize("risk,evidence,trust,contradicts,expected", DECISION_TABLE)
def test_decision_table_row(risk, evidence, trust, contradicts, expected):
    assert config.expected_decision(risk, evidence, trust, contradicts) == expected


def test_every_decision_is_a_declared_enum_value():
    produced = {
        config.expected_decision(risk, evidence, trust, contradicts)
        for risk, evidence, trust, contradicts, _ in DECISION_TABLE
    }
    assert produced <= set(config.DECISIONS)


def test_low_risk_claim_is_acceptable_at_max_trust():
    assert (
        config.expected_decision("low_risk", "none", config.TRUST_MAX)
        == "accept_as_belief"
    )


def test_high_risk_claim_with_verified_evidence_is_acceptable_at_min_trust():
    assert (
        config.expected_decision("high_risk", "verified", config.TRUST_MIN)
        == "accept_as_belief"
    )


def test_reservation_and_reward_claims_are_high_risk():
    assert config.risk_of("reserved_item") == "high_risk"
    assert config.risk_of("paid_deposit") == "high_risk"
    assert config.risk_of("promised_reward") == "high_risk"


def test_rumor_claim_is_low_risk():
    assert config.risk_of("heard_rumor") == "low_risk"


def test_trust_is_clamped_to_the_zero_to_three_scale():
    assert config.clamp_trust(70) == config.TRUST_MAX
    assert config.clamp_trust(-5) == config.TRUST_MIN
