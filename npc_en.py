"""English clothing-shop NPC for the ABCD validation run (docs/ABCD_NPC_초안.md).

npc/ is not edited. install() swaps the shop catalogue in config; run_dialogue() mirrors
npc.runner.run_dialogue for the two deciders this experiment uses (slm, decision_table)
with every prompt string in English.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from npc import config, llm, runner
from npc.adapters import KIND_LABELS, build_memory
from npc.engine import GameEngine

HANGUL = re.compile(r"[\uac00-\ud7a3]")

PERSONA_EN = (
    'You are Morgan, the clerk at "Northgate Outfitters", a clothing shop in a modern-day life-sim game.\n'
    "- Blunt and strict about money and records, but you do not ignore a customer in real trouble.\n"
    "- You trust only the shop ledger. You remember stock, prices and orders precisely.\n"
    "- You dislike empty talk and exaggeration. Speak 1-2 sentences per turn.\n"
    "- Never invent an item, an order, a payment or a promise. If the ledger does not show it, "
    "say you cannot confirm it.\n"
    '- Speak polite, plain English. Call the player "you".\n'
    "Examples:\n"
    '  "I\'ll check the ledger first. Do you have the order number or the receipt?"\n'
    '  "Nice try, but I can\'t refund something the ledger doesn\'t show."\n'
    '  "Got it. Thanks for coming in."'
)

BRANDS = ("Calvin Klein", "Guess", "Michael Kors", "Tommy Hilfiger")
TYPES = ("boots", "jacket", "jeans", "shirt")
CATALOG = [f"{b} {t}" for b in BRANDS for t in TYPES]

PREDICATE_EN = {
    "reserved_item": "placed an order that has not arrived",
    "paid_deposit": "paid (was charged) for something",
    "promised_reward": "was promised a reward",
    "promised_discount": "was given a discount or promo code",
    "completed_errand": "already did the requested action (e.g. returned the item)",
    "owns_item": "already bought or owns the item",
    "heard_rumor": "heard a rumor",
    "none": "no claim",
}

DECISION_EN = {
    "accept_as_belief": "believe the customer",
    "reject": "do not believe it",
    "dispute": "it contradicts what I know",
    "defer": "postpone the judgement",
    "request_evidence": "ask for evidence",
}

NLU_INSTRUCTION = (
    "Structure the customer's message as JSON.\n\n"
    "claim_predicate is the kind of thing the customer asserts to be true.\n"
    + "\n".join(f"- {k}: {v}" for k, v in PREDICATE_EN.items())
    + "\n\nUse none for greetings, questions and plain purchase requests with no claim.\n"
    "If the customer mentions a past order, payment, promo code, return or purchase, pick that predicate.\n"
    "claim_object is a short English name of the item or thing the claim is about.\n"
    "Output only JSON."
)

DECIDE_INSTRUCTION = (
    "Choose how to take what the customer just said, and answer as Morgan in 1-2 sentences.\n"
    + "\n".join(f"- {k}: {v}" for k, v in DECISION_EN.items())
    + "\nOutput only JSON."
)

KIND_EN = {
    "world_truth": "world fact",
    "committed_event": "committed event",
    "player_claim": "customer claim",
    "npc_belief": "my belief",
    "utterance": "dialogue",
}


PERSONA_FIX = PERSONA_EN.replace(
    "- You trust only the shop ledger. You remember stock, prices and orders precisely.\n",
    "- You trust the ledger. If it shows a record matching the verified customer's claim, that record IS the proof: "
    "do not ask for receipts or order numbers. Ask for evidence only when the ledger has no such record.\n",
).replace('  "Got it. Thanks for coming in."', '  "Yes, I see your return from Nov 10 in the ledger. The refund is pending; I\'ll check on it."\n  "Got it. Thanks for coming in."')
DECIDE_FIX = DECIDE_INSTRUCTION.replace(
    "\nOutput only JSON.",
    "\nA ledger record matching the verified customer's claim counts as verified evidence.\nOutput only JSON.",
)
assert "IS the proof" in PERSONA_FIX and "Yes, I see your return" in PERSONA_FIX and DECIDE_FIX != DECIDE_INSTRUCTION
MODE = {"ledger": "line", "instr": "base"}
LEDGER_DIR = Path(__file__).parent / "results" / "abcd" / "ledgers"


def persona() -> str:
    return PERSONA_FIX if MODE["instr"] == "fix" else PERSONA_EN


def decide_instruction() -> str:
    return DECIDE_FIX if MODE["instr"] == "fix" else DECIDE_INSTRUCTION


def install(ledger: str = "line", instr: str = "base") -> None:
    assert ledger in ("line", "v2", "v3", "v4") and instr in ("base", "fix")
    MODE.update(ledger=ledger, instr=instr)
    config.PERSONA = PERSONA_EN
    config.PRICES = {item: 0 for item in CATALOG}
    config.INITIAL_STOCK = {item: 1 for item in CATALOG}
    KIND_LABELS.clear()
    KIND_LABELS.update(KIND_EN)


def assert_english() -> None:
    texts = [PERSONA_EN, PERSONA_FIX, DECIDE_FIX, NLU_INSTRUCTION, DECIDE_INSTRUCTION, *KIND_LABELS.values(),
             *config.INITIAL_STOCK, json.dumps(runner.NLU_SCHEMA), json.dumps(runner.DECIDE_SCHEMA)]
    bad = [t for t in texts if HANGUL.search(t)]
    assert not bad, bad
    assert config.PERSONA == PERSONA_EN


LEDGER_EN = {
    "promised_discount": "a promo code was issued to this customer and is still valid",
    "completed_errand": "a return from this customer was received",
    "paid_deposit": "this customer was charged twice for one purchase",
    "reserved_item": "this customer placed an order ({products}) that has not been delivered yet",
    "owns_item": "this customer bought {products} here",
}


def ledger_line(scenario: dict) -> str:
    claim = scenario["turns"][-1]
    if claim["evidence"] != "verified":
        return "- No ledger record about this customer's claim."
    products = ", ".join(scenario.get("initial_facts", {}).get("products", [])) or "an item"
    return "- Ledger record: " + LEDGER_EN[claim["truth_predicate"]].format(products=products.replace("_", " ")) + "."


def shop_status(engine: GameEngine, scenario: dict) -> str:
    stock = [f"- {item}: in stock {engine.fact(f'shop.stock.{item}')}" for item in CATALOG]
    if MODE["ledger"] == "v2":
        return "\n".join(stock) + "\n" + (LEDGER_DIR / f"{scenario['scenario_id']}.txt").read_text().rstrip()
    if MODE["ledger"] == "v3":
        return "\n".join(stock) + "\n" + (LEDGER_DIR.parent / "ledgers_v3" / f"{scenario['scenario_id']}.txt").read_text().rstrip()
    if MODE["ledger"] == "v4":
        import ledger_vdb
        meta = json.loads((LEDGER_DIR.parent / "ledgers_v3" / f"{scenario['scenario_id']}.json").read_text())
        hits = ledger_vdb.search(f"{meta['customer']} {scenario['turns'][-1]['player']}", scenario["scenario_id"][-1])
        return ("\n".join(stock) + "\n" + meta["header"] + "\nLedger search results (top 5 of the shop ledger):\n"
                + "\n".join("  " + h["text"] for h in hits))
    return "\n".join(stock + ["[Ledger]", ledger_line(scenario)])


def memory_context(memory) -> str:
    items = []
    for row in memory.engine.claims():
        items.append((row["turn_id"], f"[customer claim] {row['raw_text']} (source: player, verified: {row['evidence']})"))
    for row in memory.engine.beliefs():
        items.append((row["turn_id"], f"[my belief] I believe the customer {PREDICATE_EN.get(row['predicate'], row['predicate'])}"
                      f" ({row['object']}) (source: {row['accepted_by']})"))
    for item in memory._utterances:
        items.append((item.turn, f"[dialogue] {item.text}"))
    return "\n".join(t for _, t in sorted(items, key=lambda p: p[0])) or "(no records yet)"


def run_dialogue(scenario: dict, condition: str, seed: int) -> runner.RunRecord:
    spec = config.CONDITIONS[condition]
    assert spec["decider"] in ("slm", "decision_table") and spec["memory"] == "structured", condition
    engine = GameEngine(":memory:")
    engine.reset()
    memory = build_memory(condition, engine)
    trust = config.clamp_trust(scenario.get("trust", 1))
    record = runner.RunRecord(
        run_id=f"{scenario['scenario_id']}__{condition}__s{seed}", condition=condition, seed=seed,
        scenario_id=scenario["scenario_id"], model=config.MODEL_NAME,
        embed_model=config.EMBED_MODEL_NAME, trust=trust,
    )
    for index, turn_spec in enumerate(scenario["turns"], start=1):
        player, evidence = turn_spec["player"], turn_spec.get("evidence", "none")
        memory.remember(index, "Customer", player)
        nlu = llm.chat([{"role": "system", "content": NLU_INSTRUCTION}, {"role": "user", "content": player}],
                       seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
        predicate = (nlu.parsed or {}).get("claim_predicate", "none")
        if predicate not in config.CLAIM_PREDICATES:
            predicate = "none"
        claim_object = (nlu.parsed or {}).get("claim_object", "") or ""
        claim_id = engine.save_claim(index, player, predicate, claim_object, evidence) if predicate != "none" else None
        risk_truth = config.risk_of(turn_spec.get("truth_predicate", predicate))
        expected = config.expected_decision(risk_truth, evidence, trust, turn_spec.get("contradicts_state", False))
        base = (f"{persona()}\n\n[Current shop state]\n{shop_status(engine, scenario)}\n\n"
                f"[Memory]\n{memory_context(memory)}")
        version_before = engine.version()
        if spec["decider"] == "decision_table":
            decision = config.expected_decision(config.risk_of(predicate), evidence, trust,
                                                turn_spec.get("contradicts_state", False))
            messages = [{"role": "system", "content":
                         f"{base}\n\n[Policy decision] {decision} ({DECISION_EN[decision]})\n"
                         "Answer as Morgan in 1-2 sentences, consistent with this decision. "
                         "Do not overturn it. Output only JSON."},
                        {"role": "user", "content": player}]
            completion = llm.chat(messages, seed=seed, json_schema=runner.SPEAK_SCHEMA)
            actor = "policy_engine"
        else:
            messages = [{"role": "system", "content": f"{base}\n\n{decide_instruction()}"},
                        {"role": "user", "content": player}]
            completion = llm.chat(messages, seed=seed, json_schema=runner.DECIDE_SCHEMA)
            decision = (completion.parsed or {}).get("decision", "defer")
            if decision not in config.DECISIONS:
                decision = "defer"
            actor = "slm"
        utterance = (completion.parsed or {}).get("utterance", completion.text) or ""
        belief_created = claim_id is not None and engine.record_decision(index, claim_id, decision, actor=actor) is not None
        engine.log_generated(index, utterance)
        memory.remember(index, "Morgan", utterance)
        record.turns.append(runner.TurnRecord(
            turn=index, player=player, expected_decision=expected, evidence=evidence, risk_truth=risk_truth,
            nlu=nlu.parsed, nlu_predicate=predicate, nlu_schema_ok=nlu.schema_ok, nlu_latency_ms=nlu.latency_ms,
            decision=decision, decision_actor=actor, response=utterance, response_schema_ok=completion.schema_ok,
            response_latency_ms=completion.latency_ms, prompt=json.dumps(messages, ensure_ascii=False),
            prompt_hash=runner._hash(messages), world_version_before=version_before,
            world_version_after=engine.version(), belief_created=belief_created,
            raw_response=completion.text,
        ))
    record.final_world = engine.world()
    record.belief_count = len(engine.beliefs())
    record.refusal_count = len(engine.refusals())
    engine.close()
    return record
