"""라이브 M1P6: KNN 중심 귀 (위험도는 임베딩 kNN, 술어는 B와 일치하면 B, 아니면 이웃 다수결). 사전등록: docs/M1P6_사전등록.md.
단계: freeze -> live -> analyze."""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, eval as ev, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
from nlu_confirm import now, sha  # noqa: E402
from nlu_hybrid import embed_all, is_high, K  # noqa: E402

LOG = CP / "logs/m1p6"
FREEZE = LOG / "freeze.json"
LIVE = LOG / "runs.jsonl"
OUT = CP / "results/bottleneck"
TRAIN_SETS = ["nlu_heldout2", "nlu_heldout3", "nlu_heldout4", "nlu_heldout5", "nlu_heldout6"]
SEALED = ["nlu_knn_live.py", "docs/M1P6_사전등록.md", "nlu_improve.py", "nlu_hybrid.py", "nlu_confirm.py",
          "npc/runner.py", "npc/config.py", "npc/llm.py", "npc/adapters.py", "npc/engine.py", "npc/eval.py"] + \
         [f"{n}/heldout_set.json" for n in TRAIN_SETS]


def train_data() -> list[dict]:
    rows = [{"u": line["utterance"], "label": line["label"]}
            for name in TRAIN_SETS
            for d in json.loads((CP / name / "heldout_set.json").read_text(encoding="utf-8"))["dialogues"]
            for line in d["lines"]]
    for r, e in zip(rows, embed_all([r["u"] for r in rows])):
        r["e"] = e
    return rows


def knn_predicate(b_pred: str, neighbors: list[dict]) -> tuple[str, float]:
    share = sum(is_high(n["label"]) for n in neighbors) / len(neighbors)
    high = share >= 0.5
    if high == is_high(b_pred):
        return b_pred, share
    pool = [n["label"] for n in neighbors if is_high(n["label"]) == high]
    return Counter(pool).most_common(1)[0][0], share


def make_nlu(train: list[dict]):
    def _nlu(utterance: str, seed: int):
        c = ni.make_nlu("B")(utterance, seed)
        started = time.perf_counter()
        e = embed_all([utterance])[0]
        top = sorted(train, key=lambda t: -sum(a * b for a, b in zip(e, t["e"])))[:K]
        parsed = dict(c.parsed or {})
        b_pred = parsed.get("claim_predicate", "none")
        b_pred = b_pred if b_pred in cfg.CLAIM_PREDICATES else "none"
        pred, share = knn_predicate(b_pred, top)
        parsed |= {"claim_predicate": pred, "b_predicate": b_pred, "knn_high_share": share}
        knn_ms = int((time.perf_counter() - started) * 1000)
        return dataclasses.replace(c, parsed=parsed, latency_ms=c.latency_ms + knn_ms)
    return _nlu


def check_seal() -> None:
    bad = [p for p, h in json.loads(FREEZE.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch: {bad}")


def freeze_cmd() -> None:
    if FREEZE.exists() or LIVE.exists():
        raise SystemExit("already frozen or live runs exist")
    LOG.mkdir(parents=True, exist_ok=True)
    FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "hashes": {f: sha(CP / f) for f in SEALED}},
                                 indent=2, ensure_ascii=False), encoding="utf-8")
    print("frozen")


def live_cmd() -> None:
    check_seal()
    runner._nlu = make_nlu(train_data())
    done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()} if LIVE.exists() else set()
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(ni.scenarios().items()):
            for seed in cfg.SEEDS:
                run_id = f"{sid}__M1P6__s{seed}"
                if run_id in done:
                    continue
                print(f"Running {run_id}", flush=True)
                record = runner.run_dialogue(s, "M1P1", seed)
                record.condition, record.run_id = "M1P6", run_id
                f.write(record.to_json() + "\n")
                f.flush()
    print("LIVE_DONE", flush=True)


