"""라이브 M1P8: 승계 신호(지시어·그+명사)와 전언 소문 규칙, 템플릿 출력 결합. 사전등록: docs/M1P8_사전등록.md.
단계: precheck -> freeze-prompt -> (새 시나리오 작성) -> freeze-set -> live -> analyze."""
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
import nlu_ledger_live as m7  # noqa: E402
from nlu_confirm import MARKERS, now, sha  # noqa: E402
from nlu_hybrid import is_high  # noqa: E402

LOG = CP / "logs/m1p8"
SCEN_DIR = CP / "scenarios_m1p8"
PRECHECK = LOG / "precheck.json"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
LIVE = LOG / "runs.jsonl"
OUT = CP / "results/bottleneck"
CONDITIONS = {"M1P7": "M1P1", "M1P8E": "M1P1", "M1P8": "M1P3"}

REF = re.compile(MARKERS.pattern + r"|(^|[\s,])그\s+[가-힣]")
HEAR = re.compile(r"(대요|래요|다던데요?|다더라고요|더라고요|더군요|다고\s?(하더|들었|그러)|라던데요?|랍니다|답니다|다네요|대더라)"
                  r"[.?!~…]*\s*$")
FIRST = re.compile(r"(제가|저는|저도|저한테|제게|내가|나한테|저희|제\s?(거|것|몫|이름)|내\s?(거|것))")
TXN = re.compile(r"(맡겨|맡긴|예약|빼\s?놓|빼\s?둔|남겨\s?두|선금|미리\s?(냈|드렸|치렀)|값은|약속|주신다|준다고|깎|싸게|심부름|"
                 r"다\s?했|갖다\s?드렸|원래)")
LABELED = ["nlu_heldout2", "nlu_heldout3", "nlu_heldout4", "nlu_heldout5", "nlu_heldout6", "nlu_heldout7"]
SCEN_DIRS = ["scenarios", "scenarios_adversarial", "scenarios_ledger"]


def hearsay_rumor(utterance: str) -> bool:
    return bool(HEAR.search(utterance)) and not FIRST.search(utterance) and not TXN.search(utterance)


def apply_rules(pred: str, utterance: str, ledger: list[dict]) -> tuple[str, str | None, str]:
    last = next((x for x in reversed(ledger) if is_high(x["predicate"])), None)
    if not is_high(pred) and last and REF.search(utterance):
        return last["predicate"], last["object"], "inherited"
    if is_high(pred) and hearsay_rumor(utterance):
        return "heard_rumor", None, "hearsay"
    return pred, None, ""


def make_m1p8_nlu(train: list[dict]):
    knn_nlu = m6.make_nlu(train)
    ledger: list[dict] = []

    def _nlu(utterance: str, seed: int):
        c = knn_nlu(utterance, seed)
        parsed = dict(c.parsed or {})
        pred, obj, rule = apply_rules(parsed["claim_predicate"], utterance, ledger)
        parsed["claim_predicate"] = pred
        if obj is not None:
            parsed["claim_object"] = obj
        parsed["ledger_inherited"] = rule == "inherited"
        parsed["hearsay_rule"] = rule == "hearsay"
        if pred != "none":
            ledger.append({"predicate": pred, "object": parsed.get("claim_object", "") or ""})
        return dataclasses.replace(c, parsed=parsed)
    return _nlu


def labeled_lines() -> list[dict]:
    rows = [{"u": line["utterance"], "label": line["label"]}
            for name in LABELED
            for d in json.loads((CP / name / "heldout_set.json").read_text(encoding="utf-8"))["dialogues"]
            for line in d["lines"]]
    rows += [{"u": t["player"], "label": t["truth_predicate"]}
             for d in SCEN_DIRS for p in sorted((CP / d).glob("*.json"))
             for t in json.loads(p.read_text(encoding="utf-8")).get("turns", [])]
    return list({r["u"]: r for r in rows}.values())


