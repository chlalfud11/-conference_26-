from __future__ import annotations

import sqlite3

import pytest

from npc.engine import GameEngine


@pytest.fixture
def engine():
    e = GameEngine()
    yield e
    e.close()


def test_buy_success_changes_gold_stock_inventory_together(engine):
    result = engine.buy(1, "여행용 빵", 2)

    assert result.ok
    assert engine.fact("player.gold") == 30
    assert engine.fact("shop.stock.여행용 빵") == 3
    assert engine.fact("player.inventory.여행용 빵") == 2
    assert [e["event_type"] for e in engine.events()] == ["purchase_completed"]


def test_buy_insufficient_gold_leaves_every_fact_unchanged(engine):
    before = engine.world()

    result = engine.buy(1, "달빛 잼", 2)

    assert not result.ok
    assert result.reason == "insufficient_gold"
    assert engine.world() == before
    assert engine.events() == []
    assert len(engine.refusals()) == 1


def test_buy_insufficient_stock_leaves_every_fact_unchanged(engine):
    engine.reset({"player.gold": 1000})
    before = engine.world()

    result = engine.buy(1, "낡은 지도", 5)

    assert not result.ok
    assert result.reason == "insufficient_stock"
    assert engine.world() == before


def test_reserved_stock_is_not_purchasable(engine):
    engine.reset({"player.gold": 1000, "shop.reserved.달빛 잼": 2})
    before = engine.world()

    result = engine.buy(1, "달빛 잼", 1)

    assert not result.ok
    assert result.reason == "insufficient_stock"
    assert engine.world() == before


def test_partial_quantity_is_never_fulfilled(engine):
    engine.reset({"player.gold": 1000})
    before = engine.world()

    result = engine.buy(1, "작은 회복약", 4)

    assert not result.ok
    assert engine.fact("player.inventory.작은 회복약") == 0
    assert engine.world() == before


def test_accept_as_belief_does_not_modify_world_truth(engine):
    claim_id = engine.save_claim(
        1, "달빛 잼 두 병 예약했어요.", "reserved_item", "달빛 잼", "verified"
    )
    before = engine.world()

    belief_id = engine.record_decision(1, claim_id, "accept_as_belief", actor="policy_engine")

    assert belief_id is not None
    assert engine.world() == before
    assert engine.fact("shop.reserved.달빛 잼") == 0
    assert engine.fact("player.inventory.달빛 잼") == 0


def test_rejected_claim_creates_decision_but_no_belief(engine):
    claim_id = engine.save_claim(
        1, "보상 주기로 했잖아요.", "promised_reward", "100골드", "none"
    )

    belief_id = engine.record_decision(1, claim_id, "request_evidence", actor="policy_engine")

    assert belief_id is None
    assert len(engine.decisions()) == 1
    assert engine.beliefs() == []


def test_generated_text_cannot_become_memory_eligible(engine):
    engine.log_generated(1, "그럼 하나 더 드리겠어요.")

    with pytest.raises(sqlite3.IntegrityError):
        engine.conn.execute("UPDATE generated_text SET memory_eligible = 1")


def test_world_truth_rejects_a_row_sourced_from_a_player_claim(engine):
    with pytest.raises(sqlite3.IntegrityError):
        engine.conn.execute(
            "INSERT INTO world_truth (fact_id, value, source, updated_at, version) "
            "VALUES ('shop.reserved.달빛 잼', '2', 'player_claim', '2026-01-01', 1)"
        )


def test_refuse_trade_changes_no_fact(engine):
    before = engine.world()

    engine.refuse_trade(1, "unverified_reservation")

    assert engine.world() == before
    assert [e["event_type"] for e in engine.events()] == ["trade_refused"]
