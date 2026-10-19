"""Recorded-input diagnostics; never changes product prompts or source data.

Artifact dictionaries follow the existing runner's JSON style. Semantic review
is supplied by the executor, not inferred from regexes or an external judge.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

from . import config, llm, runner
from .adapters import MemoryItem, StructuredMemory, shop_status

CARDS = (
    ("S05_v1", 3), ("S05_v1", 7), ("S06_v3", 4), ("S07_v1", 1),
    ("S12_v1", 2), ("S06_v2", 2), ("S05_v1", 1), ("S05_v1", 6),
    ("S07_v1", 2), ("S08_v3", 2), ("S11_v1", 2), ("S11_v2", 2),
)
SEEDS = (11, 29, 47)
SPEECH_VARIANTS = ("B", "E", "H", "C", "I")
NLU_VARIANTS = ("current", "context", "prefix")
OFFICIAL_PREFIX = "You are EXAONE model from LG AI Research, a helpful assistant."
OFFICIAL_SOURCE = (
    "https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
)
SEMANTIC_FLAGS = (
    "unsupported_assertion", "policy_contradiction", "inappropriate_greeting",
    "inappropriate_purchase", "inappropriate_rumor", "blanket_refusal",
)
CRITERIA = {
    "nlu": "36 classifications: improve total predicate accuracy over current; "
           "do not worsen greeting or simple-purchase controls.",
    "speech": "36 generations: reduce unsupported assertions or policy contradictions "
              "without increasing either; no blanket refusal of verified claims, "
              "unverified rumors or normal product inquiries.",
    "baseline_zero": "No improvement demonstrated on a card with zero baseline errors.",
    "scope": "Selected diagnostic cases only; not a general hallucination rate.",
}


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_hash(value: dict | list) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def source_manifest(root: Path) -> dict[str, str]:
    paths = [root / "logs/runs.jsonl", root / "m1p2_prompt_replay.py"]
    paths += sorted((root / "npc").glob("*.py"))
    paths += [root / "scenarios" / f"{name}.json" for name in sorted({s for s, _ in CARDS})]
    return {
        str(path.relative_to(root)): sha256(path) for path in paths
        if path.name != "root_cause_probe.py"
    }


def _stable_rows(rows: list) -> list[dict]:
    return [{key: value for key, value in dict(row).items() if key != "created_at"}
            for row in rows]


def _messages(card: dict, context: str, guidance: str) -> list[dict]:
    base = (
        f"{config.PERSONA}\n\n[지금 가게 상태]\n{card['shop_status']}\n\n"
        f"[기억]\n{context}"
    )
    decision = card["decision"]
    return [
        {"role": "system", "content":
         f"{base}\n\n[엔진 근거]\n{card['grounding']}\n{guidance}\n\n"
         f"[정책 판단] {decision} ({runner.DECISION_KO[decision]})\n"
         "이 판단에 맞춰 도르만으로서 1~2문장으로 답해라. "
         "판단을 뒤집지 마라. JSON으로만 출력한다."},
        {"role": "user", "content": card["player"]},
    ]


def reconstruct(root: Path) -> tuple[list[dict], list[dict]]:
    """Run the real runner with stored NLU/speech, observing before speech."""
    records = read_rows(root / "logs/runs.jsonl")
    cards, annotations = [], []
    old_chat, old_build = llm.chat, runner.build_memory
    for scenario_id in sorted({name for name, _ in CARDS}):
        matches = [row for row in records if row["condition"] == "M1P2G"
                   and row["seed"] == 11 and row["scenario_id"] == scenario_id]
        if len(matches) != 1:
            raise ValueError(f"Expected one original M1P2G seed11 run: {scenario_id}")
        original = matches[0]
        scenario = read_json(root / "scenarios" / f"{scenario_id}.json")
        index, nlu_call = 0, True
        memory: StructuredMemory | None = None

        def build(condition: str, engine: runner.GameEngine) -> StructuredMemory:
            nonlocal memory
            built = old_build(condition, engine)
            if not isinstance(built, StructuredMemory):
                raise ValueError("Freeze requires actual StructuredMemory")
            memory = built
            return built

        def replay(messages: list[dict], seed: int,
                   max_tokens: int = config.MAX_TOKENS,
                   json_schema: dict | None = None) -> llm.Completion:
            nonlocal index, nlu_call
            stored = original["turns"][index]
            if nlu_call:
                parsed = stored["nlu"]
                nlu_call = False
            else:
                if memory is None:
                    raise ValueError("Replay memory was not constructed")
                engine = memory.engine
                turn = index + 1
                spec = scenario["turns"][index]
                predicate = (stored["nlu"] or {}).get("claim_predicate", "none")
                if predicate not in config.CLAIM_PREDICATES:
                    predicate = "none"
                object_ = (stored["nlu"] or {}).get("claim_object", "") or ""
                decision = config.expected_decision(
                    config.risk_of(predicate), spec.get("evidence", "none"),
                    config.clamp_trust(scenario.get("trust", 1)),
                    spec.get("contradicts_state", False),
                )
                if (scenario_id, turn) in CARDS:
                    grounding = runner._engine_grounding(
                        engine, predicate, object_, spec.get("evidence", "none"),
                        config.clamp_trust(scenario.get("trust", 1)),
                        spec.get("contradicts_state", False),
                    )
                    card = {
                        "card_id": f"{scenario_id}/t{turn}", "scenario_id": scenario_id,
                        "turn": turn, "source_run_id": original["run_id"],
                        "player": stored["player"], "parsed_nlu": stored["nlu"],
                        "nlu_predicate": predicate, "decision": decision,
                        "decision_source": "policy_engine_from_stored_nlu",
                        "fields": list(config.CONDITIONS["M1P2G"]["fields"]),
                        "memory_items": [asdict(item) for item in memory._items()],
                        "utterances": [asdict(item) for item in memory._utterances],
                        "claims": _stable_rows(engine.claims()),
                        "beliefs": _stable_rows(engine.beliefs()),
                        "decisions": _stable_rows(engine.decisions()),
                        "events": _stable_rows(engine.events()),
                        "refusals": _stable_rows(engine.refusals()),
                        "current_state": engine.world(), "world_version": engine.version(),
                        "shop_status": shop_status(engine), "grounding": grounding,
                        "policy_inputs": json.loads(grounding)["policy_inputs"],
                        "pending_action": spec.get("action"),
                        "action_phase": "not_executed",
                        "preceding_user_turns": [
                            item["player"] for item in scenario["turns"][max(0, index - 2):index]
                        ],
                        "original_messages": messages,
                        "original_prompt_hash": stored["prompt_hash"],
                        "reconstructed_prompt_hash": runner._hash(messages),
                    }
                    card["exposure_counts"] = {
                        kind: sum(item["kind"] == kind for item in card["memory_items"])
                        for kind in ("player_claim", "npc_belief", "committed_event")
                    }
                    card["exposure_counts"]["npc_utterance"] = sum(
                        item["kind"] == "utterance" and item["source"] == "도르만"
                        for item in card["memory_items"]
                    )
                    context = "\n".join(
                        MemoryItem(**item).render(tuple(card["fields"]))
                        for item in card["memory_items"]
                    ) or "(아직 기록이 없음)"
                    if _messages(card, context, runner.SOURCED_SPEECH_EXAMPLES) != messages:
                        raise ValueError(f"Structural reconstruction mismatch: {card['card_id']}")
                    if decision != stored["decision"]:
                        raise ValueError(f"Actual policy mismatch: {card['card_id']}")
                    cards.append(card)
                    annotations.append({
                        "card_id": card["card_id"],
                        "truth_predicate": spec.get("truth_predicate", predicate),
                        "expected_decision": stored["expected_decision"],
                        "forbidden_assertions": spec.get("forbidden_assertions", []),
                        "required_markers": spec.get("required_markers", []),
                        "scored": spec.get("scored", False),
                        "source": f"scenarios/{scenario_id}.json/turns/{index}",
                        "control": (
                            "verified_claim" if spec.get("evidence") == "verified" else
                            "rumor" if spec.get("truth_predicate") == "heard_rumor" else
                            "purchase" if spec.get("action", {}).get("skill") == "buy" else
                            "greeting" if turn == 1 else
                            "product_inquiry" if scenario_id == "S08_v3" else "boundary"
                        ),
                    })
                parsed = {"utterance": stored["response"]}
                index += 1
                nlu_call = True
            return llm.Completion(
                text=json.dumps(parsed, ensure_ascii=False), parsed=parsed,
                schema_ok=stored["nlu_schema_ok"] if not nlu_call else stored["response_schema_ok"],
                latency_ms=0, prompt_tokens=0, completion_tokens=0,
            )

        llm.chat, runner.build_memory = replay, build
        try:
            result = runner.run_dialogue(scenario, "M1P2G", 11)
            if index != len(original["turns"]) or result.final_world != original["final_world"]:
                raise ValueError(f"Stored replay state mismatch: {scenario_id}")
        finally:
            llm.chat, runner.build_memory = old_chat, old_build
            if memory is not None:
                memory.engine.close()
    order = {f"{name}/t{turn}": i for i, (name, turn) in enumerate(CARDS)}
    return (sorted(cards, key=lambda row: order[row["card_id"]]),
            sorted(annotations, key=lambda row: order[row["card_id"]]))


def freeze(out: Path, root: Path = config.ROOT) -> dict:
    before = source_manifest(root)
    cards, labels = reconstruct(root)
    matched = sum(c["original_prompt_hash"] == c["reconstructed_prompt_hash"] for c in cards)
    if matched != 12 or len(cards) != 12:
        raise ValueError(f"Freeze prerequisite failed: {matched}/{len(cards)}, required 12/12")
    if before != source_manifest(root):
        raise ValueError("Original source files changed during freeze")
    summary = {
        "schema_version": 1, "source_root": str(root.resolve()),
        "source_sha256": before, "matched": matched, "compared": len(cards),
        "pass": True, "truth_labels_separate": True, "criteria": CRITERIA,
        "official_prefix": OFFICIAL_PREFIX, "official_prefix_source": OFFICIAL_SOURCE,
        "snapshots_sha256": artifact_hash(cards), "card_annotations_sha256": artifact_hash(labels),
        "exposure_counts": {card["card_id"]: card["exposure_counts"] for card in cards},
    }
    if (out / "manifest.json").exists():
        if read_json(out / "manifest.json") != summary or read_rows(out / "snapshots.jsonl") != cards:
            raise ValueError("Refusing to replace a different freeze")
        if read_rows(out / "card_annotations.jsonl") != labels:
            raise ValueError("Refusing to replace different truth annotations")
    else:
        write_rows(out / "snapshots.jsonl", cards)
        write_rows(out / "card_annotations.jsonl", labels)
        write_json(out / "manifest.json", summary)
    print(f"FREEZE_PASS {matched}/12")
    return summary


def load_frozen(out: Path) -> tuple[list[dict], dict[str, dict]]:
    manifest = read_json(out / "manifest.json")
    if not manifest["pass"] or manifest["matched"] != manifest["compared"] or manifest["compared"] != 12:
        raise ValueError("Missing 12/12 freeze prerequisite")
    root = Path(manifest["source_root"])
    if source_manifest(root) != manifest["source_sha256"]:
        raise ValueError("Original source SHA manifest changed")
    cards = read_rows(out / "snapshots.jsonl")
    annotation_rows = read_rows(out / "card_annotations.jsonl")
    if (artifact_hash(cards) != manifest["snapshots_sha256"]
            or artifact_hash(annotation_rows) != manifest["card_annotations_sha256"]):
        raise ValueError("Frozen state or separate truth annotations changed")
    labels = {row["card_id"]: row for row in annotation_rows}
    if [c["card_id"] for c in cards] != [f"{s}/t{t}" for s, t in CARDS]:
        raise ValueError("Frozen card set changed")
    for card in cards:
        if runner._hash(card["original_messages"]) != card["original_prompt_hash"]:
            raise ValueError(f"Frozen prompt hash changed: {card['card_id']}")
    return cards, labels


def separated_memory(card: dict) -> list[dict]:
    """Do not use MemoryItem.verified as evidence for accepted beliefs."""
    claims = {row["claim_id"]: row for row in card["claims"]}
    beliefs = iter(card["beliefs"])
    items = []
    for original in card["memory_items"]:
        item = dict(original)
        if item["kind"] == "npc_belief":
            belief = next(beliefs)
            evidence = claims[belief["claim_id"]]["evidence"]
            item.pop("verified")
            item.update(policy_acceptance="accept_as_belief",
                        policy_source=belief["accepted_by"],
                        evidence_status=evidence, evidence_verified=evidence == "verified",
                        evidence_source="scenario_fixture")
        else:
            status = item.pop("verified")
            if item["kind"] == "player_claim":
                item.update(evidence_status=status, evidence_verified=status == "verified",
                            evidence_source="scenario_fixture")
            elif item["kind"] == "committed_event":
                item.update(commit_status="committed", commit_source=item["source"])
        items.append(item)
    return items


def speech_messages(card: dict, variant: str) -> list[dict]:
    if variant == "B":
        return card["original_messages"]
    if variant == "I":
        return [{"role": m["role"], "content":
                 OFFICIAL_PREFIX + "\n" + m["content"] if i == 0 else m["content"]}
                for i, m in enumerate(card["original_messages"])]
    if variant == "C":
        contract = {
            "decision": card["decision"], "decision_source": card["decision_source"],
            "current_user": card["player"], "actual_nlu": card["parsed_nlu"],
            "current_facts": card["current_state"], "facts_source": "game_engine",
            "policy_inputs": card["policy_inputs"], "committed_events": card["events"],
            "pending_action": card["pending_action"], "action_phase": "not_executed",
            "unknowns": {
                "unverified_claims": [row for row in card["claims"] if row["evidence"] != "verified"],
                "historical_promises_deposits": "Not established by current quantity counters.",
            },
        }
        return [{"role": "system", "content":
                 config.PERSONA + "\n[현재 발화 계약]\n" +
                 json.dumps(contract, ensure_ascii=False, sort_keys=True) +
                 "\n현재 결정에 맞춰 자유 대사 1~2문장을 JSON utterance로 출력한다. "
                 "정책 수용과 증거 검증을 구분한다. 현재 예약 0은 과거 약속 부재를 증명하지 않는다. "
                 "미확인 주장은 인용·조건부로만 말한다. 예정 행동은 아직 실행되지 않았으므로 "
                 "구매·전달 완료로 말하지 않는다. 현재 발화가 인사·상품 문의·단순 구매이고 "
                 "주장이 없으면 defer는 주장에 대한 판단 보류일 뿐, 인사나 거래의 거절이 아니다. "
                 "현재 사용자 요청에 적절히 응답한다."},
                {"role": "user", "content": card["player"]}]
    if variant == "H":
        items = [item for item in card["memory_items"]
                 if not (item["kind"] == "utterance" and item["source"] == "도르만")]
        context = "\n".join(MemoryItem(**item).render(tuple(card["fields"])) for item in items)
        return _messages(card, context or "(아직 기록이 없음)", runner.SOURCED_SPEECH_EXAMPLES)
    if variant == "E":
        lines = []
        for original, item in zip(card["memory_items"], separated_memory(card), strict=True):
            if original["kind"] != "npc_belief":
                lines.append(MemoryItem(**original).render(tuple(card["fields"])))
            else:
                tail = [
                    f"출처: {item['source']}",
                    f"정책 수용: {item['policy_acceptance']}",
                    f"증거 상태: {item['evidence_status']} (출처: {item['evidence_source']})",
                    f"외부 증거 검증: {item['evidence_verified']}",
                ]
                if item["confidence"] is not None:
                    tail.append(f"확신: {item['confidence']:.2f}")
                lines.append(f"[내믿음] {item['text']} ({', '.join(tail)})")
        context = "\n".join(lines) or "(아직 기록이 없음)"
        guidance = (
            "world_truth는 game_engine의 현재 상태다. policy_inputs의 evidence와 "
            "evidence_verified는 시나리오가 제공한 증거 상태다. 손님주장의 검증 표시도 "
            "제공된 증거 상태이며, 내믿음의 정책 수용은 믿기로 한 판단이지 증거 검증이 아니다. "
            "내믿음의 증거 상태와 외부 증거 검증은 연결된 손님주장의 실제 증거에서 가져온다. "
            "확정사건은 엔진 실행 기록이지 외부 주장 검증이 아니다. "
            "확인되지 않은 주장이나 약속·선금의 존재 또는 부재를 지어내지 않는다.\n"
        ) + runner.SOURCED_SPEECH_EXAMPLES.split("판단별 말투 예시:\n", 1)[1]
        return _messages(card, context, guidance)
    raise ValueError(f"Unknown speech variant: {variant}")


def nlu_messages(card: dict, variant: str) -> list[dict]:
    instruction = runner.NLU_INSTRUCTION
    if variant == "prefix":
        instruction = OFFICIAL_PREFIX + "\n" + instruction
    elif variant == "context":
        instruction += (
            "\n참조 맥락은 이전 사용자 발화이며 사실 검증 자료가 아니다. "
            "현재 user 메시지 하나만 분류한다. 이전 주장 종류를 새 인사·구매 요청에 붙이지 않는다."
            "\n[이전 사용자 최대 2턴]\n" +
            json.dumps(card["preceding_user_turns"], ensure_ascii=False)
        )
    elif variant != "current":
        raise ValueError(f"Unknown NLU variant: {variant}")
    return [{"role": "system", "content": instruction},
            {"role": "user", "content": card["player"]}]


def jobs(cards: list[dict], seeds: tuple[int, ...] = SEEDS,
         runtime: bool = False) -> list[dict]:
    if seeds != SEEDS:
        raise ValueError("Pilot requires exactly seeds 11 29 47; no extra sampling")
    result = []
    for task, variants in (("nlu", NLU_VARIANTS), ("speech", SPEECH_VARIANTS)):
        selected = cards[:2] if runtime else cards
        for index, card in enumerate(selected):
            for seed_index, seed in enumerate((11,) if runtime else seeds):
                offset = (index + seed_index) % len(variants)
                ordered = ("current",) if runtime and task == "nlu" else (
                    ("B",) if runtime else variants[offset:] + variants[:offset]
                )
                for variant in ordered:
                    for repeat in range(1, 4) if runtime else (0,):
                        messages = (nlu_messages(card, variant) if task == "nlu"
                                    else speech_messages(card, variant))
                        result.append({
                            "call_id": f"{'runtime' if runtime else 'pilot'}/{task}/"
                                       f"{card['card_id']}/{variant}/s{seed}/r{repeat}",
                            "task": task, "card_id": card["card_id"], "variant": variant,
                            "seed": seed, "repeat": repeat, "order": len(result),
                            "messages": messages, "prompt_hash": runner._hash(messages),
                            "max_tokens": config.MAX_TOKENS_NLU if task == "nlu" else config.MAX_TOKENS,
                            "json_schema": runner.NLU_SCHEMA if task == "nlu" else runner.SPEAK_SCHEMA,
                            "temperature": config.TEMPERATURE, "top_p": config.TOP_P,
                        })
    return result


def valid_parsed(value: dict | None, schema: dict) -> bool:
    """Check structure separately from semantic correctness and JSON parsing."""
    if not isinstance(value, dict) or set(value) != set(schema["required"]):
        return False
    for key, spec in schema["properties"].items():
        actual = value[key]
        if spec["type"] == "string" and not isinstance(actual, str):
            return False
        if spec["type"] == "number" and (type(actual) not in (int, float)):
            return False
        if "enum" in spec and actual not in spec["enum"]:
            return False
    return True


def execute(out: Path, planned: list[dict], runtime: bool = False) -> dict:
    """Resume only incomplete transport calls; preserve every completed response."""
    prefix = "runtime" if runtime else "pilot"
    plan_path = out / f"{prefix}_plan.json"
    if plan_path.exists() and read_json(plan_path) != {"calls": planned}:
        raise ValueError("Resume plan differs from the frozen call plan")
    write_json(plan_path, {"calls": planned})
    path = out / f"{prefix}_calls.jsonl"
    previous = read_rows(path)
    planned_by_id = {job["call_id"]: job for job in planned}
    completed = {}
    for row in previous:
        if row["call_id"] not in planned_by_id:
            raise ValueError("Unexpected existing call ID")
        if row["prompt_hash"] != planned_by_id[row["call_id"]]["prompt_hash"]:
            raise ValueError("Existing call prompt differs")
        if row["status"] == "completed":
            if row["call_id"] in completed:
                raise ValueError("Duplicate completed call ID")
            completed[row["call_id"]] = row
    original_post = llm._post
    out.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for job in planned:
            if job["call_id"] in completed:
                continue
            observation: dict = {}

            def observed_post(url: str, payload: dict, timeout: int = 180) -> dict:
                observation["request"] = payload
                body = original_post(url, payload, timeout)
                observation["raw_response"] = body
                return body

            attempts = 1 + sum(row["call_id"] == job["call_id"] for row in previous)
            row = {**job, "attempt_id": f"{job['call_id']}/attempt{attempts}"}
            llm._post = observed_post
            started = time.perf_counter()
            try:
                completion = llm.chat(
                    job["messages"], seed=job["seed"], max_tokens=job["max_tokens"],
                    json_schema=job["json_schema"],
                )
                body = observation.get("raw_response", {})
                choice = body.get("choices", [{}])[0]
                row.update(
                    status="completed", response=completion.text, parsed=completion.parsed,
                    json_parse_ok=completion.schema_ok,
                    schema_ok=valid_parsed(completion.parsed, job["json_schema"]),
                    latency_ms=completion.latency_ms, prompt_tokens=completion.prompt_tokens,
                    completion_tokens=completion.completion_tokens,
                    usage=body.get("usage"), finish_reason=choice.get("finish_reason"),
                    output_truncated=(choice["finish_reason"] == "length"
                                      if choice.get("finish_reason") is not None else None),
                    input_truncated=body.get("truncated"),
                    truncation_evidence={"truncated": body.get("truncated"),
                                         "timings": body.get("timings"),
                                         "finish_reason": choice.get("finish_reason")},
                    observation=observation,
                )
                completed[job["call_id"]] = row
            except (llm.InferenceError, TimeoutError, OSError) as exc:
                row.update(status="failed", error=str(exc), observation=observation)
            except (KeyError, IndexError, TypeError) as exc:
                if "raw_response" not in observation:
                    raise
                # A returned malformed completion must not be resampled for quality.
                row.update(
                    status="completed", protocol_error=str(exc), response="",
                    parsed=None, json_parse_ok=False, schema_ok=False,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    prompt_tokens=None, completion_tokens=None, usage=None,
                    finish_reason=None, output_truncated=None, input_truncated=None,
                    truncation_evidence={"raw_response": observation["raw_response"]},
                    observation=observation,
                )
                completed[job["call_id"]] = row
            finally:
                llm._post = original_post
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            previous.append(row)
            print(f"CALL {row['status']} {job['call_id']} "
                  f"completed={len(completed)}/{len(planned)}", flush=True)
            for task in ("nlu", "speech"):
                task_ids = {item["call_id"] for item in planned if item["task"] == task}
                if job["task"] == task and task_ids <= completed.keys():
                    print(f"{prefix.upper()}_{task.upper()}_COMPLETE {len(task_ids)}", flush=True)
    summary = {"completed": len(completed), "planned": len(planned),
               "failed_attempts": sum(row["status"] == "failed" for row in previous),
               "pass": len(completed) == len(planned)}
    print(json.dumps(summary))
    return summary


def probe(url: str, payload: dict | None = None) -> dict:
    try:
        if payload is not None:
            return {"status": "observed", "body": llm._post(url, payload)}
        with urllib.request.urlopen(url, timeout=10) as response:
            return {"status": "observed", "body": json.loads(response.read())}
    except (urllib.error.URLError, llm.InferenceError, TimeoutError, json.JSONDecodeError) as exc:
        return {"status": "unconfirmed", "error": str(exc)}


def runtime_metadata(out: Path, planned: list[dict], model: Path,
                     official_config: Path | None = None,
                     server_binary: str | None = None,
                     server_log: Path | None = None) -> dict:
    """Metadata/tokenization probes do not generate model outputs."""
    if (out / "runtime_metadata.json").exists():
        existing = read_json(out / "runtime_metadata.json")
        if existing["model_sha256"] != sha256(model):
            raise ValueError("Runtime model changed since original metadata capture")
        return existing
    base = config.CHAT_ENDPOINT.rsplit("/v1/", 1)[0]
    metadata = {
        "model_file": str(model.resolve()), "model_sha256": sha256(model),
        "endpoint": config.CHAT_ENDPOINT,
        "endpoints": {name: probe(base + name) for name in ("/props", "/slots", "/health", "/v1/models")},
        "official_source": OFFICIAL_SOURCE,
        "official_config": None, "template_comparison": "unconfirmed",
        "server_version": "unconfirmed", "server_log": None,
        "rendered_inputs": [], "eos": None,
    }
    if official_config is not None:
        official = read_json(official_config)
        metadata["official_config"] = {"path": str(official_config), "sha256": sha256(official_config),
                                       "body": official}
        props = metadata["endpoints"]["/props"].get("body", {})
        metadata["template_comparison"] = (
            "exact_match" if props.get("chat_template") == official.get("chat_template")
            and isinstance(official.get("chat_template"), str) else "mismatch_or_unavailable"
        )
    binary = server_binary or shutil.which("llama-server")
    if binary:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
        metadata["server_version"] = {"command": [binary, "--version"], "exit_code": version.returncode,
                                      "stdout": version.stdout, "stderr": version.stderr}
    if server_log:
        metadata["server_log"] = {
            "path": str(server_log), "sha256_at_probe": sha256(server_log),
            "text": server_log.read_text(encoding="utf-8"),
        }
    for job in planned[::3]:
        rendered = probe(base + "/apply-template", {"messages": job["messages"], "add_generation_prompt": True})
        prompt = rendered.get("body", {}).get("prompt")
        tokens = (probe(base + "/tokenize", {"content": prompt, "add_special": True, "with_pieces": True})
                  if isinstance(prompt, str) else {"status": "unconfirmed", "error": "No rendered prompt"})
        metadata["rendered_inputs"].append({
            "call_id": job["call_id"], "prompt_hash": job["prompt_hash"],
            "apply_template": rendered, "tokenize": tokens,
            "applied_to_actual_generation": "unconfirmed: diagnostic endpoint, not a generation trace",
        })
    metadata["eos"] = probe(base + "/tokenize", {
        "content": "[|endofturn|]", "add_special": False, "parse_special": True, "with_pieces": True,
    })
    metadata["interface_caveat"] = (
        "Exact metadata template equality and diagnostic rendering do not prove the actual "
        "generation template, stop behavior or absence of truncation. Compare raw finish reasons "
        "and usage; special_eos_id warnings alone do not prove a broken interface."
    )
    write_json(out / "runtime_metadata.json", metadata)
    return metadata


def completed_calls(out: Path, cards: list[dict]) -> list[dict]:
    planned = jobs(cards)
    rows = [row for row in read_rows(out / "pilot_calls.jsonl") if row["status"] == "completed"]
    by_id = {row["call_id"]: row for row in rows}
    if len(rows) != len(by_id) or set(by_id) != {job["call_id"] for job in planned}:
        raise ValueError("Require exactly 288 unique completed pilot calls (108 NLU + 180 speech)")
    for job in planned:
        row = by_id[job["call_id"]]
        for key in ("messages", "prompt_hash", "task", "card_id", "variant", "seed", "order"):
            if row[key] != job[key]:
                raise ValueError(f"Call differs from fixed plan: {row['call_id']}/{key}")
    return rows


def review_pack(out: Path) -> dict:
    cards, labels = load_frozen(out)
    by_card = {card["card_id"]: card for card in cards}
    speech = [row for row in completed_calls(out, cards) if row["task"] == "speech"]
    random.Random(20261014).shuffle(speech)
    visible, mapping, template = [], [], []
    for index, row in enumerate(speech, 1):
        blind_id = f"R{index:03d}"
        card = by_card[row["card_id"]]
        # No condition, seed, call ID, messages, prompt hash or variant in this payload.
        visible.append({
            "blind_id": blind_id, "card_id": card["card_id"], "player": card["player"],
            "response": row["response"], "schema_ok": row["schema_ok"],
            "actual_nlu": card["parsed_nlu"], "actual_decision": card["decision"],
            "current_state": card["current_state"], "policy_inputs": card["policy_inputs"],
            "claims": card["claims"], "beliefs": card["beliefs"], "events": card["events"],
            "preceding_user_turns": card["preceding_user_turns"],
            "pending_action": card["pending_action"], "action_phase": card["action_phase"],
            "truth_annotation": labels[card["card_id"]],
        })
        mapping.append({"blind_id": blind_id, "call_id": row["call_id"], "variant": row["variant"],
                        "seed": row["seed"], "card_id": row["card_id"]})
        template.append({
            "blind_id": blind_id, **{flag: None for flag in SEMANTIC_FLAGS},
            "ambiguous": None, "judge": "", "judge_type": "",
            "independent": None, "rationale": "", "evidence_refs": [],
        })
    write_rows(out / "review_pack.jsonl", visible)
    write_rows(out / "review_mapping.jsonl", mapping)
    if not (out / "annotations.jsonl").exists():
        write_rows(out / "annotations.jsonl", template)
    write_json(out / "review_criteria.json", {
        "rows": 180, "nlu_programmatic_rows": 108, "criteria": CRITERIA,
        "flags": list(SEMANTIC_FLAGS), "judge_types": ["human", "ai_assisted"],
        "instructions": "Compare definite assertions with supplied evidence; quotations and "
                        "conditionals are not definite assertions. Unknown history is unsupported, "
                        "not proven false. Mark each category independently, record ambiguity and "
                        "evidence references. No automatic external judge.",
    })
    return {"speech_reviews": 180, "nlu_programmatic": 108}


def validate_annotations(rows: list[dict], mapping: list[dict]) -> dict[str, dict]:
    ids = {row["blind_id"] for row in mapping}
    by_id = {row["blind_id"]: row for row in rows}
    if len(mapping) != 180 or len(ids) != 180 or len(rows) != 180 or set(by_id) != ids:
        raise ValueError("Require exactly all 180 unique speech review rows; NLU 108 is programmatic")
    for row in rows:
        if any(type(row.get(flag)) is not bool for flag in (*SEMANTIC_FLAGS, "ambiguous", "independent")):
            raise ValueError(f"Incomplete semantic flags: {row['blind_id']}")
        if row.get("judge_type") not in ("human", "ai_assisted") or not row.get("judge", "").strip():
            raise ValueError(f"Missing judge provenance: {row['blind_id']}")
        if not row.get("rationale", "").strip() or not row.get("evidence_refs"):
            raise ValueError(f"Missing semantic reasoning/evidence: {row['blind_id']}")
        if not isinstance(row["evidence_refs"], list) or not all(
            isinstance(ref, str) and ref.strip() for ref in row["evidence_refs"]
        ):
            raise ValueError(f"Invalid evidence references: {row['blind_id']}")
    return by_id


def report(out: Path, annotations: Path, source: Path) -> dict:
    cards, labels = load_frozen(source)
    calls = completed_calls(source, cards)
    mapping = read_rows(source / "review_mapping.jsonl")
    reviewed = validate_annotations(read_rows(annotations), mapping)
    by_call = {row["call_id"]: row for row in calls}
    speech_ids = {row["call_id"] for row in calls if row["task"] == "speech"}
    if {row["call_id"] for row in mapping} != speech_ids:
        raise ValueError("Review mapping does not cover all speech calls")
    for row in mapping:
        call = by_call[row["call_id"]]
        if any(row[key] != call[key] for key in ("variant", "seed", "card_id")):
            raise ValueError("Review mapping metadata differs from call")
    speech, nlu, pairing = {}, {}, []
    for variant in SPEECH_VARIANTS:
        entries = [(item, reviewed[item["blind_id"]]) for item in mapping if item["variant"] == variant]
        speech[variant] = {
            "denominator": len(entries),
            **{flag: sum(row[flag] for _, row in entries) for flag in SEMANTIC_FLAGS},
            "ambiguous": sum(row["ambiguous"] for _, row in entries),
            "per_card": {
                card["card_id"]: {
                    "denominator": 3,
                    "semantic_errors": sum(
                        row["unsupported_assertion"] or row["policy_contradiction"]
                        for item, row in entries if item["card_id"] == card["card_id"]
                    ),
                } for card in cards
            },
            "controls": {
                control: {
                    "denominator": sum(labels[item["card_id"]]["control"] == control for item, _ in entries),
                    "blanket_refusals": sum(
                        row["blanket_refusal"] for item, row in entries
                        if labels[item["card_id"]]["control"] == control
                    ),
                } for control in ("verified_claim", "rumor", "product_inquiry")
            },
        }
    for variant in NLU_VARIANTS:
        entries = [row for row in calls if row["task"] == "nlu" and row["variant"] == variant]
        scores = [{
            "call_id": row["call_id"], "card_id": row["card_id"],
            "correct": row["schema_ok"] and (row["parsed"] or {}).get("claim_predicate")
                       == labels[row["card_id"]]["truth_predicate"],
            "truth_predicate": labels[row["card_id"]]["truth_predicate"],
            "parsed": row["parsed"], "control": labels[row["card_id"]]["control"],
        } for row in entries]
        nlu[variant] = {
            "denominator": len(scores), "correct": sum(row["correct"] for row in scores),
            "controls": {control: {
                "denominator": sum(row["control"] == control for row in scores),
                "correct": sum(row["correct"] for row in scores if row["control"] == control),
            } for control in ("greeting", "purchase")}, "scores": scores,
        }
    for variant, stats in speech.items():
        baseline = speech["B"]
        reductions = [stats[key] - baseline[key] for key in ("unsupported_assertion", "policy_contradiction")]
        stats["eligible"] = (
            variant != "B" and max(reductions) <= 0 and min(reductions) < 0
            and all(value["denominator"] > 0 and value["blanket_refusals"] == 0
                    for value in stats["controls"].values())
        )
        stats["baseline_zero_cards"] = [key for key, value in baseline["per_card"].items()
                                         if value["semantic_errors"] == 0]
    for variant, stats in nlu.items():
        baseline = nlu["current"]
        stats["eligible"] = (
            variant != "current" and stats["correct"] > baseline["correct"]
            and all(value["correct"] >= baseline["controls"][key]["correct"]
                    for key, value in stats["controls"].items())
        )
    for call in calls:
        label = labels[call["card_id"]]
        pairing.append({
            **call, "truth_annotation": label,
            "regex_auxiliary_hits": [
                pattern for pattern in label["forbidden_assertions"]
                if call["task"] == "speech" and re.search(pattern, call["response"])
            ],
        })
    runtime = read_rows(source / "runtime_calls.jsonl")
    runtime_plan = jobs(cards, runtime=True)
    repeated = [row for row in runtime if row["status"] == "completed"]
    if len(repeated) != 12 or {row["call_id"] for row in repeated} != {row["call_id"] for row in runtime_plan}:
        raise ValueError("Report requires 12 separate runtime repeats")
    metadata = read_json(source / "runtime_metadata.json")
    independent_human = all(
        row["judge_type"] == "human" and row["independent"] for row in reviewed.values()
    )
    result = {
        "criteria": CRITERIA, "speech": speech, "nlu": nlu,
        "denominators": {"speech": 180, "nlu": 108, "runtime": 12, "semantic_review": 180},
        "review_provenance": {
            "judges": sorted({row["judge"] for row in reviewed.values()}),
            "independent_human_evaluation": independent_human,
            "ai_assisted_rows": sum(row["judge_type"] == "ai_assisted" for row in reviewed.values()),
        },
        "runtime": {
            "metadata": metadata,
            "repeat_groups": {
                job["call_id"].rsplit("/r", 1)[0]: len({
                    row["response"] for row in repeated
                    if row["call_id"].rsplit("/r", 1)[0] == job["call_id"].rsplit("/r", 1)[0]
                }) for job in runtime_plan[::3]
            },
            "output_truncated": sum(row["output_truncated"] is True for row in repeated),
            "output_truncation_unconfirmed": sum(row["output_truncated"] is None for row in repeated),
            "input_truncation_unconfirmed": sum(row["input_truncated"] is None for row in repeated),
        },
        "cause_evidence": [
            {"cause": "belief_metadata_repair", "comparison": "E vs B",
             "status": ("unconfirmed_zero_belief_exposure"
                        if not any(card["exposure_counts"]["npc_belief"] for card in cards)
                        else "supported_on_pilot" if speech["E"]["eligible"]
                        else "not_supported_by_selection"),
             "exposed_cards": sum(card["exposure_counts"]["npc_belief"] > 0 for card in cards)},
            {"cause": "evidence_guide_clarification", "comparison": "E vs B",
             "status": "supported_on_pilot" if speech["E"]["eligible"] else "not_supported_by_selection"},
            {"cause": "npc_history", "comparison": "H vs B",
             "status": "supported_on_pilot" if speech["H"]["eligible"] else "not_supported_by_selection"},
            {"cause": "decision_contract_bundle", "comparison": "C vs B",
             "status": "supported_on_pilot" if speech["C"]["eligible"] else "not_supported_by_selection"},
            {"cause": "nlu_context", "comparison": "context vs current",
             "status": "supported_on_pilot" if nlu["context"]["eligible"] else "not_supported_by_selection"},
            {"cause": "official_prefix", "comparison": "I vs B; prefix vs current",
             "status": "supported_on_pilot" if speech["I"]["eligible"] or nlu["prefix"]["eligible"]
                       else "not_supported_by_selection"},
            {"cause": "quantization_capacity_training", "status": "unconfirmed_not_tested"},
            {"cause": "actual_generation_template_and_input_truncation",
             "status": "unconfirmed_without_applied_generation_trace"},
        ],
        "recommendation": {
            "speech_candidates": [v for v in SPEECH_VARIANTS if speech[v]["eligible"]],
            "nlu_candidates": [v for v in NLU_VARIANTS if nlu[v]["eligible"]],
            "adoption": "Executor must assess interface evidence first; eligible pilot candidates "
                        "are not product changes or a guarantee. No eligible candidate means no "
                        "input improvement is selected.",
        },
        "exposure_counts": {card["card_id"]: card["exposure_counts"] for card in cards},
        "E_limitation": (
            "All frozen cards have zero pre-speech npc_belief entries. E changes guidance "
            "only and does not expose repaired belief metadata; its results "
            "cannot causally estimate belief-metadata repair."
            if not any(card["exposure_counts"]["npc_belief"] for card in cards)
            else "Belief exposure counts are reported per card."
        ),
    }
    write_json(out / "summary.json", result)
    write_rows(out / "input_output_pairs.jsonl", pairing)
    lines = [
        "# SLM root-cause diagnostic pilot", "",
        "180 speech outputs reviewed; 108 NLU outputs scored programmatically; "
        "12 separate runtime repeats. Each condition denominator is 36.",
        f"Independent human evaluation: {independent_human}. "
        "AI-assisted audit is not independent human ground truth.", "",
        "## Fixed selection criteria", *[f"- {key}: {value}" for key, value in CRITERIA.items()], "",
        "## Speech", "| Condition | N | Unsupported | Policy contradiction | Ambiguous | Eligible |",
        "|---|---:|---:|---:|---:|---|",
        *[f"| {v} | {s['denominator']} | {s['unsupported_assertion']} | "
          f"{s['policy_contradiction']} | {s['ambiguous']} | {s['eligible']} |"
          for v, s in speech.items()], "", "## NLU",
        "| Condition | N | Correct predicate | Eligible |", "|---|---:|---:|---|",
        *[f"| {v} | {s['denominator']} | {s['correct']} | {s['eligible']} |"
          for v, s in nlu.items()], "",
        "## Cause evidence", *[f"- {row['cause']}: {row['status']}" for row in result["cause_evidence"]],
        "", "## Recommendation", json.dumps(result["recommendation"], ensure_ascii=False),
        "", "## Belief exposure", result["E_limitation"],
        "", "## Interface and limits", metadata["interface_caveat"],
        "See summary.json for exact metadata, subgroup denominators, per-card baseline-zero "
        "checks, semantic categories, repeat variability and truncation evidence. "
        "Regex hits are auxiliary only. No causal attribution to size or quantization was tested.",
    ]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "runtime", "run", "review-pack", "report"):
        command = sub.add_parser(name)
        command.add_argument("--out", type=Path, default=Path("logs/root_cause"))
        if name == "run":
            command.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS))
        if name == "runtime":
            command.add_argument("--model-file", type=Path,
                                 default=config.ROOT / "models" / f"{config.MODEL_NAME}.gguf")
            command.add_argument("--official-tokenizer-config", type=Path)
            command.add_argument("--server-binary")
            command.add_argument("--server-log", type=Path)
        if name == "report":
            command.set_defaults(out=Path("results/slm_root_cause"))
            command.add_argument("--source", type=Path, default=Path("logs/root_cause"))
            command.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        freeze(args.out)
    elif args.command == "report":
        report(args.out, args.annotations, args.source)
    else:
        cards, _ = load_frozen(args.out)
        if args.command == "review-pack":
            print(json.dumps(review_pack(args.out)))
        else:
            planned = jobs(cards, tuple(args.seeds) if args.command == "run" else SEEDS,
                           runtime=args.command == "runtime")
            if args.command == "runtime":
                runtime_metadata(args.out, planned, args.model_file,
                                 args.official_tokenizer_config, args.server_binary, args.server_log)
            result = execute(args.out, planned, runtime=args.command == "runtime")
            if not result["pass"]:
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
