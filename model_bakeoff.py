"""모델 비교 시험(탐색용): 같은 손님 말에 대해 후보 SLM의 대사를 모아 사람이 자연스러움을 블라인드로 평가한다.
사용: 8080 서버를 후보 모델로 띄운 뒤 `run <tag>`; 모든 모델이 끝나면 `sheet`, 평가 후 `score`."""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import runner  # noqa: E402
import nlu_knn_live as m6  # noqa: E402
import nlu_ledger_live as m7  # noqa: E402
import nlu_m1p8_live as m8  # noqa: E402
import measure_judge as mj  # noqa: E402

SET = "tmpl" if "--set=tmpl" in sys.argv or "--template" in sys.argv else ""
OUT = CP / ("logs/bakeoff_tmpl" if SET else "logs/bakeoff")
SCEN = ["S81", "S86", "S94", "S100"]
SHEET = CP / ("labels/template_rating.csv" if SET else "labels/bakeoff_rating.csv")
KEY = OUT / "sheet_key.json"


def run(tag: str, template: str | None = None) -> None:
    m8.hearsay_rumor = lambda _u: False
    condition = "M1P3" if template else "M1P1"
    if template in ("new", "v2"):
        import speech_variants
        speech_variants.install(11, v2=template == "v2")
    scen = {s["scenario_id"]: s for s in (json.loads(p.read_text(encoding="utf-8"))
                                          for p in sorted((CP / "scenarios_m1p9").glob("*.json")))}
    train = m6.train_data()
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"{tag}.jsonl").open("w", encoding="utf-8") as f:
        for sid in SCEN:
            runner._nlu = m8.make_m1p8_nlu(train)
            record = runner.run_dialogue(scen[sid], condition, 11)
            record.condition, record.run_id = tag, f"{sid}__{tag}"
            f.write(record.to_json() + "\n")
            print(f"done {sid}", flush=True)
    runner._nlu = m7.ORIGINAL_NLU
    print("BAKEOFF_RUN_DONE", tag, flush=True)


def sheet() -> None:
    rows = []
    for p in sorted(OUT.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            for i, t in enumerate(r["turns"], 1):
                rows.append({"model": r["condition"], "scenario": r["scenario_id"], "turn": i, "player": t["player"],
                             "response": t.get("response") or "", "decision": t["decision"],
                             "expected": t["expected_decision"],
                             "latency_ms": (t.get("nlu_latency_ms") or 0) + (t.get("response_latency_ms") or 0)})
    random.Random(7).shuffle(rows)
    key = {}
    with SHEET.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "player", "response", "natural", "note"])
        w.writeheader()
        for i, r in enumerate(rows, 1):
            key[f"b{i:03d}"] = r
            w.writerow({"id": f"b{i:03d}", "player": r["player"], "response": r["response"], "natural": "", "note": ""})
    KEY.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(rows), "rows")


def score() -> None:
    key = json.loads(KEY.read_text(encoding="utf-8"))
    with SHEET.open(encoding="utf-8-sig", newline="") as f:
        rated = {r["id"]: r for r in csv.DictReader(f)}
    out = {}
    for rid, r in key.items():
        o = out.setdefault(r["model"], {"n": 0, "natural_sum": 0, "rated": 0, "agree": 0, "judge_contam": 0, "lat": []})
        o["n"] += 1
        o["agree"] += r["decision"] == r["expected"]
        o["judge_contam"] += mj.judge(r["response"])
        o["lat"].append(r["latency_ms"])
        v = rated[rid]["natural"].strip()
        if v:
            o["rated"] += 1
            o["natural_sum"] += int(v)
    for o in out.values():
        o["natural_mean"] = o.pop("natural_sum") / max(1, o["rated"])
        lat = sorted(o.pop("lat"))
        o["latency_median_ms"] = lat[len(lat) // 2]
    (CP / "results/measure").mkdir(parents=True, exist_ok=True)
    (CP / "results/measure/bakeoff.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "sheet", "score"])
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--template", choices=["old", "new", "v2"])
    ap.add_argument("--set", choices=["tmpl"])
    a = ap.parse_args()
    {"run": lambda: run(a.tag, a.template), "sheet": sheet, "score": score}[a.command]()
