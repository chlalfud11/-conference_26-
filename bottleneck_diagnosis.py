"""병목 진단: 기존 원자료만 읽어 결정 오류를 단계(NLU 위험도 / 정책)로 귀속하고 단계별 지연을 잰다. 추론 0건."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from npc import config as cfg

CP = Path(__file__).resolve().parent
LOGS = (CP / "logs/runs.jsonl", CP / "logs/adversarial/runs.jsonl", CP / "logs/policy_v2/runs.jsonl")
OUT = CP / "results/bottleneck/diagnosis.json"


def load():
    scen = {}
    for d in ("scenarios", "scenarios_adversarial"):
        for f in sorted((CP / d).glob("*.json")):
            s = json.loads(f.read_text(encoding="utf-8"))
            scen[s["scenario_id"]] = s
    runs, seen = [], set()
    for p in LOGS:
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["run_id"] not in seen:
                seen.add(r["run_id"])
                runs.append(r)
    return scen, runs


def pct(values, q):
    v = sorted(values)
    return v[int(q * (len(v) - 1))] if v else None


def main() -> dict:
    scen, runs = load()
    attribution = collections.defaultdict(collections.Counter)
    latency = collections.defaultdict(lambda: collections.defaultdict(list))
    nlu_calls = {}
    for r in runs:
        sc = scen[r["scenario_id"]]
        for t, spec in zip(r["turns"], sc["turns"]):
            latency[r["condition"]]["nlu"].append(t.get("nlu_latency_ms") or 0)
            latency[r["condition"]]["speech"].append(t.get("response_latency_ms") or 0)
            if not spec.get("scored"):
                continue
            truth = spec.get("truth_predicate", "none")
            nlu_calls.setdefault((r["scenario_id"], r["seed"], t["turn"]), (truth, t["nlu_predicate"]))
            risk_ok = cfg.risk_of(truth) == cfg.risk_of(t["nlu_predicate"])
            key = f"risk_{'ok' if risk_ok else 'wrong'}__decision_{'ok' if t['decision'] == t['expected_decision'] else 'wrong'}"
            attribution[r["condition"]][key] += 1

    pred_conf, risk_conf = collections.Counter(), collections.Counter()
    for truth, pred in nlu_calls.values():
        pred_conf[f"{truth}->{pred}"] += 1
        risk_conf[f"{cfg.risk_of(truth)}->{cfg.risk_of(pred)}"] += 1
    n = len(nlu_calls)
    out = {
        "source_logs": [str(p.relative_to(CP)) for p in LOGS],
        "runs": len(runs),
        "unique_scored_nlu_calls": n,
        "nlu_predicate_accuracy": sum(1 for t, p in nlu_calls.values() if t == p) / n,
        "nlu_risk_accuracy": sum(1 for t, p in nlu_calls.values() if cfg.risk_of(t) == cfg.risk_of(p)) / n,
        "risk_confusion": dict(risk_conf),
        "predicate_confusion": dict(sorted(pred_conf.items())),
        "decision_attribution": {c: dict(v) for c, v in sorted(attribution.items())},
        "latency_ms": {c: {s: {"median": pct(v, .5), "p95": pct(v, .95)} for s, v in d.items()}
                       for c, d in sorted(latency.items())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    print("NLU 위험도 정확도", round(o["nlu_risk_accuracy"], 4), "술어 정확도", round(o["nlu_predicate_accuracy"], 4))
    print("위험도 혼동", o["risk_confusion"])
    for c in ("M1P1", "M1P4"):
        print(c, o["decision_attribution"][c])
    print("저장:", OUT)
