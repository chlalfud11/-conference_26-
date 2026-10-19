from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import config
from .engine import GameEngine, SkillResult

POLICY_LINES: Final[dict[str, str]] = {
    "request_evidence": "자네, 그 말씀을 뒷받침할 증거를 보여주겠어요?",
    "dispute": "그 말씀은 확정된 사실로 받아들이지 않겠어요.",
    "defer": "그 말씀에 대한 판단은 보류할게요.",
    "reject": "지금은 그 요청을 받아들일 수 없어요.",
    "accept_verified": "제공된 증거를 근거로 자네의 말씀을 기억해 둘게요.",
    "accept_unverified": "자네의 말씀은 아직 확인되지 않은 이야기로 기억해 둘게요.",
}

TEMPLATES: Final[dict[str, str]] = {
    **POLICY_LINES,
    "greeting": "자네, 어서 와요. 필요한 물건을 말씀해 주세요.",
    "farewell": "자네, 조심해서 가요. 다음에 또 들러요.",
    "catalog": "취급하는 품목은 {items}예요. 궁금한 물건을 말씀해 주세요.",
    "stock_and_policy": (
        "{item}의 현재 재고는 {stock}개, 예약 수량은 {reserved}개이고 "
        "판매가는 {unit_price}골드예요. {policy_line}"
    ),
    "purchase_completed": (
        "자네, {item} {quantity}개 구매가 처리됐어요. 총액은 {total_price}골드예요."
    ),
    "buy_insufficient_gold": "골드가 부족해 구매를 처리하지 못했어요.",
    "buy_insufficient_stock": "판매 가능한 재고가 부족해 구매를 처리하지 못했어요.",
    "buy_invalid_quantity": "구매 수량이 올바르지 않아 처리하지 못했어요.",
    "buy_unknown_item": "취급하지 않는 품목이라 구매를 처리하지 못했어요.",
}


@dataclass(frozen=True, slots=True)
class SpeechPlan:
    template_id: str
    values: dict[str, str | int]
    sources: dict[str, str]
    policy_key: str | None = None


def make_speech_plan(
    engine: GameEngine, decision: str, evidence: str, player: str,
    predicate: str, claim_object: str, intent: str,
    purchase: SkillResult | None = None,
) -> SpeechPlan:
    """Use engine values and controlled acts, never the model's candidate text."""
    if purchase is not None:
        if purchase.ok:
            values = {
                key: purchase.payload[key]
                for key in ("item", "quantity", "total_price")
            }
            return SpeechPlan(
                "purchase_completed", values, {key: "buy_skill" for key in values},
            )
        return SpeechPlan(
            f"buy_{purchase.reason}", {}, {"template_id": "buy_skill"},
        )

    policy_key = decision
    if decision == "accept_as_belief":
        policy_key = "accept_verified" if evidence == "verified" else "accept_unverified"

    if predicate == "none":
        if "안녕" in player or "구경" in player:
            return SpeechPlan("greeting", {}, {"template_id": "dialogue_act"})
        if any(word in player for word in ("가볼게", "다음에", "다음번", "잘 가")):
            return SpeechPlan("farewell", {}, {"template_id": "dialogue_act"})

    item = claim_object if claim_object in config.PRICES else next(
        (name for name in config.PRICES if name in player), None,
    )
    if item is not None:
        return SpeechPlan(
            "stock_and_policy",
            {
                "item": item, "stock": engine.fact(f"shop.stock.{item}"),
                "reserved": engine.fact(f"shop.reserved.{item}"),
                "unit_price": config.PRICES[item],
            },
            {
                "item": "price_table", "stock": "game_engine",
                "reserved": "game_engine", "unit_price": "price_table",
                "policy_key": "policy_engine",
            },
            policy_key=policy_key,
        )
    if predicate == "none" and intent == "ask_info" and any(
        word in player for word in ("품목", "물건은", "무슨 물건", "뭘 파", "뭐 팔")
    ):
        return SpeechPlan(
            "catalog", {"items": ", ".join(config.PRICES)}, {"items": "price_table"},
        )
    return SpeechPlan(policy_key, {}, {"template_id": "policy_engine"})


def render_speech_plan(plan: SpeechPlan) -> str:
    """Render only a template-owned sentence and its trusted slots."""
    values = dict(plan.values)
    if plan.policy_key is not None:
        values["policy_line"] = POLICY_LINES[plan.policy_key]
    return TEMPLATES[plan.template_id].format_map(values)
