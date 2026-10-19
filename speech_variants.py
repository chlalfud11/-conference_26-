"""도르만 말투 템플릿 변형. 슬롯 이름과 정책 의미는 npc/speech.py와 같고, 문장만 여러 개로 늘린다.
`install(seed)`가 runner의 렌더 함수를 바꿔 끼운다(npc/* 수정 없음). 변형 선택은 seed와 템플릿별 사용 횟수로 정해진다."""
from __future__ import annotations

import hashlib
import re
from collections import Counter

from npc import runner, speech
from nlu_m1p8_live import REF

POLICY_VARIANTS: dict[str, list[str]] = {
    "request_evidence": [
        "증표나 영수증 같은 걸 보여 주게. 그래야 나도 믿을 수 있지.",
        "흠, 장부에는 그런 게 안 보이는구먼. 뭔가 증거가 될 만한 걸 가져와 보게.",
        "말만으로는 내가 확인할 길이 없네. 증표가 있으면 보여 주겠나?",
        "그 얘기를 뒷받침할 만한 게 있나? 쪽지든 영수증이든 좋네.",
    ],
    "dispute": [
        "내 장부와는 다르구먼. 그 말은 사실로 받아들이기 어렵네.",
        "기록과 맞지 않네. 미안하지만 그대로 믿을 수는 없겠어.",
        "장부를 보면 그렇지 않다네. 그 말은 받아들이지 않겠네.",
        "글쎄, 내가 아는 것과는 영 다르구먼. 그건 사실로 칠 수 없네.",
    ],
    "defer": [
        "그건 지금 당장 판단하기 어렵구먼. 좀 더 알아보고 얘기하세.",
        "흠, 일단 판단은 미뤄 두겠네.",
        "그 일은 아직 뭐라 말하기 이르네. 나중에 다시 얘기해 보세.",
        "확실해질 때까지는 결정을 미루겠네.",
    ],
    "reject": [
        "미안하지만 그 부탁은 들어줄 수 없네.",
        "그건 곤란하구먼. 지금은 해 줄 수 없겠어.",
        "안 되겠네. 그 요청은 받아들일 수 없어.",
        "그건 어렵겠네. 다른 걸 도와줄까?",
    ],
    "accept_verified": [
        "증표를 보니 맞구먼. 그 얘기는 내가 잘 기억해 두지.",
        "확인됐네. 자네 말대로 장부에 적어 두겠네.",
        "그래, 증거가 있으니 믿겠네. 기억해 두지.",
        "이제 확인이 됐구먼. 잊지 않고 기억하겠네.",
    ],
    "accept_unverified": [
        "알겠네. 다만 아직 확인된 건 아니니 그런 얘기가 있었다고만 적어 두지.",
        "자네 말은 들었네. 확인되기 전까지는 그냥 들은 얘기로 기억해 두겠네.",
        "그렇군. 사실인지는 모르니 일단 메모만 해 두겠네.",
        "그런 얘기가 있다는 건 알아 두지. 확인된 사실로 치지는 않겠네.",
    ],
}

TEMPLATE_VARIANTS: dict[str, list[str]] = {
    "greeting": ["어서 오게! 뭘 찾나?", "오, 왔구먼. 필요한 게 있으면 말하게.", "어서 오게. 천천히 둘러보게나.",
                 "반갑네. 오늘은 뭘 보러 왔나?"],
    "farewell": ["조심히 가게. 또 들르고.", "잘 가게나. 다음에 또 보세.", "살펴 가게. 필요하면 또 오게.",
                 "그래, 잘 가게. 길 조심하고."],
    "catalog": ["우리 가게엔 {items}이 있네. 뭐가 필요한가?", "{items}을 팔고 있지. 궁금한 게 있으면 물어보게.",
                "지금 있는 건 {items}일세. 골라 보게."],
    "stock_and_policy": [
        "{item}은 지금 {stock}개 있고, 예약분은 {reserved}개네. 하나에 {unit_price}골드일세. {policy_line}",
        "{item} 말인가? 재고 {stock}개에 예약분이 {reserved}개, 값은 {unit_price}골드네. {policy_line}",
        "{item}이라면 {stock}개 남았고 예약분이 {reserved}개구먼. 개당 {unit_price}골드야. {policy_line}",
    ],
    "purchase_completed": ["{item} {quantity}개, 모두 {total_price}골드일세. 고맙네.",
                           "자, {item} {quantity}개 챙겼네. {total_price}골드 받았네.",
                           "{item} {quantity}개 계산 끝났네. 합해서 {total_price}골드야."],
    "buy_insufficient_gold": ["이런, 골드가 모자라구먼.", "가진 골드로는 부족하네. 다음에 오게."],
    "buy_insufficient_stock": ["미안하네, 그만큼은 재고가 없어.", "물건이 모자라서 그렇게는 못 주겠네."],
    "buy_invalid_quantity": ["몇 개를 사겠다는 건지 다시 말해 주게.", "수량이 이상하구먼. 다시 말해 주겠나?"],
    "buy_unknown_item": ["그건 우리 가게에서 안 파는 물건일세.", "그런 물건은 취급하지 않네."],
    "rumor": ["그런 소문이 도나? 사실인지는 모르겠지만 귀는 열어 두지.", "허, 그런 얘기가 있구먼. 더 들리는 게 있으면 알려 주게.",
              "글쎄, 난 처음 듣는 얘기네. 맞는지는 두고 봐야겠어.", "그렇다더군. 소문이야 원래 부풀려지기 마련이지만."],
    "browse": ["그거라면 한번 찾아보지. 잠깐 기다리게.", "흠, 창고에 남아 있나 보겠네.",
               "알겠네. 물건 보고 값을 알려 주지.", "그래, 그것도 볼 거면 꺼내 오겠네."],
    "smalltalk": ["허허, 그렇구먼.", "그런가? 알겠네.", "그래, 그렇군.", "허, 그렇구먼. 천천히 보게."],
    "thanks": ["뭘, 고맙긴.", "허허, 별말을.", "그래, 또 필요하면 말하게."],
}

