"""라이브 M1P10: 모델 대사(M1P8E) vs v2 템플릿 출력(M1P8v2)의 대사 오염. 오염은 턴별 이중 LLM 판정 + 판정 불일치 조정으로 잰다.
사전등록: docs/M1P10_사전등록.md. 단계: freeze-prompt -> (새 시나리오) -> freeze-set -> live -> sheets -> (라벨링·조정) -> analyze."""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402
import nlu_knn_live as m6  # noqa: E402
import nlu_ledger_live as m7  # noqa: E402
import nlu_m1p8_live as m8  # noqa: E402
import speech_variants as sv  # noqa: E402
from nlu_confirm import now, sha  # noqa: E402
from nlu_hybrid import is_high  # noqa: E402

LOG = CP / "logs/m1p10"
SCEN_DIR = CP / "scenarios_m1p10"
PROMPT_FREEZE, SET_FREEZE, LIVE = LOG / "prompt_freeze.json", LOG / "set_freeze.json", LOG / "runs.jsonl"
SHEET, KEY = CP / "labels/m1p10_sheet.csv", LOG / "sheet_key.json"
OUT = CP / "results/bottleneck"
CONDITIONS = {"M1P8E": "M1P1", "M1P8v2": "M1P3"}
ORIGINAL = (runner.make_speech_plan, runner.render_speech_plan)


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SCEN_DIR.exists():
        raise SystemExit("prompt already frozen or scenarios exist")
    files = ["nlu_m1p10_live.py", "docs/M1P10_사전등록.md", "docs/오염_코드북.md", "speech_variants.py", "nlu_m1p8_live.py",
             "nlu_ledger_live.py", "nlu_knn_live.py", "npc/speech.py", "npc/runner.py"] + m6.SEALED[2:]
    LOG.mkdir(parents=True, exist_ok=True)
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SCEN_DIR.exists(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print("prompt frozen")


def scenarios() -> dict[str, dict]:
    return {s["scenario_id"]: s for s in (json.loads(p.read_text(encoding="utf-8"))
                                          for p in sorted(SCEN_DIR.glob("*.json")))}


def freeze_set() -> None:
    m8.check(PROMPT_FREEZE)
    if SET_FREEZE.exists() or LIVE.exists():
        raise SystemExit("set already frozen or runs exist")
    m8.SCEN_DIR = SCEN_DIR
    errs = m8.validate()
    if errs or len(scenarios()) != 32:
        raise SystemExit("invalid scenarios: " + "; ".join(errs) + f" n={len(scenarios())}")
    sc = scenarios()
    turns = [t for s in sc.values() for t in s["turns"]]
    SET_FREEZE.write_text(json.dumps({
        "frozen_at_utc": now(), "scenarios": len(sc), "turns": len(turns),
        "kind": dict(Counter(t.get("kind") for t in turns)), "truth": dict(Counter(t["truth_predicate"] for t in turns)),
        "evidence": dict(Counter(t["evidence"] for t in turns)), "trust": dict(Counter(s["trust"] for s in sc.values())),
        "hashes": {f"scenarios_m1p10/{p.name}": sha(p) for p in sorted(SCEN_DIR.glob("*.json"))}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8")[:700])


def live() -> None:
    m8.check(PROMPT_FREEZE)
    m8.check(SET_FREEZE)
    m8.hearsay_rumor = lambda _u: False
    train = m6.train_data()
    done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()} if LIVE.exists() else set()
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(scenarios().items()):
            for seed in cfg.SEEDS:
                for cond, path in CONDITIONS.items():
                    run_id = f"{sid}__{cond}__s{seed}"
                    if run_id in done:
                        continue
                    runner.make_speech_plan, runner.render_speech_plan = ORIGINAL
                    if cond == "M1P8v2":
                        sv.install(seed, v2=True)
                    runner._nlu = m8.make_m1p8_nlu(train)
                    print(f"Running {run_id}", flush=True)
                    record = runner.run_dialogue(s, path, seed)
                    record.condition, record.run_id = cond, run_id
                    f.write(record.to_json() + "\n")
                    f.flush()
    runner._nlu = m7.ORIGINAL_NLU
    print("LIVE_DONE", flush=True)


def claim_turns():
    scen = scenarios()
    for line in LIVE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for i, (t, s) in enumerate(zip(r["turns"], scen[r["scenario_id"]]["turns"]), 1):
            if is_high(s["truth_predicate"]) and s["evidence"] in ("none", "contradicting"):
                yield r, i, t, s


def sheets() -> None:
    m8.check(PROMPT_FREEZE)
    m8.check(SET_FREEZE)
    if SHEET.exists():
        raise SystemExit("sheet exists")
    rows = [{"run_id": r["run_id"], "condition": r["condition"], "scenario": r["scenario_id"], "turn": i,
             "evidence": s["evidence"], "player": t["player"], "response": t.get("response") or ""}
            for r, i, t, s in claim_turns()]
    random.Random(10).shuffle(rows)
    key = {}
    with SHEET.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "evidence", "player", "response", "label", "note"])
        w.writeheader()
        for i, r in enumerate(rows, 1):
            key[f"m{i:04d}"] = r
            w.writerow({"id": f"m{i:04d}", "evidence": r["evidence"], "player": r["player"], "response": r["response"],
                        "label": "", "note": ""})
    KEY.write_text(json.dumps(key, ensure_ascii=False), encoding="utf-8")
    print(len(rows), "rows", dict(Counter(r["condition"] for r in rows)))


def read(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r["label"].strip() for r in csv.DictReader(f)}


def analyze() -> None:
    import measure_build as mb
    key = json.loads(KEY.read_text(encoding="utf-8"))
    a, b = read(CP / "labels/m1p10_llm1.csv"), read(CP / "labels/m1p10_llm2.csv")
    adj = read(CP / "labels/m1p10_adjudicated.csv") if (CP / "labels/m1p10_adjudicated.csv").exists() else {}
    label = {}
    for i in key:
        label[i] = a[i] if a[i] == b[i] else adj.get(i, "")
    pending = [i for i, v in label.items() if v not in ("0", "1")]
    if pending:
        raise SystemExit(f"adjudication pending: {len(pending)} rows")
    per = {c: defaultdict(Counter) for c in CONDITIONS}
    for i, k in key.items():
        cell = per[k["condition"]][k["scenario"]]
        cell["n"] += 1
        cell["contam"] += label[i] == "1"
    shared = sorted(set(per["M1P8E"]) & set(per["M1P8v2"]))
    rate = {c: [per[c][s]["contam"] / per[c][s]["n"] for s in shared] for c in CONDITIONS}
    diffs = [v - e for v, e in zip(rate["M1P8v2"], rate["M1P8E"])]
    agree = defaultdict(Counter)
    for line in LIVE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for t in r["turns"]:
            agree[r["condition"]]["n"] += 1
            agree[r["condition"]]["ok"] += t["decision"] == t["expected_decision"]
    pairs = [(int(a[i]), int(b[i])) for i in key]
    totals = {c: {"turns": sum(x["n"] for x in per[c].values()), "contaminated": sum(x["contam"] for x in per[c].values()),
                  "decision_agree_rate": agree[c]["ok"] / agree[c]["n"]} for c in CONDITIONS}
    for c in CONDITIONS:
        totals[c]["rate"] = totals[c]["contaminated"] / totals[c]["turns"]
        totals[c]["scenario_ci95"] = ni.bootstrap_ci(rate[c])
    out = {"at_utc": now(), "label_method": "dual LLM (Claude Opus, GPT) + adjudication by orchestrator",
           "llm_llm_kappa": mb.kappa(pairs), "adjudicated": sum(a[i] != b[i] for i in key), "summary": totals,
           "primary_contam_v2_minus_model": {"n_scenarios": len(shared), "mean_diff": sum(diffs) / len(diffs),
                                             "p_two_sided": ni.sign_flip(diffs), "ci95": ni.bootstrap_ci(diffs)},
           "adopt_v2": ni.sign_flip(diffs) < 0.05 and sum(diffs) < 0
                       and totals["M1P8v2"]["decision_agree_rate"] >= totals["M1P8E"]["decision_agree_rate"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m1p10_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["freeze-prompt", "freeze-set", "live", "sheets", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "live": live, "sheets": sheets,
     "analyze": analyze}[ap.parse_args().command]()
