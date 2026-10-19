from __future__ import annotations

import pytest

from npc import config
from npc.engine import GameEngine
from npc.speech import TEMPLATES, make_speech_plan, render_speech_plan


@pytest.fixture
def engine():
    instance = GameEngine()
    yield instance
    instance.close()


@pytest.mark.parametrize("reserved", [0, 2])
def test_stock_slots_come_from_engine_not_claimed_reservation(engine, reserved):
    engine.reset({"shop.reserved.달빛 잼": reserved})

    plan = make_speech_plan(
        engine, "request_evidence", "none", "달빛 잼 20병 예약했어요.",
        "reserved_item", "__MODEL_PRODUCT__", "claim_reservation",
    )

    assert plan.template_id == "stock_and_policy"
    assert plan.values == {
        "item": "달빛 잼", "stock": 2, "reserved": reserved, "unit_price": 30,
    }
    assert plan.policy_key == "request_evidence"
    assert plan.sources["reserved"] == "game_engine"


def test_purchase_confirmation_uses_successful_trade_payload(engine):
    result = engine.buy(1, "여행용 빵", 2)
    assert result.ok

    plan = make_speech_plan(
        engine, "defer", "none", "빵 주세요.", "none", "", "buy", result,
    )

    assert plan.template_id == "purchase_completed"
    assert plan.values == {"item": "여행용 빵", "quantity": 2, "total_price": 20}
    assert set(plan.sources.values()) == {"buy_skill"}
    assert engine.fact("player.inventory.여행용 빵") == 2


@pytest.mark.parametrize("item,quantity,reason", [
    ("달빛 잼", 4, "insufficient_gold"),
    ("여행용 빵", 6, "insufficient_stock"),
    ("여행용 빵", 0, "invalid_quantity"),
    ("__MODEL_PRODUCT__", 1, "unknown_item"),
])
def test_failed_purchase_cannot_become_purchase_confirmation(engine, item, quantity, reason):
    engine.reset({"player.gold": 100})
    before = engine.world()
    result = engine.buy(1, item, quantity)
    assert not result.ok

    plan = make_speech_plan(
        engine, "defer", "none", "잼 주세요.", "none", "", "buy", result,
    )

    assert plan.template_id == f"buy_{reason}"
    assert plan.values == {}
    assert engine.world() == before


@pytest.mark.parametrize("decision,evidence,expected", [
    ("request_evidence", "none", "request_evidence"),
    ("dispute", "contradicting", "dispute"),
    ("defer", "none", "defer"),
    ("reject", "verified", "reject"),
    ("accept_as_belief", "none", "accept_unverified"),
    ("accept_as_belief", "verified", "accept_verified"),
])
def test_policy_act_distinguishes_unverified_belief(engine, decision, evidence, expected):
    plan = make_speech_plan(
        engine, decision, evidence, "그런 이야기를 들었어요.",
        "heard_rumor", "", "ask_info",
    )

    assert plan.template_id == expected
    assert plan.values == {}
    assert plan.template_id in TEMPLATES
    assert render_speech_plan(plan) == TEMPLATES[expected]


@pytest.mark.parametrize("player,intent,expected", [
    ("안녕하세요.", "smalltalk", "greeting"),
    ("다음에 또 들를게요.", "other", "farewell"),
    ("취급하는 품목이 궁금해요.", "ask_info", "catalog"),
])
def test_social_and_catalog_acts_need_no_model_factual_text(engine, player, intent, expected):
    plan = make_speech_plan(
        engine, "defer", "none", player, "none", "__MODEL_PRODUCT__", intent,
    )

    assert plan.template_id == expected
    if expected == "catalog":
        assert plan.values == {"items": ", ".join(config.PRICES)}
    else:
        assert plan.values == {}


def test_unknown_rumor_subject_keeps_belief_act_instead_of_unrelated_catalog(engine):
    plan = make_speech_plan(
        engine, "accept_as_belief", "none", "북쪽 숲에 늑대가 다닌다던데요.",
        "none", "", "ask_info",
    )

    assert plan.template_id == "accept_unverified"
    assert plan.values == {}
