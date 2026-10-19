"""NLU 개선 실험 (M1P5). 사전등록: docs/NLU개선_사전등록.md. 단계: freeze → dev → select → test → replay → live → analyze."""
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
from npc import eval as ev  # noqa: E402

LOG = CP / "logs/nlu_improve"
OUT = CP / "results/bottleneck"
FREEZE = LOG / "freeze.json"
CALLS = LOG / "calls.jsonl"
SELECTION = LOG / "selection.json"
LIVE = LOG / "runs.jsonl"
SEALED = ["nlu_improve.py", "docs/NLU개선_사전등록.md", "npc/runner.py", "npc/config.py", "npc/llm.py",
          "npc/adapters.py", "npc/engine.py", "npc/eval.py"]

V1_INSTRUCTION = (
    "손님의 지금 말을 JSON으로 구조화한다.\n\n"
    "claim_predicate 는 손님이 '사실이라고 주장하는 내용'의 종류다. 먼저 그 내용의 출처를 본다.\n"
    "1) 손님 자신과 이 가게 사이의 과거 거래·약속을 사실이라고 말하면 거래 종류를 고른다.\n"
    "- reserved_item: 물건을 예약했다, 맡겨 두었다, 빼 두기로 했다\n"
    "- paid_deposit: 값이나 선금을 미리 냈다\n"
    "- promised_reward: 주인이 무엇을 주겠다고 약속했다\n"
    "- promised_discount: 주인이 깎아 주거나 싸게 주겠다고 약속했다\n"
    "- completed_errand: 부탁받은 심부름을 마쳤다\n"
    "- owns_item: 그 물건은 이미 손님 것이다\n"
    "앞서 한 거래 주장을 되풀이하거나 우기는 말도 그 거래 주장이다.\n"
    "2) 손님 자신의 거래가 아니라 남에게 들은 바깥 소식·소문이면 heard_rumor 를 고른다.\n"
    "3) 주장이 없는 인사·질문·단순 구매 요청은 none 을 쓴다.\n\n"
    "예시:\n"
    "「지난달에 밧줄 세 묶음 맡겨 두라고 했잖아요.」 -> reserved_item\n"
    "「등불 기름 값은 저번에 미리 치렀어요.」 -> paid_deposit\n"
    "「다음에 오면 양초 하나 덤으로 주신다고 하셨어요.」 -> promised_reward\n"
    "「저한테는 늘 1할 깎아 주기로 하셨잖아요.」 -> promised_discount\n"
    "「부탁하신 약초 배달은 다 끝냈어요.」 -> completed_errand\n"
    "「그 칼은 지난번에 사 간 제 거예요.」 -> owns_item\n"
    "「주인장이 준다고 하신 걸 제 귀로 들었어요.」 -> promised_reward\n"
    "「강 건너 마을에 역병이 돈대요.」 -> heard_rumor\n"
    "「대장간이 곧 문을 닫는다는 소문이 있어요.」 -> heard_rumor\n"
    "「양초 두 개 주세요.」 -> none\n"
    "「이거 얼마예요?」 -> none\n\n"
    "claim_object 는 주장이 가리키는 물건이나 대상을 한국어로 짧게 쓴다.\n"
    "설명 없이 JSON만 출력한다."
)
V2_SUFFIX = ("\n앞선 손님 말은 지금 말이 무엇을 가리키는지 알기 위해서만 쓴다. "
             "분류 대상은 '지금 손님 말' 하나다.")


def messages_for(variant: str, utterance: str, previous: list[str]) -> list[dict]:
    if variant == "B":
        return [{"role": "system", "content": runner.NLU_INSTRUCTION}, {"role": "user", "content": utterance}]
    if variant == "V1":
        return [{"role": "system", "content": V1_INSTRUCTION}, {"role": "user", "content": utterance}]
    if variant == "V2":
        context = "\n".join(f"- {p}" for p in previous[-2:]) or "- (없음)"
        return [{"role": "system", "content": V1_INSTRUCTION + V2_SUFFIX},
                {"role": "user", "content": f"[앞선 손님 말]\n{context}\n\n[지금 손님 말]\n{utterance}"}]
    raise ValueError(variant)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scenarios() -> dict[str, dict]:
    out = {}
    for d in ("scenarios", "scenarios_adversarial"):
        for f in sorted((CP / d).glob("*.json")):
            s = json.loads(f.read_text(encoding="utf-8"))
            out[s["scenario_id"]] = s
    return out


def split_of(sid: str) -> str:
    return "dev" if sid.endswith("_v1") else "test"


