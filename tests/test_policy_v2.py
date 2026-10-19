from __future__ import annotations

import itertools

import pytest

from npc import config
from ulw_policy_v2 import expected_decision_v2, risk_of_v2

DECISION_TABLE = [
    ("none", "claim", "none", 3, False, "request_evidence"),
    ("none", "claim", "verified", 0, False, "accept_as_belief"),
    ("none", "claim", "contradicting", 3, False, "dispute"),
    ("none", "claim", "verified", 3, True, "reject"),
    ("none", "question", "none", 2, False, "accept_as_belief"),
    ("none", "question", "none", 1, False, "defer"),
    ("reserved_item", "claim", "none", 3, False, "request_evidence"),
    ("heard_rumor", "claim", "none", 2, False, "accept_as_belief"),
]

SPEECH_ACTS = ("claim", "question", "other")
EVIDENCE = ("none", "verified", "contradicting")


@pytest.mark.parametrize("pred,speech_act,evidence,trust,contradicts,expected", DECISION_TABLE)
def test_decision_table_row(pred, speech_act, evidence, trust, contradicts, expected):
    assert expected_decision_v2(pred, speech_act, evidence, trust, contradicts) == expected


def test_high_risk_predicates_stay_high_risk():
    for predicate in config.HIGH_RISK_PREDICATES:
        assert risk_of_v2(predicate, "claim") == "high_risk"
        assert risk_of_v2(predicate, "other") == "high_risk"


def test_unread_predicate_is_high_risk_only_for_claims():
    assert risk_of_v2("none", "claim") == "high_risk"
    assert risk_of_v2("none", "question") == "low_risk"
    assert risk_of_v2("none", "other") == "low_risk"


def test_rumor_predicate_stays_low_risk_even_as_a_claim():
    assert risk_of_v2("heard_rumor", "claim") == "low_risk"


@pytest.mark.parametrize(
    "pred,speech_act,evidence,trust,contradicts",
    [
        cell for cell in itertools.product(
            sorted(config.CLAIM_PREDICATES), SPEECH_ACTS, EVIDENCE,
            range(config.TRUST_MIN, config.TRUST_MAX + 1), (False, True))
        if not (cell[0] == "none" and cell[1] == "claim")
    ],
)
def test_v2_matches_v1_outside_the_fail_closed_cell(pred, speech_act, evidence, trust, contradicts):
    assert expected_decision_v2(pred, speech_act, evidence, trust, contradicts) == (
        config.expected_decision(config.risk_of(pred), evidence, trust, contradicts))


@pytest.mark.parametrize(
    "evidence,trust,contradicts",
    [cell for cell in itertools.product(
        EVIDENCE, range(config.TRUST_MIN, config.TRUST_MAX + 1), (False, True))],
)
def test_fail_closed_cell_never_accepts_an_unsupported_claim(evidence, trust, contradicts):
    decision = expected_decision_v2("none", "claim", evidence, trust, contradicts)
    assert decision in set(config.DECISIONS)
    if evidence == "none" and not contradicts:
        assert decision == "request_evidence"


def test_only_the_claim_with_unread_predicate_differs_from_v1():
    differing = {
        (pred, speech_act)
        for pred, speech_act, evidence, trust, contradicts in itertools.product(
            sorted(config.CLAIM_PREDICATES), SPEECH_ACTS, EVIDENCE,
            range(config.TRUST_MIN, config.TRUST_MAX + 1), (False, True))
        if expected_decision_v2(pred, speech_act, evidence, trust, contradicts)
        != config.expected_decision(config.risk_of(pred), evidence, trust, contradicts)
    }
    assert differing == {("none", "claim")}
