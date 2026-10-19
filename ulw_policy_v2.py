"""P4 승격 정책: fail-closed. 사전등록 대상 (2026-10-15)."""
from __future__ import annotations

HIGH_RISK_PREDICATES = frozenset({
    "reserved_item", "paid_deposit", "promised_reward",
    "promised_discount", "completed_errand", "owns_item",
})
TRUST_ACCEPT_THRESHOLD = 2
DECISIONS = ("accept_as_belief", "reject", "dispute", "defer", "request_evidence")


def risk_of_v2(predicate: str, speech_act: str) -> str:
    if predicate in HIGH_RISK_PREDICATES:
        return "high_risk"
    if speech_act == "claim" and predicate == "none":
        return "high_risk"
    return "low_risk"


def expected_decision_v2(
    predicate: str,
    speech_act: str,
    evidence: str,
    trust: int,
    contradicts_state: bool = False,
) -> str:
    if contradicts_state:
        return "reject"
    if evidence == "contradicting":
        return "dispute"
    risk = risk_of_v2(predicate, speech_act)
    if risk == "high_risk":
        return "request_evidence" if evidence == "none" else "accept_as_belief"
    return "accept_as_belief" if trust >= TRUST_ACCEPT_THRESHOLD else "defer"