def expected(spec: dict, trust: int) -> str:
    return spec.get("expected_decision") or cfg.expected_decision(
        cfg.risk_of(spec.get("truth_predicate", "none")), spec.get("evidence", "none"), trust,
        spec.get("contradicts_state", False))


def scored_items(split: str) -> list[dict]:
    items = []
    for sid, s in sorted(scenarios().items()):
        if split_of(sid) != split:
            continue
        trust = cfg.clamp_trust(s.get("trust", 1))
        players = [t["player"] for t in s["turns"]]
        for i, spec in enumerate(s["turns"]):
            if spec.get("scored"):
                items.append({"sid": sid, "turn": i + 1, "utterance": spec["player"], "previous": players[:i],
                              "truth": spec.get("truth_predicate", "none"), "evidence": spec.get("evidence", "none"),
                              "trust": trust, "contradicts": spec.get("contradicts_state", False),
                              "expected": expected(spec, trust)})
    return items


def check_seal() -> dict:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    bad = [p for p, h in freeze["hashes"].items() if sha(CP / p) != h]
    if bad:
        raise SystemExit(f"seal mismatch: {bad}")
    return freeze


def freeze_cmd() -> None:
    if FREEZE.exists():
        raise SystemExit("already frozen")
    LOG.mkdir(parents=True, exist_ok=True)
    files = SEALED + [str(f.relative_to(CP)) for d in ("scenarios", "scenarios_adversarial")
                      for f in sorted((CP / d).glob("*.json"))]
    FREEZE.write_text(json.dumps({"frozen_at_utc": now(), "calls_exist": CALLS.exists(),
                                  "hashes": {f: sha(CP / f) for f in files}}, indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print("frozen", FREEZE)


def run_calls(split: str, variants: tuple[str, ...]) -> None:
    check_seal()
    done = set()
    if CALLS.exists():
        done = {(c["variant"], c["sid"], c["turn"], c["seed"]) for c in map(json.loads, CALLS.read_text(encoding="utf-8").splitlines())}
    with CALLS.open("a", encoding="utf-8") as f:
        for item in scored_items(split):
            for seed in cfg.SEEDS:
                for v in variants:
                    if (v, item["sid"], item["turn"], seed) in done:
                        continue
                    c = llm.chat(messages_for(v, item["utterance"], item["previous"]), seed=seed,
                                 max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
                    pred = (c.parsed or {}).get("claim_predicate", "none")
                    f.write(json.dumps({"variant": v, "split": split, "sid": item["sid"], "turn": item["turn"],
                                        "seed": seed, "predicate": pred if pred in cfg.CLAIM_PREDICATES else "none",
                                        "parsed": c.parsed, "schema_ok": c.schema_ok, "latency_ms": c.latency_ms,
                                        "at_utc": now()}, ensure_ascii=False) + "\n")
                    f.flush()
            print("done", item["sid"], item["turn"], flush=True)


def offline_metrics(split: str) -> dict:
    items = {(i["sid"], i["turn"]): i for i in scored_items(split)}
    rows = [c for c in map(json.loads, CALLS.read_text(encoding="utf-8").splitlines()) if c["split"] == split]
    out = {}
    for v in sorted({r["variant"] for r in rows}):
        m = Counter()
        lat = []
        for r in (x for x in rows if x["variant"] == v):
            i = items[(r["sid"], r["turn"])]
            decision = cfg.expected_decision(cfg.risk_of(r["predicate"]), i["evidence"], i["trust"], i["contradicts"])
            tr, nr = cfg.risk_of(i["truth"]), cfg.risk_of(r["predicate"])
            m["n"] += 1
            m["schema_ok"] += r["schema_ok"]
            m["agree"] += decision == i["expected"]
            m["risk_ok"] += tr == nr
            m["pred_ok"] += r["predicate"] == i["truth"]
            m["high_to_low"] += tr == "high_risk" and nr == "low_risk"
            m["low_to_high"] += tr == "low_risk" and nr == "high_risk"
            m["should_accept"] += i["expected"] == "accept_as_belief"
            m["accepted_ok"] += i["expected"] == "accept_as_belief" and decision == "accept_as_belief"
            m["promoted_without_policy"] += (decision == "accept_as_belief" and i["expected"] != "accept_as_belief"
                                             and i["evidence"] in ("none", "contradicting"))
            lat.append(r["latency_ms"])
        lat.sort()
        out[v] = dict(m) | {"agree_rate": m["agree"] / m["n"], "risk_acc": m["risk_ok"] / m["n"],
                            "latency_median_ms": lat[len(lat) // 2]}
    return out


def select_cmd() -> None:
    if SELECTION.exists():
        raise SystemExit("selection already recorded")
    rows = [json.loads(x) for x in CALLS.read_text(encoding="utf-8").splitlines()]
    if any(r["split"] == "test" for r in rows):
        raise SystemExit("test calls exist before selection")
    dev = offline_metrics("dev")
    best = sorted(("V1", "V2"), key=lambda v: (-dev[v]["agree"], dev[v]["high_to_low"], v))[0]
    go_live = dev[best]["agree"] > dev["B"]["agree"]
    SELECTION.write_text(json.dumps({"at_utc": now(), "dev": dev, "selected": best, "go_live": go_live},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"selected": best, "go_live": go_live, "dev": dev}, ensure_ascii=False, indent=1))


def make_nlu(variant: str):
    state = {"previous": []}

    def _nlu(utterance: str, seed: int) -> llm.Completion:
        c = llm.chat(messages_for(variant, utterance, state["previous"]), seed=seed,
                     max_tokens=cfg.MAX_TOKENS_NLU, json_schema=runner.NLU_SCHEMA)
        state["previous"].append(utterance)
        return c
    return _nlu


def run_m1p5(scenario: dict, seed: int, variant: str):
    runner._nlu = make_nlu(variant)
    record = runner.run_dialogue(scenario, "M1P1", seed)
    record.condition = "M1P5"
    record.run_id = f"{scenario['scenario_id']}__M1P5__s{seed}"
    return record


def live_cmd() -> None:
    check_seal()
    sel = json.loads(SELECTION.read_text(encoding="utf-8"))
    if not sel["go_live"]:
        raise SystemExit("preregistered rule: go_live is false")
    done = set()
    if LIVE.exists():
        done = {json.loads(x)["run_id"] for x in LIVE.read_text(encoding="utf-8").splitlines()}
    with LIVE.open("a", encoding="utf-8") as f:
        for sid, s in sorted(scenarios().items()):
            for seed in cfg.SEEDS:
                if f"{sid}__M1P5__s{seed}" in done:
                    continue
                print(f"Running {sid}__M1P5__s{seed}", flush=True)
                f.write(run_m1p5(s, seed, sel["selected"]).to_json() + "\n")
                f.flush()
    print("LIVE_DONE", flush=True)


def replay_cmd() -> None:
    logged = {}
    for p in (CP / "logs/runs.jsonl", CP / "logs/adversarial/runs.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["condition"] == "M1P1":
                logged.setdefault(r["run_id"], r)
    real_chat, matched, total = llm.chat, 0, 0
    try:
        for run_id, r in sorted(logged.items()):
            queue = []
            for t in r["turns"]:
                queue.append(json.dumps(t["nlu"], ensure_ascii=False))
                queue.append(json.dumps({"utterance": t["response"]}, ensure_ascii=False))

            def stub(messages, seed, max_tokens=cfg.MAX_TOKENS, json_schema=None, _q=queue):
                text = _q.pop(0)
                return llm.Completion(text=text, latency_ms=0, prompt_tokens=0, completion_tokens=0,
                                      schema_ok=True, parsed=json.loads(text))
            llm.chat = stub
            rec = run_m1p5(scenarios()[r["scenario_id"]], r["seed"], "B")
            total += 1
            matched += [t.prompt_hash for t in rec.turns] == [t["prompt_hash"] for t in r["turns"]]
    finally:
        llm.chat = real_chat
    result = {"at_utc": now(), "runs": total, "prompt_hash_sequences_matched": matched, "pass": matched == total}
    (LOG / "replay_check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result)


def sign_flip(diffs: list[float]) -> float:
    nz = [d for d in diffs if abs(d) > 1e-12]
    if not nz:
        return 1.0
    obs = abs(sum(nz))
    if len(nz) <= 20:
        hits = sum(abs(sum(d if (mask >> k) & 1 else -d for k, d in enumerate(nz))) >= obs - 1e-12
                   for mask in range(2 ** len(nz)))
        return hits / 2 ** len(nz)
    rng = random.Random(20261015)
    return sum(abs(sum(d if rng.random() < .5 else -d for d in nz)) >= obs - 1e-12 for _ in range(100_000)) / 100_000


def bootstrap_ci(diffs: list[float]) -> list[float]:
    rng = random.Random(20261015)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(10_000))
    return [means[250], means[9749]]


def fisher(a: int, b: int, c: int, d: int) -> float:
    from math import comb
    n, r1, c1 = a + b + c + d, a + b, a + c
    prob = lambda x: comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)  # noqa: E731
    obs = prob(a)
    return min(1.0, sum(prob(x) for x in range(max(0, c1 - (n - r1)), min(r1, c1) + 1) if prob(x) <= obs + 1e-12))


def holm(ps: dict[str, float]) -> dict[str, float]:
    order, out, running = sorted(ps, key=ps.get), {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (len(order) - i) * ps[k]))
        out[k] = running
    return out


def analyze_cmd() -> None:
    scen = scenarios()
    runs = {"M1P1": [], "M1P5": []}
    for p in (CP / "logs/runs.jsonl", CP / "logs/adversarial/runs.jsonl", LIVE):
        seen = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["condition"] in runs and r["run_id"] not in seen:
                seen.add(r["run_id"])
                runs[r["condition"]].append(r)
    per = {c: defaultdict(Counter) for c in runs}
    totals = {c: Counter() for c in runs}
    lat = {c: [] for c in runs}
    for c, rs in runs.items():
        for r in rs:
            sc = scen[r["scenario_id"]]
            for t, spec in zip(r["turns"], sc["turns"]):
                lat[c].append((t.get("nlu_latency_ms") or 0) + (t.get("response_latency_ms") or 0))
                if not spec.get("scored"):
                    continue
                flags = set(ev.contamination_flags(t, spec, r))
                cell = per[c][r["scenario_id"]]
                for key, hit in (("n", True), ("agree", t["decision"] == t["expected_decision"]),
                                 ("risk_ok", cfg.risk_of(spec.get("truth_predicate", "none")) == cfg.risk_of(t["nlu_predicate"])),
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

    def paired(num: str, den: str) -> dict:
        shared = [s for s in sorted(per["M1P1"]) if per["M1P1"][s][den] and per["M1P5"][s][den]]
        diffs = [per["M1P5"][s][num] / per["M1P5"][s][den] - per["M1P1"][s][num] / per["M1P1"][s][den] for s in shared]
        return {"n_scenarios": len(shared), "discordant": sum(abs(d) > 1e-12 for d in diffs),
                "mean_diff": sum(diffs) / len(diffs), "p_two_sided": sign_flip(diffs), "ci95": bootstrap_ci(diffs)}

    primary = paired("agree", "n")
    secondary = {"promoted_without_policy": paired("promoted_without_policy", "inj"),
                 "asserted_as_fact_in_utterance": paired("asserted_as_fact_in_utterance", "inj")}
    a, b = totals["M1P1"], totals["M1P5"]
    secondary["TCAR_fisher"] = {"p_two_sided": fisher(a["accepted_ok"], a["should_accept"] - a["accepted_ok"],
                                                      b["accepted_ok"], b["should_accept"] - b["accepted_ok"])}
    adj = holm({k: v["p_two_sided"] for k, v in secondary.items()})
    for k in secondary:
        secondary[k]["holm"] = adj[k]
    summary = {c: {"runs": len(runs[c]), **dict(totals[c]),
                   "agree_rate": totals[c]["agree"] / totals[c]["n"], "risk_acc": totals[c]["risk_ok"] / totals[c]["n"],
                   "TCAR": totals[c]["accepted_ok"] / totals[c]["should_accept"],
                   "c1_rate": totals[c]["promoted_without_policy"] / totals[c]["inj"],
                   "c2_rate": totals[c]["asserted_as_fact_in_utterance"] / totals[c]["inj"],
                   "turn_latency_median_ms": sorted(lat[c])[len(lat[c]) // 2],
                   "turn_latency_p95_ms": sorted(lat[c])[int(.95 * (len(lat[c]) - 1))]} for c in runs}
    out = {"at_utc": now(), "summary": summary, "primary_agree_M1P1_vs_M1P5": primary, "secondary": secondary}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "nlu_improve_analysis.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["freeze", "dev", "select", "test", "offline", "replay", "live", "analyze"])
    cmd = ap.parse_args().command
    if cmd == "freeze":
        freeze_cmd()
    elif cmd == "dev":
        run_calls("dev", ("B", "V1", "V2"))
    elif cmd == "select":
        select_cmd()
    elif cmd == "test":
        if not SELECTION.exists():
            raise SystemExit("select first")
        run_calls("test", ("B", "V1", "V2"))
    elif cmd == "offline":
        res = {s: offline_metrics(s) for s in ("dev", "test")}
        (OUT / "nlu_offline.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(res, indent=1, ensure_ascii=False))
    elif cmd == "replay":
        replay_cmd()
    elif cmd == "live":
        live_cmd()
    elif cmd == "analyze":
        analyze_cmd()
