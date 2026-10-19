"""NLU V9: kNN 귀 학습 문장 보강 실험 (KNN_AUG vs KNN_OLD 주 검정). 사전등록: docs/NLU_V9_사전등록.md.
단계: (보강 문장 작성) -> freeze-prompt -> (세트7 작성) -> freeze-set -> run -> analyze."""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, llm, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
from nlu_confirm import boot, now, read_jsonl, sha, sign_flip  # noqa: E402
from nlu_hybrid import K, embed_all, is_high  # noqa: E402

LOG = CP / "logs/nlu_aug"
AUG = LOG / "aug_lines.json"
SET = CP / "nlu_heldout7/heldout_set.json"
OUT = CP / "results/bottleneck"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
CALLS = LOG / "calls.jsonl"
OLD_SETS = ["nlu_heldout2", "nlu_heldout3", "nlu_heldout4", "nlu_heldout5", "nlu_heldout6"]
VARIANTS = ("B", "KNN_OLD", "KNN_AUG")


def old_rows() -> list[dict]:
    return [{"u": line["utterance"], "hi": is_high(line["label"])}
            for name in OLD_SETS
            for d in json.loads((CP / name / "heldout_set.json").read_text(encoding="utf-8"))["dialogues"]
            for line in d["lines"]]


def aug_rows() -> list[dict]:
    return [{"u": x["utterance"], "hi": is_high(x["label"])}
            for x in json.loads(AUG.read_text(encoding="utf-8"))["lines"]]


def with_embeddings(rows: list[dict]) -> list[dict]:
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
            out.append({"did": d["dialogue_id"], "line": i, "utterance": line["utterance"], "label": line["label"],
                        "type": line.get("type", ""), "form": line.get("form", "")})
    return out


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SET.exists() or not AUG.exists():
        raise SystemExit("need aug lines, no set7, and no previous freeze")
    files = ["nlu_knn_aug.py", "docs/NLU_V9_사전등록.md", "nlu_hybrid.py", "nlu_confirm.py", "nlu_improve.py",
             "npc/runner.py", "npc/config.py", "npc/llm.py", "logs/nlu_aug/aug_lines.json"] + \
            [f"{n}/heldout_set.json" for n in OLD_SETS]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SET.exists(),
                                         "aug_lines": len(aug_rows()),
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
        "forms": dict(Counter(i["form"] for i in its)),
        "hashes": {"nlu_heldout7/heldout_set.json": sha(SET)}}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def run() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    done = {(c["variant"], c["did"], c["line"], c["seed"]) for c in read_jsonl(CALLS)}
    its = items()
    old = with_embeddings(old_rows())
    aug = old + with_embeddings(aug_rows())
    with CALLS.open("a", encoding="utf-8") as f:
        for it, e in zip(its, embed_all([i["utterance"] for i in its])):
            for name, train in (("KNN_OLD", old), ("KNN_AUG", aug)):
                if (name, it["did"], it["line"], None) not in done:
                    hi, share = knn_high(e, train)
                    f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": name, "seed": None,
                                        "high": hi, "share": share, "at_utc": now()}, ensure_ascii=False) + "\n")
            for seed in cfg.SEEDS:
                if ("B", it["did"], it["line"], seed) in done:
                    continue
                c = llm.chat(ni.messages_for("B", it["utterance"], []), seed=seed,
                             max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
                pred = (c.parsed or {}).get("claim_predicate", "none")
                pred = pred if pred in cfg.CLAIM_PREDICATES else "none"
                f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": "B", "seed": seed,
                                    "predicate": pred, "high": is_high(pred), "schema_ok": c.schema_ok,
                                    "latency_ms": c.latency_ms, "at_utc": now()}, ensure_ascii=False) + "\n")
            f.flush()
            print("done", it["did"], it["line"], flush=True)
    print("RUN_DONE", flush=True)


def analyze() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    its = {(i["did"], i["line"]): i for i in items()}
    per = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    tot = {v: Counter() for v in VARIANTS}
    by_form = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    by_type = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    for c in read_jsonl(CALLS):
        it = its[(c["did"], c["line"])]
        v, p, truth = c["variant"], c["high"], is_high(it["label"])
        ok = p == truth
        per[v][it["did"]][0] += ok
        per[v][it["did"]][1] += 1
        by_form[v][it["form"]][0] += ok
        by_form[v][it["form"]][1] += 1
        by_type[v][it["type"]][0] += ok
        by_type[v][it["type"]][1] += 1
        tot[v]["n"] += 1
        tot[v]["risk_ok"] += ok
        tot[v]["high_to_low"] += truth and not p
        tot[v]["low_to_high"] += (not truth) and p
    dids = sorted(per["B"])

    def compare(a: str, b: str) -> dict:
        diffs = [per[b][d][0] / per[b][d][1] - per[a][d][0] / per[a][d][1] for d in dids]
        return {"a": a, "b": b, "n_dialogues": len(dids), "discordant": sum(abs(x) > 1e-12 for x in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": boot(diffs)}

    primary = compare("KNN_OLD", "KNN_AUG")
    secondary = {"B_vs_KNN_AUG": compare("B", "KNN_AUG"), "B_vs_KNN_OLD": compare("B", "KNN_OLD")}
    running = 0.0
    for i, k in enumerate(sorted(secondary, key=lambda k: secondary[k]["p_two_sided"])):
        running = max(running, min(1.0, (len(secondary) - i) * secondary[k]["p_two_sided"]))
        secondary[k]["holm"] = running
    summary = {v: dict(tot[v]) | {"risk_acc": tot[v]["risk_ok"] / tot[v]["n"],
                                  "by_form": {k: {"ok": x[0], "n": x[1]} for k, x in sorted(by_form[v].items())},
                                  "by_type": {k: {"ok": x[0], "n": x[1]} for k, x in sorted(by_type[v].items())}}
               for v in VARIANTS}
    out = {"at_utc": now(), "summary": summary, "primary_KNN_OLD_vs_KNN_AUG": primary, "secondary": secondary,
           "adopt_KNN_AUG": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                            and tot["KNN_AUG"]["high_to_low"] <= tot["KNN_OLD"]["high_to_low"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "knn_aug_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = argparse.ArgumentParser()
    cmd.add_argument("command", choices=["freeze-prompt", "freeze-set", "run", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "run": run, "analyze": analyze}[cmd.parse_args().command]()
