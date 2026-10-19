from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

from . import config, llm
from .adapters import build_memory, shop_status
from .engine import GameEngine
from .speech import make_speech_plan, render_speech_plan

INTENTS = ("claim_reservation", "request_reward", "request_discount",
           "buy", "ask_info", "smalltalk", "other")

NLU_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "speech_act": {"type": "string",
                       "enum": ["claim", "question", "request", "greeting", "other"]},
        "claim_predicate": {"type": "string", "enum": list(config.CLAIM_PREDICATES)},
        "claim_object": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["intent", "speech_act", "claim_predicate", "claim_object", "confidence"],
    "additionalProperties": False,
}

DECIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(config.DECISIONS)},
        "utterance": {"type": "string"},
    },
    "required": ["decision", "utterance"],
    "additionalProperties": False,
}

SPEAK_SCHEMA = {
    "type": "object",
    "properties": {"utterance": {"type": "string"}},
    "required": ["utterance"],
    "additionalProperties": False,
}

DECISION_KO = {
    "accept_as_belief": "손님 말을 믿는다",
    "reject": "믿지 않는다",
    "dispute": "내가 아는 것과 반대다",
    "defer": "판단을 미룬다",
    "request_evidence": "증거를 요구한다",
}

NLU_INSTRUCTION = (
    "손님의 말을 JSON으로 구조화한다.\n\n"
    "claim_predicate 는 손님이 '사실이라고 주장하는 내용'의 종류다.\n"
    + "\n".join(f"- {key}: {label}" for key, label in config.PREDICATE_LABELS.items())
    + "\n\n주장이 전혀 없는 인사·질문·단순 구매 요청은 none 을 쓴다.\n"
    "과거의 예약·선금·약속·심부름을 언급하면 반드시 해당 predicate 를 고른다.\n"
    "claim_object 는 주장이 가리키는 물건이나 대상을 한국어로 짧게 쓴다.\n"
    "설명 없이 JSON만 출력한다."
)

DECIDE_INSTRUCTION = (
    "손님이 방금 한 말을 어떻게 받아들일지 고르고, 도르만으로서 1~2문장으로 답해라.\n"
    + "\n".join(f"- {k}: {v}" for k, v in DECISION_KO.items())
    + "\nJSON으로만 출력한다."
)

RULE_BLOCK = (
    "[승격 결정표] 위에서부터 먼저 일치하는 행 하나만 적용한다.\n"
    "1. 상태 모순이 '예' 이면 -> reject\n"
    "2. 증거 상태가 contradicting 이면 -> dispute\n"
    "3. 위험도가 high_risk 이고 증거 상태가 none 이면 -> request_evidence\n"
    "4. 위험도가 high_risk 이고 증거 상태가 verified 이면 -> accept_as_belief\n"
    f"5. 위험도가 low_risk 이고 신뢰도가 {config.TRUST_ACCEPT_THRESHOLD} 이상이면"
    " -> accept_as_belief\n"
    f"6. 위험도가 low_risk 이고 신뢰도가 {config.TRUST_ACCEPT_THRESHOLD} 미만이면"
    " -> defer\n"
    "이 표가 결정의 유일한 근거다. 표가 지정한 결정을 그대로 고른다."
)


def _material(predicate: str, evidence: str, trust: int, contradicts: bool) -> str:
    return (
        "[판단 재료]\n"
        f"- 손님 주장 종류: {predicate} "
        f"({config.PREDICATE_LABELS.get(predicate, predicate)})\n"
        f"- 위험도: {config.risk_of(predicate)}\n"
        f"- 증거 상태: {evidence}\n"
        f"- 신뢰도: {trust}\n"
        f"- 상태 모순: {'예' if contradicts else '아니오'}"
    )


SPEECH_EXAMPLES = (
    "판단별 말투 예시:\n"
    "  request_evidence — 「그런 기록은 내 장부에 없어요. 영수증이나 예약증을 보여주겠어요?」\n"
    "  dispute — 「내 장부에는 그 반대로 적혀 있어요. 다시 확인해 보죠.」\n"
    "  defer — 「지금은 확인할 길이 없네요. 확인되면 그때 말씀드릴게요.」\n"
    "  reject — 「그건 지금 가게 사정과 맞지 않아요.」\n"
    "  accept_as_belief — 「그렇군요. 그 말씀은 기억해 두겠어요.」\n"
    "확인되지 않은 것을 확정된 사실처럼 말하지 않는다. "
    "주지 않을 물건을 준다고 말하지 않는다."
)

GROUND_BY_DECISION = {
    "request_evidence": "{what}에 대한 기록이 내 장부에 없다",
    "dispute": "{what}에 대해 내 장부는 손님 말과 반대다",
    "accept_as_belief": "{what}에 대해 손님이 내놓은 증거를 확인했다",
    "defer": "{what}을 지금 확인할 근거가 없다",
    "reject": "{what}이 현재 가게 상태와 모순된다",
}


