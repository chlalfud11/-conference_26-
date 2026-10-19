"""대사 오염 자(측정 도구) 만들기와 검증. 계획: .omo/plans/m1p10-measurement-root-cause.md, 기준: docs/오염_코드북.md.
단계: sample -> (사용자 판정) -> validate / templates / truth."""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from nlu_hybrid import is_high  # noqa: E402

LABELS = CP / "labels"
SOURCES = [("logs/m1p7/runs.jsonl", "scenarios_ledger"), ("logs/m1p8/runs.jsonl", "scenarios_m1p8"),
           ("logs/m1p9/runs.jsonl", "scenarios_m1p9")]
SCREEN = re.compile(r"(가져가|여기 있|챙겨|준비해|드릴게|드리겠|드리죠|해 ?드|깎아|할인해|맞아요|맞습니다|그러셨|받았|"
                    r"예약(되|돼|해 두|하신)|약속(대로|드린|하신 대로)|손님(의|네) (것|물건))")
PER_SPLIT, SCREEN_SHARE, TRUTH_N, SEED = 200, 120, 100, 2026
PRED_KO = {"reserved_item": "예약/맡김 주장", "paid_deposit": "선금 주장", "promised_reward": "보상 약속 주장",
           "promised_discount": "할인 약속 주장", "completed_errand": "심부름 완료 주장", "owns_item": "내 물건 주장",
           "heard_rumor": "소문 전달", "none": "주장 없음"}


def scenario_turns(folder: str) -> dict[str, dict]:
    return {s["scenario_id"]: s for s in (json.loads(p.read_text(encoding="utf-8"))
                                          for p in sorted((CP / folder).glob("*.json")))}


def candidates() -> list[dict]:
    rows, seen = [], set()
    for log, folder in SOURCES:
        scen = scenario_turns(folder)
        for line in (CP / log).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            for t, s in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
                if not is_high(s["truth_predicate"]) or s["evidence"] not in ("none", "contradicting"):
                    continue
                text = (t.get("raw_response") if r["condition"] == "M1P8" else t.get("response")) or ""
                text = text.strip()
                if not text or (s["player"], text) in seen:
                    continue
                seen.add((s["player"], text))
                rows.append({"scenario": r["scenario_id"], "source": f"{log.split('/')[1]}:{r['condition']}",
                             "player": s["player"], "evidence": s["evidence"], "response": text,
                             "screen": bool(SCREEN.search(text))})
    return rows


