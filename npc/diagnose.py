from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import config, llm
from .runner import NLU_SCHEMA, NLU_INSTRUCTION, _nlu


def utterances(folder: Path) -> list[tuple[str, str, str]]:
    rows = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for index, turn in enumerate(data["turns"], start=1):
            rows.append((f"{data['scenario_id']}#{index}", turn["player"],
                         turn.get("truth_predicate", "none")))
    return rows


def classify(text: str, seed: int, predicates: list[str]) -> str:
    schema = json.loads(json.dumps(NLU_SCHEMA))
    schema["properties"]["claim_predicate"]["enum"] = predicates
    completion = llm.chat(
        [{"role": "system", "content": NLU_INSTRUCTION},
         {"role": "user", "content": text}],
        seed=seed, max_tokens=config.MAX_TOKENS_NLU, json_schema=schema,
    )
    return (completion.parsed or {}).get("claim_predicate", "none")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="npc.diagnose")
    parser.add_argument("--seed", type=int, default=config.SEEDS[0])
    parser.add_argument("--out", default=str(config.ROOT / "results" / "nlu_diagnostic.json"))
    args = parser.parse_args(argv)

    rows = utterances(config.ROOT / "scenarios")
    base_order = list(config.CLAIM_PREDICATES)
    none_first = ["none"] + [p for p in base_order if p != "none"]

    report = {"seed": args.seed, "n": len(rows), "variants": {}}
    for name, order in (("declared_order", base_order), ("none_first", none_first)):
        correct, confusion, errors = 0, Counter(), []
        for key, text, truth in rows:
            predicted = classify(text, args.seed, order)
            if predicted == truth:
                correct += 1
            else:
                confusion[f"{truth}->{predicted}"] += 1
                errors.append({"id": key, "text": text, "truth": truth, "pred": predicted})
        report["variants"][name] = {
            "enum_order": order,
            "accuracy": round(correct / len(rows), 4),
            "correct": correct,
            "confusion": dict(confusion.most_common(10)),
            "errors": errors,
        }
        print(f"{name:<16} accuracy={correct / len(rows):.3f} ({correct}/{len(rows)})", flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    best = max(report["variants"], key=lambda k: report["variants"][k]["accuracy"])
    print(f"DIAGNOSE_DONE best={best} out={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
