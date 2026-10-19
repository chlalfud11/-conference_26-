"""라이브 M1P7: KNN 귀 + 장부 승계, 새 시나리오(scenarios_ledger)에서 M1P1/M1P6/M1P7 비교. 사전등록: docs/M1P7_사전등록.md.
단계: freeze-prompt -> (새 시나리오 작성) -> freeze-set -> live -> analyze."""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, eval as ev, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
import nlu_knn_live as m6  # noqa: E402
from nlu_confirm import MARKERS, now, sha  # noqa: E402
from nlu_hybrid import is_high  # noqa: E402

LOG = CP / "logs/m1p7"
SCEN_DIR = CP / "scenarios_ledger"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
LIVE = LOG / "runs.jsonl"
OUT = CP / "results/bottleneck"
CONDITIONS = ("M1P1", "M1P6", "M1P7")
ORIGINAL_NLU = runner._nlu


def refers_back(utterance: str, claim_object: str) -> bool:
    words = [w for w in re.split(r"\s+", claim_object.strip()) if w]
    return MARKERS.search(utterance) is not None or bool(words and words[-1] in utterance)


def make_ledger_nlu(train: list[dict]):
    knn_nlu = m6.make_nlu(train)
    ledger: list[dict] = []

    def _nlu(utterance: str, seed: int):
        c = knn_nlu(utterance, seed)
        parsed = dict(c.parsed or {})
        inherited = False
        last = next((x for x in reversed(ledger) if is_high(x["predicate"])), None)
        if not is_high(parsed["claim_predicate"]) and last and refers_back(utterance, last["object"]):
            parsed |= {"claim_predicate": last["predicate"], "claim_object": last["object"]}
            inherited = True
        parsed["ledger_inherited"] = inherited
        if parsed["claim_predicate"] != "none":
            ledger.append({"predicate": parsed["claim_predicate"], "object": parsed.get("claim_object", "") or ""})
        return dataclasses.replace(c, parsed=parsed)
    return _nlu