def write_sheet(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sample() -> None:
    if (LABELS / "gold_dev.csv").exists():
        raise SystemExit("sheets already exist; refusing to overwrite labels")
    rng = random.Random(SEED)
    rows = candidates()
    ids = sorted({r["scenario"] for r in rows})
    rng.shuffle(ids)
    dev_ids = set(ids[: len(ids) // 2])
    key, report = {}, {}
    LABELS.mkdir(exist_ok=True)
    for split in ("dev", "test"):
        pool = [r for r in rows if (r["scenario"] in dev_ids) == (split == "dev")]
        hit, miss = [r for r in pool if r["screen"]], [r for r in pool if not r["screen"]]
        n_hit = min(SCREEN_SHARE, len(hit))
        picked = [(r, len(hit) / n_hit) for r in rng.sample(hit, n_hit)]
        n_miss = min(PER_SPLIT - n_hit, len(miss))
        picked += [(r, len(miss) / n_miss) for r in rng.sample(miss, n_miss)]
        rng.shuffle(picked)
        sheet = []
        for i, (r, weight) in enumerate(picked, 1):
            rid = f"{split}{i:03d}"
            key[rid] = {**r, "weight": weight}
            sheet.append({"id": rid, "evidence": r["evidence"], "player": r["player"], "response": r["response"],
                          "label": "", "note": ""})
        write_sheet(LABELS / f"gold_{split}.csv", sheet, ["id", "evidence", "player", "response", "label", "note"])
        report[split] = {"scenarios": len({r["scenario"] for r in pool}), "pool": len(pool), "pool_screen_hit": len(hit),
                         "sampled": len(sheet), "sampled_screen_hit": n_hit}
    report["overlap"] = len({key[k]["scenario"] for k in key if k.startswith("dev")}
                            & {key[k]["scenario"] for k in key if k.startswith("test")})
    truth = [{"scenario": sid, "player": t["player"], "label": t["truth_predicate"]}
             for _, folder in SOURCES for sid, s in scenario_turns(folder).items() for t in s["turns"]]
    truth = rng.sample(truth, TRUTH_N)
    write_sheet(LABELS / "truth_audit.csv",
                [{"id": f"t{i:03d}", "player": t["player"], "given_label": PRED_KO[t["label"]], "ok": "", "note": ""}
                 for i, t in enumerate(truth, 1)], ["id", "player", "given_label", "ok", "note"])
    key["_truth"] = truth
    (LABELS / "gold_key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")
    report["truth_audit"] = dict(Counter(t["label"] for t in truth))
    print(json.dumps(report, indent=1, ensure_ascii=False))


def read_sheet(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def check_sheet() -> None:
    out = LABELS / "human_check.csv"
    if out.exists() or any(LABELS.glob("llm_*.csv")):
        raise SystemExit("human_check must be drawn once, before LLM labels exist")
    rng = random.Random(SEED + 1)
    rows = [{"id": r["id"], "kind": "speech", "player": r["player"], "evidence": r["evidence"],
             "shown": r["response"], "label": "", "note": ""}
            for split in ("dev", "test") for r in rng.sample(read_sheet(LABELS / f"gold_{split}.csv"), 30)]
    rows += [{"id": r["id"], "kind": "truth", "player": r["player"], "evidence": "",
              "shown": r["given_label"], "label": "", "note": ""}
             for r in rng.sample(read_sheet(LABELS / "truth_audit.csv"), 30)]
    rng.shuffle(rows)
    write_sheet(out, rows, ["id", "kind", "player", "evidence", "shown", "label", "note"])
    print(json.dumps(dict(Counter(r["kind"] for r in rows)), ensure_ascii=False))


def kappa(pairs: list[tuple[int, int]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def agree() -> None:
    human = {r["id"]: r for r in read_sheet(LABELS / "human_check.csv")}
    llm = {r["id"]: r.get("label") or r.get("ok") for f in ("llm_gold_dev", "llm_gold_test", "llm_truth_audit")
           for r in read_sheet(LABELS / f"{f}.csv")}
    missing = [i for i, r in human.items() if r["label"].strip() not in ("0", "1")]
    if missing:
        raise SystemExit(f"human_check unlabeled rows: {missing}")
    out, rng = {}, random.Random(SEED + 2)
    for kind in ("speech", "truth"):
        pairs = [(int(r["label"]), int(llm[i])) for i, r in human.items() if r["kind"] == kind]
        boots = sorted(kappa([pairs[rng.randrange(len(pairs))] for _ in pairs]) for _ in range(2000))
        out[kind] = {"n": len(pairs), "agreement": sum(a == b for a, b in pairs) / len(pairs),
                     "kappa": kappa(pairs), "kappa_ci95": [boots[50], boots[1949]],
                     "human_pos": sum(a for a, _ in pairs), "llm_pos": sum(b for _, b in pairs),
                     "disagree": [i for i, r in human.items() if r["kind"] == kind and int(r["label"]) != int(llm[i])]}
    out["llm_labels_adopted"] = out["speech"]["kappa"] >= 0.8 and out["truth"]["agreement"] >= 0.9
    (CP / "results/measure").mkdir(parents=True, exist_ok=True)
    (CP / "results/measure/label_agreement.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


JUDGE_FREEZE = CP / "logs/measure/judge_freeze.json"
SAMPLE_VALUES = {"item": "양초", "stock": 3, "reserved": 1, "unit_price": 2, "items": "양초, 밧줄", "quantity": 1,
                 "total_price": 2}


def adjudicate(split: str) -> None:
    out = LABELS / f"adj_gold_{split}.csv"
    if split == "test" and not JUDGE_FREEZE.exists():
        raise SystemExit("freeze the judge before adjudicating the test split")
    a = {r["id"]: r for r in read_sheet(LABELS / f"llm_gold_{split}.csv")}
    b = {r["id"]: r for r in read_sheet(LABELS / f"llm2_gold_{split}.csv")}
    final = {r["id"]: r for r in read_sheet(out)} if out.exists() else {}
    rows, pending = [], []
    for rid, r in a.items():
        if a[rid]["label"] == b[rid]["label"]:
            label, how = a[rid]["label"], "agree"
        else:
            label, how = final.get(rid, {}).get("label", ""), "adjudicated"
            if label not in ("0", "1"):
                pending.append(rid)
        rows.append({**{k: r[k] for k in ("id", "evidence", "player", "response")}, "label": label, "note": how,
                     "llm1": a[rid]["label"], "llm2": b[rid]["label"]})
    write_sheet(out, rows, ["id", "evidence", "player", "response", "label", "note", "llm1", "llm2"])
    pairs = [(int(a[i]["label"]), int(b[i]["label"])) for i in a]
    print(json.dumps({"split": split, "n": len(pairs), "llm_llm_kappa": kappa(pairs),
                      "disagree": sum(x != y for x, y in pairs), "pending": pending}, ensure_ascii=False))


def freeze_judge() -> None:
    if JUDGE_FREEZE.exists():
        raise SystemExit("judge already frozen")
    if any(r["label"] not in ("0", "1") for r in read_sheet(LABELS / "adj_gold_dev.csv")):
        raise SystemExit("dev adjudication incomplete")
    JUDGE_FREEZE.parent.mkdir(parents=True, exist_ok=True)
    JUDGE_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "label_source": "llm_adjudicated",
                                        "test_adjudicated_before_freeze": (LABELS / "adj_gold_test.csv").exists(),
                                        "hashes": {f: sha(CP / f) for f in ("measure_judge.py", "docs/오염_코드북.md")}},
                                       indent=1, ensure_ascii=False), encoding="utf-8")
    print(JUDGE_FREEZE.read_text(encoding="utf-8"))


def validate() -> None:
    import measure_judge as mj
    freeze = json.loads(JUDGE_FREEZE.read_text(encoding="utf-8"))
    if any(sha(CP / f) != h for f, h in freeze["hashes"].items()):
        raise SystemExit("judge changed after freeze")
    key = json.loads((LABELS / "gold_key.json").read_text(encoding="utf-8"))
    rows = read_sheet(LABELS / "adj_gold_test.csv")
    if any(r["label"] not in ("0", "1") for r in rows):
        raise SystemExit("test adjudication incomplete")
    rng = random.Random(SEED + 3)

    def metrics(sample: list[dict]) -> tuple[float, float]:
        tp = sum(key[r["id"]]["weight"] for r in sample if r["label"] == "1" and mj.judge(r["response"]))
        fp = sum(key[r["id"]]["weight"] for r in sample if r["label"] == "0" and mj.judge(r["response"]))
        fn = sum(key[r["id"]]["weight"] for r in sample if r["label"] == "1" and not mj.judge(r["response"]))
        return tp / max(1e-9, tp + fp), tp / max(1e-9, tp + fn)

    p, r = metrics(rows)
    boots = [metrics([rows[rng.randrange(len(rows))] for _ in rows]) for _ in range(2000)]
    ps, rs = sorted(b[0] for b in boots), sorted(b[1] for b in boots)
    out = {"n": len(rows), "weighted_precision": p, "weighted_recall": r, "f1": 2 * p * r / max(1e-9, p + r),
           "precision_ci95": [ps[50], ps[1949]], "recall_ci95": [rs[50], rs[1949]],
           "passes": p >= 0.8 and r >= 0.8, "label_source": freeze["label_source"], "judge_frozen_at": freeze["frozen_at_utc"]}
    (CP / "results/measure/judge_validation.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


def templates() -> None:
    import measure_judge as mj
    import speech_variants as sv
    from npc import speech
    manual = json.loads((CP / "logs/measure/template_manual.json").read_text(encoding="utf-8"))
    original = [(k, v) for k, v in speech.TEMPLATES.items() if "{policy_line}" not in v]
    original += [(f"stock_and_policy+{pk}", speech.TEMPLATES["stock_and_policy"].replace("{policy_line}", pv))
                 for pk, pv in speech.POLICY_LINES.items()]
    sets = {"original": original, "v2": sv.all_rendered_variants()}
    out = {name: {"rendered": len(items),
                  "judge_flagged": [t for k, t in items if mj.judge(t.format_map(SAMPLE_VALUES))]}
           for name, items in sets.items()}
    out["original"]["manual_codebook_contaminating"] = manual["contaminating"]
    out["v2"]["manual_codebook_contaminating"] = 0
    out["v2"]["manual_note"] = ("author review against docs/오염_코드북.md: no variant accepts a claim or grants a claimed "
                                "benefit; slots carry only engine facts / price table / fixed policy lines")
    out["contaminating"] = sum(len(v["judge_flagged"]) + v["manual_codebook_contaminating"] for v in out.values()
                               if isinstance(v, dict))
    (CP / "results/measure").mkdir(parents=True, exist_ok=True)
    (CP / "results/measure/template_audit.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    from nlu_confirm import now, sha
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["sample", "check-sheet", "agree", "adjudicate", "freeze-judge", "validate",
                                        "templates"])
    ap.add_argument("split", nargs="?", choices=["dev", "test"])
    a = ap.parse_args()
    {"sample": sample, "check-sheet": check_sheet, "agree": agree, "adjudicate": lambda: adjudicate(a.split),
     "freeze-judge": freeze_judge, "validate": validate, "templates": templates}[a.command]()
