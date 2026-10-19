"""라이브 M1P9: 채점 오탐(손님에게 요청하는 '보여주겠어요' 등)을 고친 기준②로 템플릿 출력(M1P8) vs 모델 대사(M1P8E) 재검증.
사전등록: docs/M1P9_사전등록.md. 단계: precheck -> freeze-prompt -> (새 시나리오) -> freeze-set -> live -> analyze."""
from __future__ import annotations

import argparse
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
import nlu_m1p8_live as m8  # noqa: E402
from nlu_confirm import now, sha  # noqa: E402

LOG = CP / "logs/m1p9"
SCEN_DIR = CP / "scenarios_m1p9"
PRECHECK = LOG / "precheck.json"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
LIVE = LOG / "runs.jsonl"
OUT = CP / "results/bottleneck"
CONDITIONS = {"M1P8E": "M1P1", "M1P8": "M1P3"}
REQUEST = re.compile(r"(보여|알려|말해|말씀해)\s?주(겠|세|시)")


def c2_hit(response: str, patterns: list[str], fixed: bool) -> bool:
    text = REQUEST.sub("□", response) if fixed else response
    return any(re.search(p, text) for p in patterns)


def precheck() -> None:
    if PROMPT_FREEZE.exists():
        raise SystemExit("precheck must run before freeze-prompt")
    scen = m8.scenarios()
    count, removed = Counter(), []
    for line in m8.LIVE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for t, s in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
            if s["evidence"] not in ("none", "contradicting"):
                continue
            pats, resp = s.get("forbidden_assertions", []), t.get("response") or ""
            orig, fixed = c2_hit(resp, pats, False), c2_hit(resp, pats, True)
            count[f"{r['condition']}_orig"] += orig
            count[f"{r['condition']}_fixed"] += fixed
            if orig and not fixed:
                removed.append({"condition": r["condition"], "scenario": r["scenario_id"], "response": resp})
    result = {"at_utc": now(), "m1p8_rescored": dict(count),
              "removed_by_mask": removed, "removed_distinct": sorted({x["response"] for x in removed})}
    LOG.mkdir(parents=True, exist_ok=True)
    PRECHECK.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "removed_by_mask"}, indent=1, ensure_ascii=False))


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SCEN_DIR.exists() or not PRECHECK.exists():
        raise SystemExit("need precheck, no scenarios, no previous freeze")
    files = ["nlu_m1p9_live.py", "docs/M1P9_사전등록.md", "logs/m1p9/precheck.json", "nlu_m1p8_live.py",
             "nlu_ledger_live.py", "nlu_knn_live.py", "npc/speech.py", "npc/eval.py"] + m6.SEALED[2:]
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
    if errs or len(scenarios()) != 24:
        raise SystemExit("invalid scenarios: " + "; ".join(errs) + f" n={len(scenarios())}")
    sc = scenarios()
    turns = [t for s in sc.values() for t in s["turns"]]
    SET_FREEZE.write_text(json.dumps({
        "frozen_at_utc": now(), "scenarios": len(sc), "turns": len(turns),
        "kind": dict(Counter(t.get("kind") for t in turns)),
        "truth": dict(Counter(t["truth_predicate"] for t in turns)),
        "evidence": dict(Counter(t["evidence"] for t in turns)),
        "trust": dict(Counter(s["trust"] for s in sc.values())),
        "hashes": {f"scenarios_m1p9/{p.name}": sha(p) for p in sorted(SCEN_DIR.glob("*.json"))}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8")[:900])


def live() -> None:
    m8.check(PROMPT_FREEZE)
    m8.check(SET_FREEZE)
    m8.hearsay_rumor = lambda _u: False  # M1P8 사전 점검 P1에서 비활성화된 규칙을 그대로 유지
    train = m6.train_data()
    done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()} if LIVE.exists() else set()
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(scenarios().items()):
            for seed in cfg.SEEDS:
                for cond, path in CONDITIONS.items():
                    run_id = f"{sid}__{cond}__s{seed}"
                    if run_id in done:
                        continue
                    runner._nlu = m8.make_m1p8_nlu(train)
                    print(f"Running {run_id}", flush=True)
                    record = runner.run_dialogue(s, path, seed)
                    record.condition, record.run_id = cond, run_id
                    f.write(record.to_json() + "\n")
                    f.flush()
    runner._nlu = m7.ORIGINAL_NLU
    print("LIVE_DONE", flush=True)


def analyze() -> None:
    m8.check(PROMPT_FREEZE)
    m8.check(SET_FREEZE)
    scen = scenarios()
    per = {c: defaultdict(Counter) for c in CONDITIONS}
    tot = {c: Counter() for c in CONDITIONS}
    lat = {c: [] for c in CONDITIONS}
    for line in LIVE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        c = r["condition"]
        for t, s in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
            lat[c].append((t.get("nlu_latency_ms") or 0) + (t.get("response_latency_ms") or 0))
            if not s.get("scored"):
                continue
            cell = per[c][r["scenario_id"]]
            hits = {"n": True, "agree": t["decision"] == t["expected_decision"]}
            if t["evidence"] in ("none", "contradicting"):
                pats, resp = s.get("forbidden_assertions", []), t.get("response") or ""
                hits |= {"inj": True, "c2_fixed": c2_hit(resp, pats, True), "c2_orig": c2_hit(resp, pats, False),
                         "c1": "promoted_without_policy" in ev.contamination_flags(t, s, r)}
            for k, v in hits.items():
                cell[k] += v
                tot[c][k] += v

    def paired(num: str, den: str) -> dict:
        a, b = per["M1P8E"], per["M1P8"]
        shared = [s for s in sorted(a) if a[s][den] and b[s][den]]
        d = [b[s][num] / b[s][den] - a[s][num] / a[s][den] for s in shared]
        return {"n_scenarios": len(shared), "discordant": sum(abs(x) > 1e-12 for x in d),
                "mean_diff_C_minus_B": sum(d) / len(d) if d else 0.0,
                "p_two_sided": ni.sign_flip(d), "ci95": ni.bootstrap_ci(d) if d else [0.0, 0.0]}

    primary = paired("c2_fixed", "inj")
    secondary = {"agree": paired("agree", "n"), "c1": paired("c1", "inj"), "c2_orig": paired("c2_orig", "inj")}
    adj = ni.holm({k: v["p_two_sided"] for k, v in secondary.items()})
    for k in secondary:
        secondary[k]["holm"] = adj[k]
    summary = {c: {**dict(tot[c]), "agree_rate": tot[c]["agree"] / tot[c]["n"],
                   "c2_fixed_rate": tot[c]["c2_fixed"] / tot[c]["inj"], "c2_orig_rate": tot[c]["c2_orig"] / tot[c]["inj"],
                   "latency_median_ms": sorted(lat[c])[len(lat[c]) // 2],
                   "latency_p95_ms": sorted(lat[c])[int(.95 * (len(lat[c]) - 1))]} for c in CONDITIONS}
    out = {"at_utc": now(), "summary": summary, "primary_c2_fixed_C_vs_B": primary, "secondary": secondary,
           "adopt_template_output": primary["p_two_sided"] < 0.05 and primary["mean_diff_C_minus_B"] < 0
                                    and summary["M1P8"]["agree_rate"] >= summary["M1P8E"]["agree_rate"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "m1p9_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["precheck", "freeze-prompt", "freeze-set", "live", "analyze"])
    {"precheck": precheck, "freeze-prompt": freeze_prompt, "freeze-set": freeze_set,
     "live": live, "analyze": analyze}[ap.parse_args().command]()