def _grounds(engine, decision: str, predicate: str, claim_object: str) -> str:
    item = claim_object if claim_object in config.PRICES else ""
    label = config.PREDICATE_LABELS.get(predicate, predicate)
    what = f"손님이 말한 {item} 건" if item else f"손님이 말한 '{label}'"
    text = GROUND_BY_DECISION[decision].format(what=what)
    if item:
        text += (f" (현재 {item}: 예약 {engine.fact(f'shop.reserved.{item}')}개, "
                 f"손님 인벤 {engine.fact(f'player.inventory.{item}')}개, "
                 f"재고 {engine.fact(f'shop.stock.{item}')}개)")
    return text + "."


SOURCED_SPEECH_EXAMPLES = (
    "근거 블록의 world_truth는 게임 엔진이 기록한 현재 상태다. "
    "policy_inputs의 증거·신뢰도·상태 모순은 시나리오에서 제공된 값이다. "
    "evidence_verified가 false이면 증거를 확인했다고 말하지 않는다. "
    "믿기로 한 것과 확인된 세계 사실은 구분한다. "
    "기억의 내믿음에 붙은 verified 표시는 정책 승격 기록이며 외부 증거 검증과 같지 않다. "
    "엔진에 없는 약속·선금 기록의 존재나 부재를 수량만 보고 지어내지 않는다.\n"
    "판단별 말투 예시:\n"
    "  request_evidence — 「자네, 그 말씀을 뒷받침할 증거를 보여주겠어요?」\n"
    "  dispute — 「서로 다른 내용이 있어 확인이 필요해요.」\n"
    "  defer — 「아직 확인되지 않아 판단을 미룰게요.」\n"
    "  reject — 「그 요청은 지금 받아들이기 어려워요.」\n"
    "  accept_as_belief — 「자네의 말씀은 기억해 둘게요.」"
)


def _engine_grounding(
    engine: GameEngine, predicate: str, claim_object: str,
    evidence: str, trust: int, contradicts: bool,
) -> str:
    return json.dumps({
        "world_truth": engine.world(),
        "world_truth_source": "game_engine",
        "policy_inputs": {
            "claim_predicate": predicate,
            "claim_object": claim_object,
            "claim_source": "slm_nlu",
            "risk": config.risk_of(predicate),
            "evidence": evidence,
            "evidence_verified": evidence == "verified",
            "trust": trust,
            "contradicts_state": contradicts,
            "evidence_trust_contradiction_source": "scenario_fixture",
        },
    }, ensure_ascii=False, sort_keys=True)


def _hash(messages: list[dict]) -> str:
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class TurnRecord:
    turn: int
    player: str
    expected_decision: str
    evidence: str
    risk_truth: str
    nlu: dict | None
    nlu_predicate: str
    nlu_schema_ok: bool
    nlu_latency_ms: int
    decision: str
    decision_actor: str
    response: str
    response_schema_ok: bool
    response_latency_ms: int
    prompt: str
    prompt_hash: str
    world_version_before: int
    world_version_after: int
    belief_created: bool
    action: dict | None = None
    action_result: dict | None = None
    raw_response: str | None = None
    raw_response_schema_ok: bool | None = None
    output_actor: str = "slm"
    output_plan: dict | None = None
    guard_latency_ms: int = 0


@dataclass
class RunRecord:
    run_id: str
    condition: str
    seed: int
    scenario_id: str
    model: str
    embed_model: str
    trust: int
    turns: list[TurnRecord] = field(default_factory=list)
    final_world: dict = field(default_factory=dict)
    belief_count: int = 0
    refusal_count: int = 0

    def to_json(self) -> str:
        payload = asdict(self)
        for t in payload.get("turns", []):
            t["latency_ms"] = t["response_latency_ms"]
        return json.dumps(payload, ensure_ascii=False)


def _nlu(utterance: str, seed: int) -> llm.Completion:
    return llm.chat(
        [{"role": "system", "content": NLU_INSTRUCTION},
         {"role": "user", "content": utterance}],
        seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=NLU_SCHEMA,
    )


def _memory_block(memory, query: str, fields: tuple[str, ...]) -> str:
    return memory.context(query, fields)