FOLLOWUP_PREFIX = ["아까 그 얘기 말인가? ", "그 얘기라면 아까 했던 말 그대로일세. ", "여전히 그 얘기구먼. "]
POLICY_VARIANTS["sale"] = ["몇 개 줄까?", "필요한 만큼 말하게.", "보고 마음에 들면 말하게."]
BROWSE = re.compile(r"(주세요|주시오|주시겠|살게|사면|사려|하나요|하나 주|볼게|보여|얼마|값이|가격|"
                    r"한 (쌌|켤레|자루|개|통|병|필|묶음)|도 (하나|한|같이))")
THANKS = re.compile(r"(고맙|감사)")
GREETING = re.compile(r"(안녕|구경|왔어요|왔소)")
FAREWELL = re.compile(r"(가볼게|다음에|다음번|잘 가|갈게요|가오)")


def make_plan_v2(engine, decision, evidence, player, predicate, claim_object, intent, purchase=None):
    if purchase is not None:
        return speech.make_speech_plan(engine, decision, evidence, player, predicate, claim_object, intent, purchase)
    if predicate == "heard_rumor":
        return speech.SpeechPlan("rumor", {}, {"template_id": "dialogue_act"})
    if predicate == "none":
        item = next((name for name in speech.config.PRICES if name in player), None)
        if item is not None:
            return speech.SpeechPlan(
                "stock_and_policy",
                {"item": item, "stock": engine.fact(f"shop.stock.{item}"),
                 "reserved": engine.fact(f"shop.reserved.{item}"), "unit_price": speech.config.PRICES[item]},
                {"item": "price_table", "stock": "game_engine", "reserved": "game_engine",
                 "unit_price": "price_table", "policy_key": "dialogue_act"},
                policy_key="sale")
        for act, pattern in (("greeting", GREETING), ("farewell", FAREWELL), ("thanks", THANKS), ("browse", BROWSE)):
            if pattern.search(player):
                return speech.SpeechPlan(act, {}, {"template_id": "dialogue_act"})
        return speech.SpeechPlan("smalltalk", {}, {"template_id": "dialogue_act"})
    plan = speech.make_speech_plan(engine, decision, evidence, player, predicate, claim_object, intent, purchase)
    if REF.search(player):
        return speech.SpeechPlan(plan.template_id, {**plan.values, "_followup": 1}, plan.sources, plan.policy_key)
    return plan


def all_rendered_variants() -> list[tuple[str, str]]:
    out = [(k, p + v) for k, vs in POLICY_VARIANTS.items() for v in vs for p in ["", *FOLLOWUP_PREFIX]]
    for k, vs in TEMPLATE_VARIANTS.items():
        for v in vs:
            if "{policy_line}" in v:
                out += [(f"{k}+{pk}", v.replace("{policy_line}", pv)) for pk, pvs in POLICY_VARIANTS.items() for pv in pvs]
            else:
                out.append((k, v))
    return out


def install(seed: int, v2: bool = False) -> None:
    used: Counter[str] = Counter()

    def pick(key: str, options: list[str]) -> str:
        offset = int(hashlib.sha256(f"{seed}:{key}".encode()).hexdigest(), 16)
        choice = options[(offset + used[key]) % len(options)]
        used[key] += 1
        return choice

    def render(plan: speech.SpeechPlan) -> str:
        values = dict(plan.values)
        followup = values.pop("_followup", 0)
        if plan.policy_key is not None:
            values["policy_line"] = pick(plan.policy_key, POLICY_VARIANTS[plan.policy_key])
        options = POLICY_VARIANTS.get(plan.template_id) or TEMPLATE_VARIANTS[plan.template_id]
        text = pick(plan.template_id, options).format_map(values)
        return (pick("_followup", FOLLOWUP_PREFIX) + text) if followup else text

    runner.render_speech_plan = render
    if v2:
        runner.make_speech_plan = make_plan_v2
