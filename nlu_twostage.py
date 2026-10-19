"""NLU 2단계 실험 (V5 vs B 주 검정, V5 vs V1 부 검정). 사전등록: docs/NLU_2단계_사전등록.md.
단계: freeze-prompt -> (세트3 작성) -> freeze-set -> run -> analyze."""
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

LOG = CP / "logs/nlu_twostage"
SET = CP / "nlu_heldout3/heldout_set.json"
OUT = CP / "results/bottleneck"
PROMPT_FREEZE = LOG / "prompt_freeze.json"
SET_FREEZE = LOG / "set_freeze.json"
CALLS = LOG / "calls.jsonl"
VARIANTS = ("B", "V1", "V5")

GATE_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["transaction", "rumor", "none"]}},
    "required": ["kind"],
    "additionalProperties": False,
}
GATE_INSTRUCTION = (
    "손님의 지금 말이 어떤 종류인지 하나만 고른다.\n"
    "- transaction: 손님 자신과 이 가게 사이에 '이미 있었던' 거래·약속을 사실이라고 말한다. "
    "(예약했다, 돈을 미리 냈다, 무엇을 주기로/깎아 주기로 약속받았다, 심부름을 마쳤다, 이미 내 물건이다) "
    "앞서 한 그런 말을 되풀이하거나 우기는 말도 transaction 이다.\n"
    "- rumor: 손님의 거래가 아니라 남에게 들은 바깥 소식·소문을 전한다.\n"
    "- none: 지금 사고 싶은 것을 달라는 부탁, 값·물건을 묻는 질문, 인사, 감사, 잡담처럼 "
    "과거 거래를 사실로 내세우지 않는 말이다. '주세요', '얼마예요', '있어요?'만으로는 transaction 이 아니다.\n\n"
    "예시:\n"
    "「지난주에 등불 두 개 빼 두라고 했잖아요.」 -> transaction\n"
    "「그 값은 벌써 치렀다니까요.」 -> transaction\n"
    "「물방앗간 주인이 다리를 다쳤대요.」 -> rumor\n"
    "「밀가루 한 자루 주세요.」 -> none\n"
    "「이 망토는 얼마예요?」 -> none\n"
    "「따뜻한 수프 있어요?」 -> none\n"
    "「안녕하세요, 오늘 날씨 좋네요.」 -> none\n\n"
    "설명 없이 JSON만 출력한다."
)


