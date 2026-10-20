"""ABCD v4 dialogue runner (.omo/plans/abcd-v4-answer-key.md).

Reads scenarios_abcd4/ and the shop ledger only. Evidence for the decision table comes from the engine's
ledger lookup, and the memory block carries no verification flag.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import abcd4_ledger as LG
import ledger_vdb
import npc_en
from npc import config, llm, runner
from npc.adapters import build_memory
from npc.engine import GameEngine

ROOT = Path(__file__).parent
SCEN = ROOT / ("scenarios_abcd5h" if LG.HELDOUT else "scenarios_abcd4")
CONDITIONS = {"F-M1P0": ("full", "M1P0"), "S-M1P0": ("search", "M1P0"), "F-M1P1": ("full", "M1P1")}
FOLLOW_UP = {"F-M1P1FC": ("full", "M1P1"), "F-M1P1RV": ("full", "M1P1")}
TOOL_CONDITION = {"T-M1P0": ("tool", "M1P0")}
TOOL_SCHEMA = {"type": "object", "properties": {
    "call": {"type": "boolean"},
    "claim_type": {"type": "string", "enum": [*config.CLAIM_PREDICATES, "none"]}},
    "required": ["call", "claim_type"], "additionalProperties": False}
TOOL_INSTRUCTION = ("You have one tool: lookup(claim_type). It returns this customer's ledger records of that type, "
                    "with their dates. claim_type is one of: "
                    + "; ".join(f"{p} = the customer {npc_en.PREDICATE_EN[p]}" for p in config.CLAIM_PREDICATES)
                    + ". Decide whether to call the tool for the customer's message. Output only JSON.")
CUE_CANDIDATES = (
    ("promised_discount", re.compile(r"\b(promo|code|coupon|discount)\b", re.I)),
    ("completed_errand", re.compile(r"\b(return(ed)?|refund(ed)?)\b", re.I)),
    ("paid_deposit", re.compile(r"\b(charg(e|ed)|bill(ed)?|paid|pay)\b", re.I)),
    ("reserved_item", re.compile(r"\b(order(ed)?|deliver(y|ed)|shipp(ed|ing))\b", re.I)),
    ("owns_item", re.compile(r"\b(bought|purchas(e|ed)|receipt)\b", re.I)),
)
REVERIFY_SCHEMA = {"type": "object", "properties": {"asserts": {"type": "boolean"}},
                   "required": ["asserts"], "additionalProperties": False}
REVERIFY_INSTRUCTION = ("Read the customer's message. Does the customer assert, as a fact about the past, "
                        "that they {claim}? Answer true or false. Output only JSON.")
TRANSACTION_CUE = re.compile(r"\b(promo|code|coupon|discount|order(ed)?|return(ed)?|refund(ed)?|charg(e|ed)|bill(ed)?|bought|purchas(e|ed)|receipt|deliver(y|ed)|shipp(ed|ing)|paid|pay)\b", re.I)


def install():
    npc_en.install(instr="fix")
    npc_en.assert_english()


def scenarios():
    return {p.stem: json.loads(p.read_text()) for p in sorted(SCEN.glob("*.json"))}


def ledger_block(engine, scenario, view, player, rows, today):
    stock = [f"- {item}: in stock {engine.fact(f'shop.stock.{item}')}" for item in npc_en.CATALOG]
    header = (f"[Ledger - Northgate Outfitters]\nToday: {today}\n"
              f"Customer on this chat: {scenario['customer']} | member: {scenario['member_level']} | "
              "identity: VERIFIED at chat start (name + zip)")
    if view == "tool":
        body = "Records for this customer: not shown; use the lookup tool."
    elif view == "full":
        account = LG.split_who(scenario["customer"])[1]
        own = [LG.render(r) for r in rows if r["account"] == account]
        body = "Records for this customer:\n" + ("\n".join("  " + t for t in own) or "  (none)")
    else:
        hits = ledger_vdb.search4(f"{scenario['customer']} {player}")
        body = "Ledger search results (top 5 of the shop ledger):\n" + "\n".join("  " + h["text"] for h in hits)
    return "\n".join(stock) + "\n" + header + "\n" + body


def memory_context(memory) -> str:
    items = [(r["turn_id"], f"[customer claim] {r['raw_text']} (source: player)") for r in memory.engine.claims()]
    items += [(r["turn_id"], f"[my belief] I believe the customer {npc_en.PREDICATE_EN.get(r['predicate'], r['predicate'])}"
               f" ({r['object']}) (source: {r['accepted_by']})") for r in memory.engine.beliefs()]
    items += [(u.turn, f"[dialogue] {u.text}") for u in memory._utterances]
    return "\n".join(t for _, t in sorted(items, key=lambda p: p[0])) or "(no records yet)"


def run_dialogue4(scenario: dict, condition: str, seed: int, rows: list, today: str) -> runner.RunRecord:
    view, base_condition = {**CONDITIONS, **FOLLOW_UP, **TOOL_CONDITION}[condition]
    fail_closed = condition in FOLLOW_UP
    spec = config.CONDITIONS[base_condition]
    engine = GameEngine(":memory:")
    engine.reset()
    memory = build_memory(base_condition, engine)
    trust = config.clamp_trust(scenario["trust"])
    account = LG.split_who(scenario["customer"])[1]
    record = runner.RunRecord(
        run_id=f"{scenario['scenario_id']}__{condition}__s{seed}", condition=condition, seed=seed,
        scenario_id=scenario["scenario_id"], model=config.MODEL_NAME, embed_model=config.EMBED_MODEL_NAME, trust=trust,
    )
    for index, turn in enumerate(scenario["turns"], start=1):
        player, stated = turn["player"], turn.get("date")
        tool = None
        memory.remember(index, "Customer", player)
        nlu = llm.chat([{"role": "system", "content": npc_en.NLU_INSTRUCTION}, {"role": "user", "content": player}],
                       seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
        predicate = (nlu.parsed or {}).get("claim_predicate", "none")
        if predicate not in config.CLAIM_PREDICATES:
            predicate = "none"
        claim_object = (nlu.parsed or {}).get("claim_object", "") or ""
        evidence = LG.lookup(rows, account, predicate, stated)
        reverify = None
        if condition == "F-M1P1RV" and predicate == "none" and TRANSACTION_CUE.search(player):
            candidates, answers = [p for p, pattern in CUE_CANDIDATES if pattern.search(player)], {}
            for candidate in candidates:
                reply = llm.chat([{"role": "system", "content": REVERIFY_INSTRUCTION.format(claim=npc_en.PREDICATE_EN[candidate])},
                                  {"role": "user", "content": player}],
                                 seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=REVERIFY_SCHEMA)
                answers[candidate] = bool((reply.parsed or {}).get("asserts"))
                if answers[candidate]:
                    predicate = candidate
                    evidence = LG.lookup(rows, account, predicate, stated)
                    break
            reverify = {"candidates": candidates, "answers": answers, "chosen": predicate if predicate != "none" else None}
        claim_id = engine.save_claim(index, player, predicate, claim_object, evidence) if predicate != "none" else None
        shop = ledger_block(engine, scenario, view, player, rows, today)
        stated_line = f"\nCustomer-stated date: {stated}" if stated else ""
        base = (f"{npc_en.persona()}\n\n[Current shop state]\n{shop}{stated_line}\n\n"
                f"[Memory]\n{memory_context(memory)}")
        version_before = engine.version()
        if spec["decider"] == "decision_table":
            risk = config.risk_of(predicate)
            if fail_closed and predicate == "none" and TRANSACTION_CUE.search(player):
                risk = "high_risk"
            decision = config.expected_decision(risk, evidence, trust)
            messages = [{"role": "system", "content":
                         f"{base}\n\n[Policy decision] {decision} ({npc_en.DECISION_EN[decision]})\n"
                         "Answer as Morgan in 1-2 sentences, consistent with this decision. "
                         "Do not overturn it. Output only JSON."},
                        {"role": "user", "content": player}]
            completion = llm.chat(messages, seed=seed, json_schema=runner.SPEAK_SCHEMA)
            actor = "policy_engine"
        else:
            if view == "tool":
                call = llm.chat([{"role": "system", "content": f"{base}\n\n{TOOL_INSTRUCTION}"},
                                 {"role": "user", "content": player}],
                                seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=TOOL_SCHEMA)
                kind = (call.parsed or {}).get("claim_type", "none")
                called = bool((call.parsed or {}).get("call")) and kind in config.CLAIM_PREDICATES
                found = [LG.render(r) for r in rows if r["account"] == account and LG.matches(kind, r)] if called else []
                tool = {"call": called, "claim_type": kind, "result_rows": found, "schema_ok": call.schema_ok}
                if called:
                    base += f"\n\n[Tool result] lookup({kind}):\n" + ("\n".join("  " + t for t in found) or "  (no records)")
            messages = [{"role": "system", "content": f"{base}\n\n{npc_en.decide_instruction()}"},
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
            turn=index, player=player, expected_decision="", evidence=evidence, risk_truth="",
            nlu={**(nlu.parsed or {}), "reverify": reverify} if reverify else {**(nlu.parsed or {}), "tool": tool} if tool else nlu.parsed, nlu_predicate=predicate, nlu_schema_ok=nlu.schema_ok, nlu_latency_ms=nlu.latency_ms,
            decision=decision, decision_actor=actor, response=utterance, response_schema_ok=completion.schema_ok,
            response_latency_ms=completion.latency_ms, prompt=json.dumps(messages, ensure_ascii=False),
            prompt_hash=runner._hash(messages), world_version_before=version_before,
            world_version_after=engine.version(), belief_created=belief_created, raw_response=completion.text,
        ))
    record.final_world = engine.world()
    record.belief_count = len(engine.beliefs())
    record.refusal_count = len(engine.refusals())
    engine.close()
    return record
