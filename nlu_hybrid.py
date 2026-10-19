"""NLU 하이브리드 실험 (V8 = 언어모델 B ∧ 임베딩 kNN, 주 검정 V8 vs B). 사전등록: docs/NLU_V8_사전등록.md.
단계: freeze-prompt -> (사람이 세트6 작성) -> freeze-set -> run -> analyze."""
from __future__ import annotations

import argparse
import datetime
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, llm, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
from nlu_confirm import boot, now, read_jsonl, sha, sign_flip  # noqa: E402

LOG = CP / "logs/nlu_hybrid"
SET = CP / "nlu_heldout6/heldout_set.json"
OUT = CP / "results/bottleneck"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
CALLS = LOG / "calls.jsonl"
TRAIN_SETS = ["nlu_heldout2", "nlu_heldout3", "nlu_heldout4", "nlu_heldout5"]
K = 7
COMBOS = ("B", "KNN", "V8_AND", "V8_OR")


def is_high(predicate: str) -> bool:
    return cfg.risk_of(predicate) == "high_risk"


def unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_all(texts: list[str]) -> list[list[float]]:
    return [unit(v) for i in range(0, len(texts), 64) for v in llm.embed(texts[i:i + 64])]


def train_data() -> list[dict]:
    rows = [{"u": line["utterance"], "hi": is_high(line["label"])}
            for name in TRAIN_SETS
            for d in json.loads((CP / name / "heldout_set.json").read_text(encoding="utf-8"))["dialogues"]
            for line in d["lines"]]
    for r, e in zip(rows, embed_all([r["u"] for r in rows])):
        r["e"] = e
    return rows


def knn_high(e: list[float], train: list[dict]) -> tuple[bool, float]:
    top = sorted(train, key=lambda t: -sum(a * b for a, b in zip(e, t["e"])))[:K]
    share = sum(t["hi"] for t in top) / K
    return share >= 0.5, share


def items() -> list[dict]:
    out = []
    for d in json.loads(SET.read_text(encoding="utf-8"))["dialogues"]:
        for i, line in enumerate(d["lines"], start=1):
            if line["label"] not in cfg.CLAIM_PREDICATES:
                raise SystemExit(f"bad label {d['dialogue_id']} {i}")
            out.append({"did": d["dialogue_id"], "line": i, "utterance": line["utterance"],
                        "label": line["label"], "type": line.get("type", "")})
    return out


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SET.exists():
        raise SystemExit("prompt freeze must come first and only once")
    LOG.mkdir(parents=True, exist_ok=True)
    files = ["nlu_hybrid.py", "docs/NLU_V8_사전등록.md", "nlu_confirm.py", "nlu_improve.py",
             "npc/runner.py", "npc/config.py", "npc/llm.py"] + [f"{n}/heldout_set.json" for n in TRAIN_SETS]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SET.exists(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print("prompt frozen")


def freeze_set() -> None:
    check(PROMPT_FREEZE)
    if SET_FREEZE.exists() or CALLS.exists():
        raise SystemExit("set already frozen or calls exist")
    its = items()
    SET_FREEZE.write_text(json.dumps({
        "frozen_at_utc": now(),
        "set_mtime_utc": datetime.datetime.fromtimestamp(SET.stat().st_mtime, datetime.timezone.utc).isoformat(),
        "dialogues": len({i["did"] for i in its}), "lines": len(its),
        "unique_utterances": len({i["utterance"] for i in its}),
        "labels": dict(Counter(i["label"] for i in its)), "types": dict(Counter(i["type"] for i in its)),
        "hashes": {"nlu_heldout6/heldout_set.json": sha(SET)}}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def run() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    done = {(c["variant"], c["did"], c["line"], c["seed"]) for c in read_jsonl(CALLS)}
    its = items()
    train = train_data()
    with CALLS.open("a", encoding="utf-8") as f:
        for it, e in zip(its, embed_all([i["utterance"] for i in its])):
            if ("KNN", it["did"], it["line"], None) not in done:
                hi, share = knn_high(e, train)
                f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": "KNN", "seed": None,
                                    "high": hi, "share": share, "at_utc": now()}, ensure_ascii=False) + "\n")
            for seed in cfg.SEEDS:
                if ("B", it["did"], it["line"], seed) in done:
                    continue
                c = llm.chat(ni.messages_for("B", it["utterance"], []), seed=seed,
                             max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
                pred = (c.parsed or {}).get("claim_predicate", "none")
                pred = pred if pred in cfg.CLAIM_PREDICATES else "none"
                f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": "B", "seed": seed,
                                    "predicate": pred, "high": is_high(pred), "parsed": c.parsed,
                                    "schema_ok": c.schema_ok, "latency_ms": c.latency_ms, "at_utc": now()},
                                   ensure_ascii=False) + "\n")
            f.flush()
            print("done", it["did"], it["line"], flush=True)
    print("RUN_DONE", flush=True)