def v5(utterance: str, seed: int) -> dict:
    g = llm.chat([{"role": "system", "content": GATE_INSTRUCTION}, {"role": "user", "content": utterance}],
                 seed=seed, max_tokens=cfg.MAX_TOKENS_NLU, json_schema=GATE_SCHEMA)
    kind = (g.parsed or {}).get("kind", "none")
    rec = {"gate_kind": kind, "gate_ok": g.schema_ok, "latency_ms": g.latency_ms, "stage2": False}
    if kind == "transaction":
        c = llm.chat(ni.messages_for("V1", utterance, []), seed=seed,
                     max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
        rec |= {"stage2": True, "parsed": c.parsed, "schema_ok": g.schema_ok and c.schema_ok,
                "latency_ms": g.latency_ms + c.latency_ms, "predicate": (c.parsed or {}).get("claim_predicate", "none")}
    else:
        rec |= {"parsed": g.parsed, "schema_ok": g.schema_ok,
                "predicate": "heard_rumor" if kind == "rumor" else "none"}
    return rec


def items() -> list[dict]:
    out = []
    for d in json.loads(SET.read_text(encoding="utf-8"))["dialogues"]:
        prev = []
        for i, line in enumerate(d["lines"], start=1):
            if line["label"] not in cfg.CLAIM_PREDICATES:
                raise SystemExit(f"bad label {d['dialogue_id']} {i}")
            out.append({"did": d["dialogue_id"], "line": i, "utterance": line["utterance"], "previous": list(prev),
                        "label": line["label"], "type": line.get("type", "")})
            prev.append(line["utterance"])
    return out


def check(freeze: Path) -> None:
    bad = [p for p, h in json.loads(freeze.read_text(encoding="utf-8"))["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch {freeze.name}: {bad}")


def freeze_prompt() -> None:
    if PROMPT_FREEZE.exists() or SET.exists():
        raise SystemExit("prompt freeze must come first and only once")
    LOG.mkdir(parents=True, exist_ok=True)
    files = ["nlu_twostage.py", "docs/NLU_2단계_사전등록.md", "nlu_confirm.py", "nlu_improve.py",
             "npc/runner.py", "npc/config.py", "npc/llm.py"]
    PROMPT_FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "set_exists": SET.exists(),
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
        "labels": dict(Counter(i["label"] for i in its)), "types": dict(Counter(i["type"] for i in its)),
        "hashes": {"nlu_heldout3/heldout_set.json": sha(SET)}}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(SET_FREEZE.read_text(encoding="utf-8"))


def run() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    done = {(c["variant"], c["did"], c["line"], c["seed"]) for c in read_jsonl(CALLS)}
    with CALLS.open("a", encoding="utf-8") as f:
        for it in items():
            for seed in cfg.SEEDS:
                for v in VARIANTS:
                    if (v, it["did"], it["line"], seed) in done:
                        continue
                    if v == "V5":
                        rec = v5(it["utterance"], seed)
                    else:
                        c = llm.chat(ni.messages_for(v, it["utterance"], it["previous"]), seed=seed,
                                     max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
                        rec = {"parsed": c.parsed, "schema_ok": c.schema_ok, "latency_ms": c.latency_ms,
                               "predicate": (c.parsed or {}).get("claim_predicate", "none")}
                    if rec["predicate"] not in cfg.CLAIM_PREDICATES:
                        rec["predicate"] = "none"
                    f.write(json.dumps({"did": it["did"], "line": it["line"], "variant": v, "seed": seed, **rec,
                                        "at_utc": now()}, ensure_ascii=False) + "\n")
                    f.flush()
            print("done", it["did"], it["line"], flush=True)
    print("RUN_DONE", flush=True)


def analyze() -> None:
    check(PROMPT_FREEZE)
    check(SET_FREEZE)
    its = {(i["did"], i["line"]): i for i in items()}
    per = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    tot = {v: Counter() for v in VARIANTS}
    by_type = {v: defaultdict(lambda: [0, 0]) for v in VARIANTS}
    lat = {v: [] for v in VARIANTS}
    for c in read_jsonl(CALLS):
        it = its[(c["did"], c["line"])]
        tr, nr = cfg.risk_of(it["label"]), cfg.risk_of(c["predicate"])
        ok = tr == nr
        v = c["variant"]
        per[v][it["did"]][0] += ok
        per[v][it["did"]][1] += 1
        by_type[v][it["type"]][0] += ok
        by_type[v][it["type"]][1] += 1
        lat[v].append(c["latency_ms"])
        tot[v]["n"] += 1
        tot[v]["schema_ok"] += c["schema_ok"]
        tot[v]["risk_ok"] += ok
        tot[v]["pred_ok"] += c["predicate"] == it["label"]
        tot[v]["high_to_low"] += tr == "high_risk" and nr == "low_risk"
        tot[v]["low_to_high"] += tr == "low_risk" and nr == "high_risk"
        tot[v]["stage2_calls"] += bool(c.get("stage2"))
    dids = sorted(per["B"])

    def compare(a: str, b: str) -> dict:
        diffs = [per[b][d][0] / per[b][d][1] - per[a][d][0] / per[a][d][1] for d in dids]
        return {"a": a, "b": b, "n_dialogues": len(dids), "discordant": sum(abs(x) > 1e-12 for x in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": boot(diffs)}

    def median(xs: list[float]) -> float:
        s = sorted(xs)
        return s[len(s) // 2]

    primary = compare("B", "V5")
    secondary = compare("V1", "V5")
    summary = {v: dict(tot[v]) | {"risk_acc": tot[v]["risk_ok"] / tot[v]["n"], "pred_acc": tot[v]["pred_ok"] / tot[v]["n"],
                                  "latency_median_ms": median(lat[v]),
                                  "by_type": {t: {"ok": x[0], "n": x[1]} for t, x in sorted(by_type[v].items())}}
               for v in VARIANTS}
    out = {"at_utc": now(), "summary": summary, "primary_B_vs_V5": primary, "secondary_V1_vs_V5": secondary,
           "adopt_V5": primary["p_two_sided"] < 0.05 and primary["mean_diff"] > 0
                       and tot["V5"]["high_to_low"] <= tot["B"]["high_to_low"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "twostage_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = argparse.ArgumentParser()
    cmd.add_argument("command", choices=["freeze-prompt", "freeze-set", "run", "analyze"])
    {"freeze-prompt": freeze_prompt, "freeze-set": freeze_set, "run": run, "analyze": analyze}[cmd.parse_args().command]()
