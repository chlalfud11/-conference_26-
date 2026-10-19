"""M1P4 조건 러너. 사전등록 대상 (2026-10-15)."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from npc import config, llm
from npc.adapters import build_memory, shop_status
from npc.engine import GameEngine
from npc.runner import (
    NLU_SCHEMA, SPEAK_SCHEMA, NLU_INSTRUCTION, DECISION_KO,
    SOURCED_SPEECH_EXAMPLES, _engine_grounding, _hash, TurnRecord, RunRecord,
)
from ulw_policy_v2 import expected_decision_v2, risk_of_v2


def _nlu(utterance: str, seed: int) -> llm.Completion:
    return llm.chat(
        [{"role": "system", "content": NLU_INSTRUCTION},
         {"role": "user", "content": utterance}],
        seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=NLU_SCHEMA,
    )


def run_dialogue_v2(scenario: dict, seed: int, db_path: str = ":memory:") -> RunRecord:
    condition = "M1P4"
    spec = {
        "memory": "structured",
        "fields": ("type", "text", "source", "verified", "confidence"),
        "decider": "decision_table_v2",
    }
    
    engine = GameEngine(db_path)
    engine.reset(scenario.get("initial_facts"))
    memory = build_memory("M1P1", engine)
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
        speech_act = (nlu.parsed or {}).get("speech_act", "other")

        claim_id = None
        if predicate != "none":
            claim_id = engine.save_claim(index, player, predicate, claim_object, evidence)

        risk_truth = config.risk_of(turn_spec.get("truth_predicate", predicate))
        expected = turn_spec.get("expected_decision") or config.expected_decision(
            risk_truth, evidence, trust, turn_spec.get("contradicts_state", False)
        )

        context = memory.context(player, spec["fields"])
        base = (
            f"{config.PERSONA}\n\n"
            f"[지금 가게 상태]\n{shop_status(engine)}\n\n"
            f"[기억]\n{context}"
        )

        version_before = engine.version()
        
        policy_decision = expected_decision_v2(
            predicate, speech_act, evidence, trust,
            turn_spec.get("contradicts_state", False),
        )
        
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
        decision, actor = policy_decision, "policy_engine_v2"

        utterance = (completion.parsed or {}).get("utterance", completion.text) or ""
        
        belief_created = False
        if claim_id is not None:
            belief_created = engine.record_decision(
                index, claim_id, decision, actor=actor
            ) is not None

        engine.log_generated(index, utterance)
        memory.remember(index, "도르만", utterance)

        action, action_result = turn_spec.get("action"), None
        if action and action.get("skill") == "buy":
            result = engine.buy(index, action["item"], action["quantity"])
            action_result = {"ok": result.ok, "reason": result.reason}

        record.turns.append(TurnRecord(
            turn=index, player=player, expected_decision=expected, evidence=evidence,
            risk_truth=risk_truth, nlu=nlu.parsed, nlu_predicate=predicate,
            nlu_schema_ok=nlu.schema_ok, nlu_latency_ms=nlu.latency_ms,
            decision=decision, decision_actor=actor, response=utterance,
            response_schema_ok=completion.schema_ok,
            response_latency_ms=completion.latency_ms,
            prompt=json.dumps(messages, ensure_ascii=False), prompt_hash=_hash(messages),
            world_version_before=version_before, world_version_after=engine.version(),
            belief_created=belief_created, action=action, action_result=action_result,
        ))

    record.final_world = engine.world()
    record.belief_count = len(engine.beliefs())
    record.refusal_count = len(engine.refusals())
    engine.close()
    return record


def load_scenarios(path: Path) -> dict:
    scen = {}
    for f in path.glob("*.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        scen[s["scenario_id"]] = s
    return scen


if __name__ == "__main__":
    import argparse
    import datetime
    
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "run", "verify"])
    parser.add_argument("--scenarios", default="scenarios,scenarios_adversarial")
    parser.add_argument("--out", default="logs/policy_v2/runs.jsonl")
    args = parser.parse_args()
    
    CP = Path(__file__).parent
    scenario_dirs = [CP / d.strip() for d in args.scenarios.split(",")]
    out_path = CP / args.out
    freeze_path = CP / "logs/policy_v2/preregistration_freeze.json"
    
    all_scenarios = {}
    for d in scenario_dirs:
        if d.exists():
            all_scenarios.update(load_scenarios(d))
    
    if args.command == "freeze":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        sources = [
            "ulw_policy_v2.py",
            "ulw_policy_v2_run.py",
            "docs/ULW_정책v2_사전등록.md",
        ]
        for d in scenario_dirs:
            if d.exists():
                sources.extend(str(f.relative_to(CP)) for f in sorted(d.glob("*.json")))
        
        hashes = {}
        for src in sources:
            p = CP / src
            if p.exists():
                hashes[src] = hashlib.sha256(p.read_bytes()).hexdigest()
        
        freeze = {
            "frozen_at_utc": datetime.datetime.utcnow().isoformat(),
            "scenario_count": len(all_scenarios),
            "planned_runs": len(all_scenarios) * len(config.SEEDS),
            "seeds": config.SEEDS,
            "source_hashes": hashes,
        }
        freeze_path.write_text(json.dumps(freeze, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Frozen: {freeze_path}")
        print(f"Scenarios: {len(all_scenarios)}, Planned runs: {freeze['planned_runs']}")
    
    elif args.command == "run":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        first_inference = None
        
        with open(out_path, "a", encoding="utf-8") as f:
            for sid in sorted(all_scenarios.keys()):
                scenario = all_scenarios[sid]
                for seed in config.SEEDS:
                    run_id = f"{sid}__M1P4__s{seed}"
                    print(f"Running {run_id}...")
                    
                    record = run_dialogue_v2(scenario, seed)
                    
                    if first_inference is None:
                        first_inference = datetime.datetime.utcnow().isoformat()
                    
                    f.write(record.to_json() + "\n")
                    f.flush()
        
        last_inference = datetime.datetime.utcnow().isoformat()
        freeze["first_inference_utc"] = first_inference
        freeze["last_inference_utc"] = last_inference
        freeze_path.write_text(json.dumps(freeze, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Done. Output: {out_path}")
    
    elif args.command == "verify":
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        
        all_match = True
        for src, expected in freeze["source_hashes"].items():
            p = CP / src
            if p.exists():
                actual = hashlib.sha256(p.read_bytes()).hexdigest()
                if actual != expected:
                    print(f"MISMATCH: {src}")
                    all_match = False
            else:
                print(f"MISSING: {src}")
                all_match = False
        
        print(f"Verification: {'PASS' if all_match else 'FAIL'}")