def scenarios() -> dict[str, dict]:
    return {s["scenario_id"]: s for s in (json.loads(p.read_text(encoding="utf-8"))
                                          for p in sorted(SCEN_DIR.glob("*.json")))}


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SCEN_DIR.exists():
        raise SystemExit("prompt freeze must come before scenarios exist")
    LOG.mkdir(parents=True, exist_ok=True)
    files = ["nlu_ledger_live.py", "docs/M1P7_사전등록.md", "nlu_knn_live.py"] + m6.SEALED[2:]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SCEN_DIR.exists(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print("prompt frozen")


def validate() -> list[str]:
    errs = []
    for sid, s in scenarios().items():
        if len(s.get("turns", [])) != 8 or s.get("trust") not in range(cfg.TRUST_MIN, cfg.TRUST_MAX + 1):
            errs.append(f"{sid}: turns/trust")
        for i, t in enumerate(s.get("turns", []), 1):
            if t.get("truth_predicate") not in cfg.CLAIM_PREDICATES or t.get("evidence") not in cfg.EVIDENCE_STATES:
                errs.append(f"{sid} t{i}: label/evidence")
            if "action" in t:
                errs.append(f"{sid} t{i}: actions not allowed")
    return errs


def freeze_set() -> None:
    check(PROMPT_FREEZE)
    if SET_FREEZE.exists() or LIVE.exists():
        raise SystemExit("set already frozen or runs exist")
    errs = validate()
    if errs:
        raise SystemExit("invalid scenarios: " + "; ".join(errs))
    sc = scenarios()
    turns = [t for s in sc.values() for t in s["turns"]]
    SET_FREEZE.write_text(json.dumps({
        "frozen_at_utc": now(), "scenarios": len(sc), "turns": len(turns),
        "scored": sum(bool(t.get("scored")) for t in turns),
        "follow_up_refs": sum(t.get("kind") == "follow_up_ref" for t in turns),
        "truth": dict(Counter(t["truth_predicate"] for t in turns)),
        "evidence": dict(Counter(t["evidence"] for t in turns)),
        "trust": dict(Counter(s["trust"] for s in sc.values())),
        "hashes": {f"scenarios_ledger/{p.name}": sha(p) for p in sorted(SCEN_DIR.glob("*.json"))}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def live() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    train = m6.train_data()
    done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()} if LIVE.exists() else set()
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(scenarios().items()):
            for seed in cfg.SEEDS:
                for cond in CONDITIONS:
                    run_id = f"{sid}__{cond}__s{seed}"
                    if run_id in done:
                        continue
                    runner._nlu = {"M1P1": ORIGINAL_NLU, "M1P6": m6.make_nlu(train),
                                   "M1P7": make_ledger_nlu(train)}[cond]
                    print(f"Running {run_id}", flush=True)
                    record = runner.run_dialogue(s, "M1P1", seed)
                    record.condition, record.run_id = cond, run_id
                    f.write(record.to_json() + "\n")
                    f.flush()
    runner._nlu = ORIGINAL_NLU
    print("LIVE_DONE", flush=True)


def analyze() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    scen = scenarios()
    runs = {c: [] for c in CONDITIONS}
    for line in LIVE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        runs[r["condition"]].append(r)
    per = {c: defaultdict(Counter) for c in CONDITIONS}
    totals = {c: Counter() for c in CONDITIONS}
    for c, rs in runs.items():
        for r in rs:
            for t, spec in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
                if (t.get("nlu") or {}).get("ledger_inherited"):
                    totals[c]["inherited"] += 1
                    totals[c]["inherited_ok"] += is_high(spec["truth_predicate"])
                if not spec.get("scored"):
                    continue
                flags = set(ev.contamination_flags(t, spec, r))
                cell = per[c][r["scenario_id"]]
                truth_high = is_high(spec["truth_predicate"])
                ref = spec.get("kind") == "follow_up_ref"
                for key, hit in (("n", True), ("agree", t["decision"] == t["expected_decision"]),
                                 ("risk_ok", truth_high == is_high(t["nlu_predicate"])),
                                 ("high_to_low", truth_high and not is_high(t["nlu_predicate"])),
                                 ("low_to_high", (not truth_high) and is_high(t["nlu_predicate"])),
                                 ("ref_n", ref), ("ref_ok", ref and t["decision"] == t["expected_decision"]),
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
                "mean_diff": sum(diffs) / len(diffs) if diffs else 0.0,
                "p_two_sided": ni.sign_flip(diffs), "ci95": ni.bootstrap_ci(diffs) if diffs else [0.0, 0.0]}

    primary = paired("M1P6", "M1P7", "agree", "n")
    secondary = {"M1P1_vs_M1P6_agree": paired("M1P1", "M1P6", "agree", "n"),
                 "M1P1_vs_M1P7_agree": paired("M1P1", "M1P7", "agree", "n"),
                 "M1P6_vs_M1P7_c1": paired("M1P6", "M1P7", "promoted_without_policy", "inj")}
    adj = ni.holm({k: v["p_two_sided"] for k, v in secondary.items()})
    for k in secondary:
        secondary[k]["holm"] = adj[k]
    summary = {c: {"runs": len(runs[c]), **dict(totals[c]),
                   "agree_rate": totals[c]["agree"] / totals[c]["n"], "risk_acc": totals[c]["risk_ok"] / totals[c]["n"],
                   "ref_agree_rate": totals[c]["ref_ok"] / max(1, totals[c]["ref_n"]),
                   "TCAR": totals[c]["accepted_ok"] / max(1, totals[c]["should_accept"]),
                   "c1_rate": totals[c]["promoted_without_policy"] / max(1, totals[c]["inj"]),
                   "c2_rate": totals[c]["asserted_as_fact_in_utterance"] / max(1, totals[c]["inj"])}
               for c in CONDITIONS}
    out = {"at_utc": now(), "summary": summary, "primary_agree_M1P6_vs_M1P7": primary, "secondary": secondary,
           "adopt_M1P7": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                         and totals["M1P7"]["promoted_without_policy"] <= totals["M1P6"]["promoted_without_policy"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m1p7_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["freeze-prompt", "freeze-set", "live", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "live": live, "analyze": analyze}[ap.parse_args().command]()