def precheck() -> None:
    if PROMPT_FREEZE.exists():
        raise SystemExit("precheck must run before freeze-prompt")
    rows = labeled_lines()
    high_down = [r["u"] for r in rows if is_high(r["label"]) and hearsay_rumor(r["u"])]
    rumors = [r for r in rows if r["label"] == "heard_rumor"]
    p1 = {"lines": len(rows), "high_risk_turned_rumor": len(high_down), "examples": high_down,
          "rumor_caught": sum(hearsay_rumor(r["u"]) for r in rumors), "rumor_total": len(rumors),
          "none_caught": sum(r["label"] == "none" and hearsay_rumor(r["u"]) for r in rows),
          "hearsay_rule_enabled": len(high_down) == 0}
    scen = m7.scenarios()
    tally = Counter()
    for line in (CP / "logs/m1p7/runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["condition"] != "M1P7":
            continue
        ledger: list[dict] = []
        spec = scen[r["scenario_id"]]
        for t, s in zip(r["turns"], spec["turns"]):
            base = "none" if t["nlu"].get("ledger_inherited") else t["nlu_predicate"]
            pred, obj, rule = apply_rules(base, t["player"], ledger)
            if rule == "hearsay" and not p1["hearsay_rule_enabled"]:
                pred, rule = base, ""
            if pred != "none":
                ledger.append({"predicate": pred, "object": obj or ""})
            decision = cfg.expected_decision(cfg.risk_of(pred), s["evidence"], spec["trust"],
                                             s.get("contradicts_state", False))
            tally["n"] += 1
            tally["agree"] += decision == t["expected_decision"]
            tally["agree_m1p7"] += t["decision"] == t["expected_decision"]
            tally[f"rule_{rule or 'none'}"] += 1
            tally[f"rule_{rule or 'none'}_truth_high"] += is_high(s["truth_predicate"])
    result = {"at_utc": now(), "P1_hearsay": p1, "P2_replay_on_m1p7": dict(tally)}
    LOG.mkdir(parents=True, exist_ok=True)
    PRECHECK.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False))


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def hearsay_enabled() -> bool:
    return json.loads(PRECHECK.read_text(encoding="utf-8"))["P1_hearsay"]["hearsay_rule_enabled"]


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SCEN_DIR.exists() or not PRECHECK.exists():
        raise SystemExit("need precheck, no scenarios, no previous freeze")
    files = ["nlu_m1p8_live.py", "docs/M1P8_사전등록.md", "logs/m1p8/precheck.json", "nlu_ledger_live.py",
             "nlu_knn_live.py"] + m6.SEALED[2:]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SCEN_DIR.exists(),
                                         "hearsay_rule_enabled": hearsay_enabled(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print("prompt frozen")


def scenarios() -> dict[str, dict]:
    return {s["scenario_id"]: s for s in (json.loads(p.read_text(encoding="utf-8"))
                                          for p in sorted(SCEN_DIR.glob("*.json")))}


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
        "kind": dict(Counter(t.get("kind") for t in turns)),
        "truth": dict(Counter(t["truth_predicate"] for t in turns)),
        "evidence": dict(Counter(t["evidence"] for t in turns)),
        "trust": dict(Counter(s["trust"] for s in sc.values())),
        "hashes": {f"scenarios_m1p8/{p.name}": sha(p) for p in sorted(SCEN_DIR.glob("*.json"))}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def live() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    if not hearsay_enabled():
        global hearsay_rumor
        hearsay_rumor = lambda _u: False  # noqa: E731
    train = m6.train_data()
    done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()} if LIVE.exists() else set()
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(scenarios().items()):
            for seed in cfg.SEEDS:
                for cond, path in CONDITIONS.items():
                    run_id = f"{sid}__{cond}__s{seed}"
                    if run_id in done:
                        continue
                    runner._nlu = m7.make_ledger_nlu(train) if cond == "M1P7" else make_m1p8_nlu(train)
                    print(f"Running {run_id}", flush=True)
                    record = runner.run_dialogue(s, path, seed)
                    record.condition, record.run_id = cond, run_id
                    f.write(record.to_json() + "\n")
                    f.flush()
    runner._nlu = m7.ORIGINAL_NLU
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
    lat = {c: [] for c in CONDITIONS}
    for c, rs in runs.items():
        for r in rs:
            for t, spec in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
                nlu = t.get("nlu") or {}
                truth_high = is_high(spec["truth_predicate"])
                lat[c].append((t.get("nlu_latency_ms") or 0) + (t.get("response_latency_ms") or 0))
                for flag, key in (("ledger_inherited", "inherited"), ("hearsay_rule", "hearsay")):
                    if nlu.get(flag):
                        totals[c][key] += 1
                        totals[c][f"{key}_ok"] += (truth_high if key == "inherited"
                                                   else spec["truth_predicate"] == "heard_rumor")
                if not spec.get("scored"):
                    continue
                flags = set(ev.contamination_flags(t, spec, r))
                cell = per[c][r["scenario_id"]]
                ref = spec.get("kind") == "follow_up_ref"
                accepted_high = t["decision"] == "accept_as_belief" and truth_high
                for key, hit in (("n", True), ("agree", t["decision"] == t["expected_decision"]),
                                 ("risk_ok", truth_high == is_high(t["nlu_predicate"])),
                                 ("high_to_low", truth_high and not is_high(t["nlu_predicate"])),
                                 ("low_to_high", (not truth_high) and is_high(t["nlu_predicate"])),
                                 ("ref_n", ref), ("ref_ok", ref and t["decision"] == t["expected_decision"]),
                                 ("bpa_n", accepted_high),
                                 ("bpa_ok", accepted_high and t["nlu_predicate"] == spec["truth_predicate"]),
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

    primary = paired("M1P7", "M1P8E", "agree", "n")
    a, b = totals["M1P7"], totals["M1P8E"]
    secondary = {"c1_M1P7_vs_M1P8E": paired("M1P7", "M1P8E", "promoted_without_policy", "inj"),
                 "c2_M1P8E_vs_M1P8": paired("M1P8E", "M1P8", "asserted_as_fact_in_utterance", "inj"),
                 "TCAR_M1P7_vs_M1P8E": {"p_two_sided": ni.fisher(
                     a["accepted_ok"], a["should_accept"] - a["accepted_ok"],
                     b["accepted_ok"], b["should_accept"] - b["accepted_ok"])}}
    adj = ni.holm({k: v["p_two_sided"] for k, v in secondary.items()})
    for k in secondary:
        secondary[k]["holm"] = adj[k]
    summary = {c: {"runs": len(runs[c]), **dict(totals[c]),
                   "agree_rate": totals[c]["agree"] / totals[c]["n"], "risk_acc": totals[c]["risk_ok"] / totals[c]["n"],
                   "ref_agree_rate": totals[c]["ref_ok"] / max(1, totals[c]["ref_n"]),
                   "TCAR": totals[c]["accepted_ok"] / max(1, totals[c]["should_accept"]),
                   "BPA": totals[c]["bpa_ok"] / max(1, totals[c]["bpa_n"]),
                   "c1_rate": totals[c]["promoted_without_policy"] / max(1, totals[c]["inj"]),
                   "c2_rate": totals[c]["asserted_as_fact_in_utterance"] / max(1, totals[c]["inj"]),
                   "latency_median_ms": sorted(lat[c])[len(lat[c]) // 2],
                   "latency_p95_ms": sorted(lat[c])[int(.95 * (len(lat[c]) - 1))]} for c in CONDITIONS}
    c2 = secondary["c2_M1P8E_vs_M1P8"]
    out = {"at_utc": now(), "hearsay_rule_enabled": hearsay_enabled(), "summary": summary,
           "primary_agree_M1P7_vs_M1P8E": primary, "secondary": secondary,
           "adopt_ear_fix": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                            and b["promoted_without_policy"] <= a["promoted_without_policy"],
           "adopt_template_output": c2["holm"] < 0.05 and c2["mean_diff"] < 0
                                    and summary["M1P8"]["agree_rate"] >= summary["M1P8E"]["agree_rate"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m1p8_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["precheck", "freeze-prompt", "freeze-set", "live", "analyze"])
    {"precheck": precheck, "freeze-prompt": freeze_prompt, "freeze-set": freeze_set,
     "live": live, "analyze": analyze}[ap.parse_args().command]()