def analyze() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    its = {(i["did"], i["line"]): i for i in items()}
    calls = read_jsonl(CALLS)
    knn = {(c["did"], c["line"]): c["high"] for c in calls if c["variant"] == "KNN"}
    per = {v: defaultdict(lambda: [0, 0]) for v in COMBOS}
    tot = {v: Counter() for v in COMBOS}
    by_type = {v: defaultdict(lambda: [0, 0]) for v in COMBOS}
    for c in (c for c in calls if c["variant"] == "B"):
        key = (c["did"], c["line"])
        it, b, k = its[key], c["high"], knn[key]
        truth = is_high(it["label"])
        tot["B"]["disagree"] += b != k
        for v, p in (("B", b), ("KNN", k), ("V8_AND", b and k), ("V8_OR", b or k)):
            ok = p == truth
            per[v][it["did"]][0] += ok
            per[v][it["did"]][1] += 1
            by_type[v][it["type"]][0] += ok
            by_type[v][it["type"]][1] += 1
            tot[v]["n"] += 1
            tot[v]["risk_ok"] += ok
            tot[v]["high_to_low"] += truth and not p
            tot[v]["low_to_high"] += (not truth) and p
            if b == k:
                tot[v]["agree_n"] += 1
                tot[v]["agree_ok"] += ok
        tot["B"]["schema_ok"] += c["schema_ok"]
    dids = sorted(per["B"])

    def compare(a: str, b: str) -> dict:
        diffs = [per[b][d][0] / per[b][d][1] - per[a][d][0] / per[a][d][1] for d in dids]
        return {"a": a, "b": b, "n_dialogues": len(dids), "discordant": sum(abs(x) > 1e-12 for x in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": boot(diffs)}

    primary = compare("B", "V8_AND")
    secondary = {"B_vs_KNN": compare("B", "KNN"), "B_vs_V8_OR": compare("B", "V8_OR")}
    running = 0.0
    for i, k in enumerate(sorted(secondary, key=lambda k: secondary[k]["p_two_sided"])):
        running = max(running, min(1.0, (len(secondary) - i) * secondary[k]["p_two_sided"]))
        secondary[k]["holm"] = running
    summary = {v: dict(tot[v]) | {"risk_acc": tot[v]["risk_ok"] / tot[v]["n"],
                                  "agree_acc": tot[v]["agree_ok"] / max(1, tot[v]["agree_n"]),
                                  "by_type": {t: {"ok": x[0], "n": x[1]} for t, x in sorted(by_type[v].items())}}
               for v in COMBOS}
    out = {"at_utc": now(), "summary": summary, "primary_B_vs_V8_AND": primary, "secondary": secondary,
           "adopt_V8": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                       and tot["V8_AND"]["high_to_low"] <= tot["B"]["high_to_low"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hybrid_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = argparse.ArgumentParser()
    cmd.add_argument("command", choices=["freeze-prompt", "freeze-set", "run", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "run": run, "analyze": analyze}[cmd.parse_args().command]()
