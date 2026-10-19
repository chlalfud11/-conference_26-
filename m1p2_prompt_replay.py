from __future__ import annotations

import json

from npc import config, llm, runner


def main() -> int:
    with (config.ROOT / "logs" / "runs.jsonl").open(encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    with (config.ROOT / "scenarios" / "S05_v1.json").open(encoding="utf-8") as handle:
        scenario = json.load(handle)
    original_chat = llm.chat
    compared = matched = 0
    per_condition = {}
    for condition in (*config.MAIN_CONDITIONS, *config.FAIR_CONDITIONS,
                      *config.MITIGATION_CONDITIONS, *config.CORRECTED_CONDITIONS):
        baseline = next(
            record for record in records
            if record["condition"] == condition
            and record["scenario_id"] == "S05_v1"
            and record["seed"] == 11
        )
        turn_index = 0
        nlu_call = True

        def replay_chat(
            messages: list[dict], seed: int,
            max_tokens: int = config.MAX_TOKENS,
            json_schema: dict | None = None,
        ) -> llm.Completion:
            nonlocal turn_index, nlu_call
            turn = baseline["turns"][turn_index]
            if nlu_call:
                parsed = turn["nlu"]
                nlu_call = False
            else:
                parsed = {"decision": turn["decision"], "utterance": turn["response"]}
                nlu_call = True
                turn_index += 1
            return llm.Completion(
                text=json.dumps(parsed, ensure_ascii=False),
                latency_ms=0, prompt_tokens=0, completion_tokens=0,
                schema_ok=True, parsed=parsed,
            )

        llm.chat = replay_chat
        try:
            replay = runner.run_dialogue(scenario, condition, 11)
        finally:
            llm.chat = original_chat
        assert turn_index == len(baseline["turns"])
        hits = sum(
            old["prompt_hash"] == new.prompt_hash
            for old, new in zip(baseline["turns"], replay.turns, strict=True)
        )
        count = len(replay.turns)
        compared += count
        matched += hits
        per_condition[condition] = {"matched": hits, "compared": count}
        print(f"{condition}: stored_before_change vs recorded_input_replay {hits}/{count}")
    result = {
        "scope": "S05_v1 seed11, original recorded NLU and utterances; live embeddings for vector memory.",
        "not_a_fresh_sampling_reproducibility_test": True,
        "per_condition": per_condition,
        "matched": matched,
        "compared": compared,
        "pass": matched == compared == 56,
    }
    print(json.dumps(result, ensure_ascii=False))
    assert result["pass"]
    print("PROMPT_REPLAY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
