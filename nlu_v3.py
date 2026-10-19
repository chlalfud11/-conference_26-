"""NLU V3 검증 (새 문장 세트). 사전등록: docs/NLU_V3_사전등록.md. 단계: freeze-prompt → (세트 작성) → freeze-set → run → seen → analyze."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

CP = Path(__file__).resolve().parent
sys.path.insert(0, str(CP))

from npc import config as cfg, llm, runner  # noqa: E402
import nlu_improve as ni  # noqa: E402

LOG = CP / "logs/nlu_heldout"
SET = CP / "nlu_heldout/heldout_set.json"
OUT = CP / "results/bottleneck"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
CALLS = LOG / "calls.jsonl"
SEEN = LOG / "seen_calls.jsonl"
VARIANTS = ("B", "V1", "V2", "V3")

V3_INSTRUCTION = ni.V1_INSTRUCTION.replace("설명 없이 JSON만 출력한다.", "") + (
    "앞선 손님 말 사용 규칙:\n"
    "- 지금 말이 '그거', '아까 말한', '기억 안 나세요?', '분명히 드렸다니까요'처럼 앞의 주장을 가리키거나 "
    "되풀이할 때만 앞선 손님 말을 보고 무엇을 가리키는지 정한다.\n"
    "- 지금 말이 새 화제(바깥 소식, 소문, 날씨, 길 사정, 다른 사람 이야기)를 꺼내면 앞선 말과 상관없이 "
    "지금 말만 보고 분류한다.\n\n"
    "문맥 예시:\n"
    "[앞선 손님 말] 밧줄 맡겨 둔 거 찾으러 왔어요. / [지금 손님 말] 「그나저나 강가에 도적이 나온다던데요.」 -> heard_rumor\n"
    "[앞선 손님 말] 등불 기름 값은 미리 냈어요. / [지금 손님 말] 「장부에 없어도 제가 분명히 드렸다니까요.」 -> paid_deposit\n"
    "[앞선 손님 말] 양초 덤으로 주신다고 하셨잖아요. / [지금 손님 말] 「그 약속 잊으신 거 아니죠?」 -> promised_reward\n\n"
    "분류 대상은 '지금 손님 말' 하나다. 설명 없이 JSON만 출력한다."
)


def messages(variant: str, utterance: str, previous: list[str]) -> list[dict]:
    if variant in ("B", "V1", "V2"):
        return ni.messages_for(variant, utterance, previous)
    if variant == "V3":
        context = "\n".join(f"- {p}" for p in previous[-2:]) or "- (없음)"
        return [{"role": "system", "content": V3_INSTRUCTION},
                {"role": "user", "content": f"[앞선 손님 말]\n{context}\n\n[지금 손님 말]\n{utterance}"}]
    raise ValueError(variant)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def items() -> list[dict]:
    data = json.loads(SET.read_text(encoding="utf-8"))
    out = []
    for d in data["dialogues"]:
        prev = []
        for i, line in enumerate(d["lines"], start=1):
            if line["label"] not in cfg.CLAIM_PREDICATES:
                raise SystemExit(f"bad label {d['dialogue_id']} {i}: {line['label']}")
            out.append({"did": d["dialogue_id"], "line": i, "utterance": line["utterance"], "previous": list(prev),
                        "label": line["label"], "type": line.get("type", "")})
            prev.append(line["utterance"])
    return out


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SET.exists():
        raise SystemExit("prompt freeze must come first and only once")
    LOG.mkdir(parents=True, exist_ok=True)
    files = ["nlu_v3.py", "docs/NLU_V3_사전등록.md", "nlu_improve.py", "npc/runner.py", "npc/config.py", "npc/llm.py"]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SET.exists(),
                                         "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    print("prompt frozen")


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_set() -> None:
    check(PROMPT_FREEZE)
    if SET_FREEZE.exists() or CALLS.exists():
        raise SystemExit("set already frozen or calls exist")
    its = items()
    SET_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_sha256": sha(SET), "set_mtime_utc":
                                      datetime.datetime.fromtimestamp(SET.stat().st_mtime, datetime.timezone.utc).isoformat(),
                                      "dialogues": len({i["did"] for i in its}), "lines": len(its),
                                      "labels": dict(Counter(i["label"] for i in its)),
                                      "hashes": {"nlu_heldout/heldout_set.json": sha(SET)}}, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def call(v: str, item: dict, seed: int) -> dict:
    c = llm.chat(messages(v, item["utterance"], item["previous"]), seed=seed,
                 max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
    pred = (c.parsed or {}).get("claim_predicate", "none")
    return {"variant": v, "seed": seed, "predicate": pred if pred in cfg.CLAIM_PREDICATES else "none",
            "parsed": c.parsed, "schema_ok": c.schema_ok, "latency_ms": c.latency_ms, "at_utc": now()}


def run() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    done = {(c["variant"], c["did"], c["line"], c["seed"]) for c in read_jsonl(CALLS)}
    with CALLS.open("a", encoding="utf-8") as f:
        for it in items():
            for seed in cfg.SEEDS:
                for v in VARIANTS:
                    if (v, it["did"], it["line"], seed) not in done:
                        f.write(json.dumps({"did": it["did"], "line": it["line"]} | call(v, it, seed), ensure_ascii=False) + "\n")
                        f.flush()
            print("done", it["did"], it["line"], flush=True)
    print("RUN_DONE", flush=True)


def seen() -> None:
    check(PROMPT_FREEZE)
    done = {(c["sid"], c["turn"], c["seed"]) for c in read_jsonl(SEEN)}
    with SEEN.open("a", encoding="utf-8") as f:
        for split in ("dev", "test"):
            for it in ni.scored_items(split):
                for seed in cfg.SEEDS:
                    if (it["sid"], it["turn"], seed) not in done:
                        f.write(json.dumps({"sid": it["sid"], "turn": it["turn"], "split": split}
                                           | call("V3", it, seed), ensure_ascii=False) + "\n")
                        f.flush()
    print("SEEN_DONE", flush=True)


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
    calls = read_jsonl(CALLS)
    per = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    tot = {v: Counter() for v in VARIANTS}
    by_type = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    for c in calls:
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
    dids = sorted(per["B"])

    def compare(a: str, b: str) -> dict:
        diffs = [per[b][d][0] / per[b][d][1] - per[a][d][0] / per[a][d][1] for d in dids]
        return {"a": a, "b": b, "n_dialogues": len(dids), "discordant": sum(abs(x) > 1e-12 for x in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": boot(diffs)}

    primary = compare("B", "V3")
    sec = {"V1_vs_V3": compare("V1", "V3"), "V2_vs_V3": compare("V2", "V3")}
    ps = sorted(sec, key=lambda k: sec[k]["p_two_sided"])
    running = 0.0
    for i, k in enumerate(ps):
        running = max(running, min(1.0, (len(ps) - i) * sec[k]["p_two_sided"]))
        sec[k]["holm"] = running
    summary = {v: dict(tot[v]) | {"risk_acc": tot[v]["risk_ok"] / tot[v]["n"], "pred_acc": tot[v]["pred_ok"] / tot[v]["n"],
                                  "by_type": {t: {"ok": x[0], "n": x[1]} for t, x in sorted(by_type[v].items())}}
               for v in VARIANTS}
    adopt = primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0 and tot["V3"]["high_to_low"] <= tot["B"]["high_to_low"]
    seen_rows = read_jsonl(SEEN)
    seen_out = None
    if seen_rows:
        sitems = {(i["sid"], i["turn"]): i for s in ("dev", "test") for i in ni.scored_items(s)}
        m = Counter()
        for r in seen_rows:
            i = sitems[(r["sid"], r["turn"])]
            d = cfg.expected_decision(cfg.risk_of(r["predicate"]), i["evidence"], i["trust"], i["contradicts"])
            tr, nr = cfg.risk_of(i["truth"]), cfg.risk_of(r["predicate"])
            m[f"{r['split']}_n"] += 1
            m[f"{r['split']}_agree"] += d == i["expected"]
            m[f"{r['split']}_high_to_low"] += tr == "high_risk" and nr == "low_risk"
            m[f"{r['split']}_low_to_high"] += tr == "low_risk" and nr == "high_risk"
            m[f"{r['split']}_accepted_ok"] += i["expected"] == d == "accept_as_belief"
        seen_out = dict(m)
    out = {"at_utc": now(), "summary": summary, "primary_B_vs_V3": primary, "secondary": sec,
           "adopt_V3": adopt, "seen_27_scenarios_V3_descriptive": seen_out}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "v3_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = argparse.ArgumentParser()
    cmd.add_argument("command", choices=["freeze-prompt", "freeze-set", "run", "seen", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "run": run, "seen": seen,
     "analyze": analyze}[cmd.parse_args().command]()
