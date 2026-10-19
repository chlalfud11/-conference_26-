"""NLU 확인 실험 (V1 vs B 주 검정, V4 부 검정). 사전등록: docs/NLU_확인실험_사전등록.md. 단계: freeze-prompt → (세트2 작성) → freeze-set → run → analyze."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, llm, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402

LOG = CP / "logs/nlu_confirm"
SET = CP / "nlu_heldout2/heldout_set.json"
OUT = CP / "results/bottleneck"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
CALLS = LOG / "calls.jsonl"
VARIANTS = ("B", "V1", "V4")
MARKERS = re.compile(
    r"그거|그건|그게|그걸|그것|그\s?(약속|돈|값|물건|얘기|말|건)|아까|방금|저번에|지난번|말했|말씀드렸|말씀하셨|"
    r"하셨잖|했잖|드렸잖|잖아요|기억\s?(안|나|하)|분명히|라니까|다니까|몇\s?번|또\s?말|다시\s?말")


def gate(utterance: str, previous: list[str]) -> bool:
    return bool(previous) and MARKERS.search(utterance) is not None


def messages(variant: str, utterance: str, previous: list[str]) -> list[dict]:
    if variant in ("B", "V1"):
        return ni.messages_for(variant, utterance, previous)
    if variant == "V4":
        return ni.messages_for("V2" if gate(utterance, previous) else "V1", utterance, previous)
    raise ValueError(variant)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def items() -> list[dict]:
    out = []
    for d in json.loads(SET.read_text(encoding="utf-8"))["dialogues"]:
        prev = []
        for i, line in enumerate(d["lines"], start=1):
            if line["label"] not in cfg.CLAIM_PREDICATES:
                raise SystemExit(f"bad label {d['dialogue_id']} {i}")
            out.append({"did": d["dialogue_id"], "line": i, "utterance": line["utterance"], "previous": list(prev),
                        "label": line["label"], "type": line.get("type", "")})
            prev.append(line["utterance"])
    return out


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SET.exists():
        raise SystemExit("prompt freeze must come first and only once")
    LOG.mkdir(parents=True, exist_ok=True)
    files = ["nlu_confirm.py", "docs/NLU_확인실험_사전등록.md", "nlu_improve.py", "npc/runner.py", "npc/config.py", "npc/llm.py"]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SET.exists(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False), encoding="utf-8")
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
        "labels": dict(Counter(i["label"] for i in its)), "types": dict(Counter(i["type"] for i in its)),
        "gate_fires_by_type": dict(Counter(i["type"] for i in its if gate(i["utterance"], i["previous"]))),
        "hashes": {"nlu_heldout2/heldout_set.json": sha(SET)}}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def run() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    done = {(c["variant"], c["did"], c["line"], c["seed"]) for c in read_jsonl(CALLS)}
    with CALLS.open("a", encoding="utf-8") as f:
        for it in items():
            for seed in cfg.SEEDS:
                for v in VARIANTS:
                    if (v, it["did"], it["line"], seed) in done:
                        continue
                    c = llm.chat(messages(v, it["utterance"], it["previous"]), seed=seed,
                                 max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
                    pred = (c.parsed or {}).get("claim_predicate", "none")
                    f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": v, "seed": seed,
                                        "gate": gate(it["utterance"], it["previous"]) if v == "V4" else None,
                                        "predicate": pred if pred in cfg.CLAIM_PREDICATES else "none",
                                        "parsed": c.parsed, "schema_ok": c.schema_ok, "latency_ms": c.latency_ms,
                                        "at_utc": now()}, ensure_ascii=False) + "\n")
                    f.flush()
            print("done", it["did"], it["line"], flush=True)
    print("RUN_DONE", flush=True)


def sign_flip(diffs: list[float]) -> float:
    nz = [d for d in diffs if abs(d) > 1e-12]
    if not nz:
        return 1.0
    obs = abs(sum(nz))
    if len(nz) <= 20:
        return sum(abs(sum(d if (m >> k) & 1 else -d for k, d in enumerate(nz))) >= obs - 1e-12
                   for m in range(2 ** len(nz))) / 2 ** len(nz)
    rng = random.Random(20261015)
    return sum(abs(sum(d if rng.random() < .5 else -d for d in nz)) >= obs - 1e-12 for _ in range(100_000)) / 100_000


def boot(diffs: list[float]) -> list[float]:
    rng = random.Random(20261015)
    n = len(diffs)
    m = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(10_000))
    return [m[250], m[9749]]


def analyze() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    its = {(i["did"], i["line"]): i for i in items()}
    per = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    tot = {v: Counter() for v in VARIANTS}
    by_type = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    for c in read_jsonl(CALLS):
        it = its[(c["did"], c["line"])]
        tr, nr = cfg.risk_of(it["label"]), cfg.risk_of(c["predicate"])
        ok = tr == nr
        v = c["variant"]
        per[v][it["did"]][0] += ok
        per[v][it["did"]][1] += 1
        by_type[v][it["type"]][0] += ok
        by_type[v][it["type"]][1] += 1
        tot[v]["n"] += 1
        tot[v]["schema_ok"] += c["schema_ok"]
        tot[v]["risk_ok"] += ok
        tot[v]["pred_ok"] += c["predicate"] == it["label"]
        tot[v]["high_to_low"] += tr == "high_risk" and nr == "low_risk"
        tot[v]["low_to_high"] += tr == "low_risk" and nr == "high_risk"
        tot[v]["gate_on"] += bool(c.get("gate"))
    dids = sorted(per["B"])

    def compare(a: str, b: str) -> dict:
        diffs = [per[b][d][0] / per[b][d][1] - per[a][d][0] / per[a][d][1] for d in dids]
        return {"a": a, "b": b, "n_dialogues": len(dids), "discordant": sum(abs(x) > 1e-12 for x in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": boot(diffs)}

    primary = compare("B", "V1")
    sec = {"V1_vs_V4": compare("V1", "V4"), "B_vs_V4": compare("B", "V4")}
    running = 0.0
    for i, k in enumerate(sorted(sec, key=lambda k: sec[k]["p_two_sided"])):
        running = max(running, min(1.0, (len(sec) - i) * sec[k]["p_two_sided"]))
        sec[k]["holm"] = running
    summary = {v: dict(tot[v]) | {"risk_acc": tot[v]["risk_ok"] / tot[v]["n"], "pred_acc": tot[v]["pred_ok"] / tot[v]["n"],
                                  "by_type": {t: {"ok": x[0], "n": x[1]} for t, x in sorted(by_type[v].items())}}
               for v in VARIANTS}
    out = {"at_utc": now(), "summary": summary, "primary_B_vs_V1": primary, "secondary": sec,
           "adopt_V1": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                       and tot["V1"]["high_to_low"] <= tot["B"]["high_to_low"],
           "prefer_V4_over_V1": sec["V1_vs_V4"]["holm"] < 0.05 and sec["V1_vs_V4"]["mean_diff"] > 0}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "confirm_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = argparse.ArgumentParser()
    cmd.add_argument("command", choices=["freeze-prompt", "freeze-set", "run", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "run": run, "analyze": analyze}[cmd.parse_args().command]()