def run_dialogue(scenario: dict, condition: str, seed: int,
                 db_path: str = ":memory:") -> RunRecord:
    spec = config.CONDITIONS[condition]
    engine = GameEngine(db_path)
    engine.reset(scenario.get("initial_facts"))
    memory = build_memory(condition, engine)
    trust = config.clamp_trust(scenario.get("trust", 1))

    record = RunRecord(
        run_id=f"{scenario['scenario_id']}__{condition}__s{seed}",
        condition=condition, seed=seed, scenario_id=scenario["scenario_id"],
        model=config.MODEL_NAME, embed_model=config.EMBED_MODEL_NAME, trust=trust,
    )

    for index, turn_spec in enumerate(scenario["turns"], start=1):
        player = turn_spec["player"]
        evidence = turn_spec.get("evidence", "none")
        memory.remember(index, "손님", player)

        nlu = _nlu(player, seed)
        predicate = (nlu.parsed or {}).get("claim_predicate", "none")
        if predicate not in config.CLAIM_PREDICATES:
            predicate = "none"
        claim_object = (nlu.parsed or {}).get("claim_object", "") or ""

        claim_id = None
        if predicate != "none":
            claim_id = engine.save_claim(index, player, predicate, claim_object, evidence)

        risk_truth = config.risk_of(turn_spec.get("truth_predicate", predicate))
        expected = turn_spec.get("expected_decision") or config.expected_decision(
            risk_truth, evidence, trust, turn_spec.get("contradicts_state", False)
        )

        context = _memory_block(memory, player, spec["fields"])
        base = (
            f"{config.PERSONA}\n\n"
            f"[지금 가게 상태]\n{shop_status(engine)}\n\n"
            f"[기억]\n{context}"
        )

        version_before = engine.version()
        if spec["decider"].startswith("decision_table"):
            policy_decision = config.expected_decision(
                config.risk_of(predicate), evidence, trust,
                turn_spec.get("contradicts_state", False),
            )
            extra = "" if spec["decider"] == "decision_table" else (
                f"[확인된 사실] {_grounds(engine, policy_decision, predicate, claim_object)}\n"
                f"{SPEECH_EXAMPLES}\n\n"
            )
            if spec["decider"] == "decision_table_sourced":
                ground = _engine_grounding(
                    engine, predicate, claim_object, evidence, trust,
                    turn_spec.get("contradicts_state", False),
                )
                extra = f"[엔진 근거]\n{ground}\n{SOURCED_SPEECH_EXAMPLES}\n\n"
            messages = [
                {"role": "system", "content":
                    f"{base}\n\n{extra}[정책 판단] {policy_decision} "
                    f"({DECISION_KO[policy_decision]})\n"
                    "이 판단에 맞춰 도르만으로서 1~2문장으로 답해라. "
                    "판단을 뒤집지 마라. JSON으로만 출력한다."},
                {"role": "user", "content": player},
            ]
            completion = llm.chat(messages, seed=seed, json_schema=SPEAK_SCHEMA)
            decision, actor = policy_decision, "policy_engine"
        else:
            guide = "" if spec["decider"] == "slm" else (
                _material(predicate, evidence, trust,
                          turn_spec.get("contradicts_state", False))
                + f"\n\n{RULE_BLOCK}\n\n"
            )
            messages = [
                {"role": "system", "content": f"{base}\n\n{guide}{DECIDE_INSTRUCTION}"},
                {"role": "user", "content": player},
            ]
            completion = llm.chat(messages, seed=seed, json_schema=DECIDE_SCHEMA)
            decision = (completion.parsed or {}).get("decision", "defer")
            if decision not in config.DECISIONS:
                decision = "defer"
            actor = spec["decider"]

        utterance = (completion.parsed or {}).get("utterance", completion.text) or ""
        raw_utterance = utterance
        guarded = spec.get("output") == "engine_renderer"
        belief_created = False
        if claim_id is not None:
            belief_created = engine.record_decision(
                index, claim_id, decision, actor=actor
            ) is not None

        engine.log_generated(index, utterance)
        if not guarded:
            memory.remember(index, "도르만", utterance)

        action, action_result = turn_spec.get("action"), None
        purchase = None
        if action and action.get("skill") == "buy":
            result = engine.buy(index, action["item"], action["quantity"])
            action_result = {"ok": result.ok, "reason": result.reason}
            purchase = result

        output_plan, guard_latency_ms = None, 0
        if guarded:
            guard_started = time.perf_counter()
            plan = make_speech_plan(
                engine, decision, evidence, player, predicate, claim_object,
                (nlu.parsed or {}).get("intent", "other"), purchase,
            )
            utterance = render_speech_plan(plan)
            output_plan = asdict(plan)
            guard_latency_ms = int((time.perf_counter() - guard_started) * 1000)
            memory.remember(index, "도르만", utterance)

        record.turns.append(TurnRecord(
            turn=index, player=player, expected_decision=expected, evidence=evidence,
            risk_truth=risk_truth, nlu=nlu.parsed, nlu_predicate=predicate,
            nlu_schema_ok=nlu.schema_ok, nlu_latency_ms=nlu.latency_ms,
            decision=decision, decision_actor=actor, response=utterance,
            response_schema_ok=True if guarded else completion.schema_ok,
            response_latency_ms=completion.latency_ms,
            prompt=json.dumps(messages, ensure_ascii=False), prompt_hash=_hash(messages),
            world_version_before=version_before, world_version_after=engine.version(),
            belief_created=belief_created, action=action, action_result=action_result,
            raw_response=raw_utterance if guarded else None,
            raw_response_schema_ok=completion.schema_ok if guarded else None,
            output_actor="engine_renderer" if guarded else "slm",
            output_plan=output_plan, guard_latency_ms=guard_latency_ms,
        ))

    record.final_world = engine.world()
    record.belief_count = len(engine.beliefs())
    record.refusal_count = len(engine.refusals())
    engine.close()
    return record