def analyze_cmd() -> None:
    check_seal()
    scen = ni.scenarios()
    sources = {"M1P1": [CP / "logs/runs.jsonl", CP / "logs/adversarial/runs.jsonl"],
               "M1P5": [CP / "logs/nlu_improve/runs.jsonl"], "M1P6": [LIVE]}
    runs = {c: [] for c in sources}
    for c, paths in sources.items():
        seen = set()
        for p in paths:
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if r["condition"] == c and r["run_id"] not in seen:
                    seen.add(r["run_id"])
                    runs[c].append(r)
    per = {c: defaultdict(Counter) for c in runs}
    totals = {c: Counter() for c in runs}
    lat = {c: [] for c in runs}
    for c, rs in runs.items():
        for r in rs:
            for t, spec in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
                lat[c].append((t.get("nlu_latency_ms") or 0) + (t.get("response_latency_ms") or 0))
                if not spec.get("scored"):
                    continue
                flags = set(ev.contamination_flags(t, spec, r))
                cell = per[c][r["scenario_id"]]
                truth_high = is_high(spec.get("truth_predicate", "none"))
                for key, hit in (("n", True), ("agree", t["decision"] == t["expected_decision"]),
                                 ("risk_ok", truth_high == is_high(t["nlu_predicate"])),
                                 ("high_to_low", truth_high and not is_high(t["nlu_predicate"])),
                                 ("low_to_high", (not truth_high) and is_high(t["nlu_predicate"])),
                                 ("should_accept", t["expected_decision"] == "accept_as_belief"),
                                 ("accepted_ok", t["expected_decision"] == t["decision"] == "accept_as_belief")):
                    cell[key] += hit
                    totals[c][key] += hit
                if t["evidence"] in ("none", "contradicting"):
                    cell["inj"] += 1
                    totals[c]["inj"] += 1
                    for flag in ("promoted_without_policy", "asserted_as_fact_in_utterance"):
                        cell[flag] += flag in flags
                        totals[c][flag] += flag in flags

    def paired(a: str, b: str, num: str, den: str) -> dict:
        shared = [s for s in sorted(per[a]) if per[a][s][den] and per[b][s][den]]
        diffs = [per[b][s][num] / per[b][s][den] - per[a][s][num] / per[a][s][den] for s in shared]
        return {"a": a, "b": b, "n_scenarios": len(shared), "discordant": sum(abs(d) > 1e-12 for d in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": ni.sign_flip(diffs), "ci95": ni.bootstrap_ci(diffs)}

    primary = paired("M1P1", "M1P6", "agree", "n")
    secondary = {"c1": paired("M1P1", "M1P6", "promoted_without_policy", "inj"),
                 "c2": paired("M1P1", "M1P6", "asserted_as_fact_in_utterance", "inj")}
    a, b = totals["M1P1"], totals["M1P6"]
    secondary["TCAR_fisher"] = {"p_two_sided": ni.fisher(a["accepted_ok"], a["should_accept"] - a["accepted_ok"],
                                                         b["accepted_ok"], b["should_accept"] - b["accepted_ok"])}
    adj = ni.holm({k: v["p_two_sided"] for k, v in secondary.items()})
    for k in secondary:
        secondary[k]["holm"] = adj[k]
    descriptive_vs_m1p5 = paired("M1P5", "M1P6", "agree", "n")
    summary = {c: {"runs": len(runs[c]), **dict(totals[c]),
                   "agree_rate": totals[c]["agree"] / totals[c]["n"], "risk_acc": totals[c]["risk_ok"] / totals[c]["n"],
                   "TCAR": totals[c]["accepted_ok"] / totals[c]["should_accept"],
                   "c1_rate": totals[c]["promoted_without_policy"] / totals[c]["inj"],
                   "c2_rate": totals[c]["asserted_as_fact_in_utterance"] / totals[c]["inj"],
                   "turn_latency_median_ms": sorted(lat[c])[len(lat[c]) // 2],
                   "turn_latency_p95_ms": sorted(lat[c])[int(.95 * (len(lat[c]) - 1))]} for c in runs}
    out = {"at_utc": now(), "summary": summary, "primary_agree_M1P1_vs_M1P6": primary, "secondary": secondary,
           "descriptive_agree_M1P5_vs_M1P6": descriptive_vs_m1p5,
           "adopt_M1P6": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                         and b["promoted_without_policy"] <= a["promoted_without_policy"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m1p6_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["freeze", "live", "analyze"])
    {"freeze": freeze_cmd, "live": live_cmd, "analyze": analyze_cmd}[ap.parse_args().command]()
