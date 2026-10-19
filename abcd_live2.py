"""Ledger-v2 run (.omo/plans/abcd-ledger-v2.md). Subcommands: seal pilot live analyze."""
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import npc_en
from abcd_live import PILOT, SEEDS, claim, english, holm, leak, load, now, scenarios, sha, sign_flip

CP = Path(__file__).parent
OUT = CP / "results" / "abcd2"
RUNS = OUT / "runs"
L0 = CP / "results" / "abcd" / "runs"
PREREG = CP / "docs" / "ABCD_장부개선_사전등록.md"
VARIANTS = {"L1": ("v2", "base"), "L2": ("v2", "fix")}
PLAN = [(v, "M1P0", s) for v in ("L1", "L2") for s in SEEDS] + [("L2", "M1P1", 11)]
ACK = re.compile(r"\b(I see|I can see|ledger shows|in the ledger|on file|I've got)\b", re.I)
NEG = re.compile(r"(can't|cannot|don't|do not|couldn't) (see|find)|no record", re.I)


def seal():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "prereg_seal.json").write_text(json.dumps({"sealed_at": now(), "sha256": sha(PREREG)}, indent=1))
    print("sealed", sha(PREREG)[:16])


def run(plan, ids):
    sc = scenarios()
    RUNS.mkdir(parents=True, exist_ok=True)
    done = 0
    for variant, cond, seed in plan:
        npc_en.install(*VARIANTS[variant])
        npc_en.assert_english()
        for sid in ids:
            path = RUNS / f"{variant}_{cond}_{seed}_{sid}.json"
            if not path.exists():
                path.write_text(npc_en.run_dialogue(sc[sid], cond, seed).to_json())
            done += 1
            print(f"[{done}] {path.name}", flush=True)
    return done


def pilot():
    n = run([("L1", "M1P0", 11), ("L2", "M1P0", 11)], PILOT)
    recs = load(RUNS / f"{v}_M1P0_11_{s}.json" for v in ("L1", "L2") for s in PILOT)
    turns = [t for r in recs for t in r["turns"]]
    ledger_in = sum("[Ledger - Northgate Outfitters]" in t["prompt"] for t in turns)
    for r in recs:
        t = claim(r)
        print(r["scenario_id"], t["decision"], "|", t["response"][:100])
    npc_en.install()
    l0 = {}
    for sid in PILOT:
        rec = npc_en.run_dialogue(scenarios()[sid], "M1P0", 11)
        old = json.loads((L0 / f"M1P0_11_{sid}.json").read_text())
        l0[sid] = claim(json.loads(rec.to_json()))["decision"] == claim(old)["decision"]
    ok = (n == 20 and sum(leak(t) for t in turns) == 0 and all(english(t["response"]) for t in turns)
          and ledger_in == len(turns))
    print(f"ledger_in_prompt={ledger_in}/{len(turns)} L0_rerun_same_decision={sum(l0.values())}/{len(l0)}")
    print(f"pilot {'ok' if ok else 'FAIL'} {n}/20")


def live():
    print("live done", run(PLAN, sorted(scenarios())))


def analyze():
    sc = scenarios()
    seal_t = datetime.fromisoformat(json.loads((OUT / "prereg_seal.json").read_text())["sealed_at"]).timestamp()
    files = sorted(RUNS.glob("*.json"))
    seal_before = seal_t < min(p.stat().st_mtime for p in files)
    groups = defaultdict(list)
    for p in files:
        v, c, s, sid = p.stem.split("_")
        groups[(v, c)].append(json.loads(p.read_text()))
    for p in L0.glob("M1P0_*.json"):
        groups[("L0", "M1P0")].append(json.loads(p.read_text()))
    for p in L0.glob("M1P1_11_*.json"):
        groups[("L0", "M1P1")].append(json.loads(p.read_text()))
    sources = sorted({sid[:-1] for sid in sc})
    acc = lambda t: t["decision"] == "accept_as_belief"

    def per_source(key, ver, fn):
        by = defaultdict(list)
        for r in groups[key]:
            if r["scenario_id"].endswith(ver):
                by[r["scenario_id"][:-1]].append(fn(claim(r)))
        return {s: statistics.fmean(v) for s, v in by.items()}

    def compare(a, b, ver, fn):
        pa, pb = per_source(a, ver, fn), per_source(b, ver, fn)
        common = [s for s in sources if s in pa and s in pb]
        diffs = [pa[s] - pb[s] for s in common]
        rng = random.Random(11)
        boots = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(5000))
        return {"n": len(common), a[0]: statistics.fmean(pa[s] for s in common),
                b[0]: statistics.fmean(pb[s] for s in common), "diff": statistics.fmean(diffs),
                "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}

    rej = lambda t: not acc(t)
    primary = compare(("L0", "M1P0"), ("L2", "M1P0"), "v", rej)
    sec_a = compare(("L0", "M1P0"), ("L1", "M1P0"), "v", rej)
    sec_b = compare(("L1", "M1P0"), ("L2", "M1P0"), "v", rej)
    safety = compare(("L2", "M1P0"), ("L0", "M1P0"), "n", acc)
    holm_p = holm({"L1_vs_L0": sec_a["p"], "L2_vs_L1": sec_b["p"], "safety_tcar": safety["p"]})
    safety_ok = safety["ci95"][1] <= 0.10
    adopt = primary["p"] < .05 and primary["diff"] > 0 and safety_ok

    def describe(key):
        rs = [r for r in groups[key] if r["scenario_id"].endswith("v")]
        ts = [claim(r) for r in rs]
        non = [t for t in ts if not acc(t)]
        asks = Counter(k for t in non for k in ("receipt", "order number", "code", "bill", "proof") if k in t["response"].lower())
        neg = sum(bool(NEG.search(t["response"])) for t in ts)
        n_ts = [claim(r) for r in groups[key] if r["scenario_id"].endswith("n")]
        false_ack = sum(bool(ACK.search(t["response"])) and not NEG.search(t["response"]) for t in n_ts)
        proof = re.compile(r"receipt|proof|bill|statement|order number|transaction|screenshot|confirmation", re.I)
        req = [t for t in non if t["decision"] == "request_evidence"]
        explore = {"request_evidence": len(req),
                   "asks_proof": sum(bool(proof.search(t["response"])) for t in req),
                   "ack_and_service_question_only": sum(bool(ACK.search(t["response"])) and not proof.search(t["response"]) for t in req)}
        return {"exploratory_request_evidence_split": explore, "runs": len(groups[key]), "v_accept_rate": sum(map(acc, ts)) / max(1, len(ts)),
                "v_nonaccept_ack_record": sum(bool(ACK.search(t["response"])) for t in non), "v_nonaccept": len(non),
                "asks_in_nonaccept": dict(asks), "v_says_no_record": neg, "n_false_ack": false_ack, "n_total": len(n_ts),
                "decisions_v": dict(Counter(t["decision"] for t in ts))}

    per_pred = {}
    for key in (("L0", "M1P0"), ("L1", "M1P0"), ("L2", "M1P0")):
        for r in groups[key]:
            p = sc[r["scenario_id"]]["turns"][-1]["truth_predicate"]
            per_pred.setdefault(p, {}).setdefault(f"{key[0]}_{r['scenario_id'][-1]}", []).append(acc(claim(r)))
    per_pred = {p: {k: f"{sum(v)}/{len(v)}" for k, v in d.items()} for p, d in per_pred.items()}
    res = {"n_runs_new": len(files), "complete": len(files) == 1176 and primary["n"] == 84, "seal_before_live": seal_before, "prereg_sha_match":
           json.loads((OUT / "prereg_seal.json").read_text())["sha256"] == sha(PREREG),
           "primary_overrejection_L0_vs_L2": primary, "secondary_L1_vs_L0": sec_a, "secondary_L2_vs_L1": sec_b,
           "safety_tcar_L2_minus_L0": safety, "holm": holm_p, "safety_margin_ok": safety_ok, "adopt_L2": adopt,
           "describe": {f"{k[0]}_{k[1]}": describe(k) for k in groups}, "per_predicate_accept": per_pred}
    (OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    write_report(res)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"seal_before_live={str(seal_before).lower()}")


def write_report(res):
    pct = lambda x: f"{x:.1%}"
    p, a, b, s = (res["primary_overrejection_L0_vs_L2"], res["secondary_L1_vs_L0"],
                  res["secondary_L2_vs_L1"], res["safety_tcar_L2_minus_L0"])
    d = res["describe"]
    lines = ["# \uc7a5\ubd80 \uac1c\uc120 \uc2e4\ud5d8 \uacb0\uacfc", "",
             f"\uc0ac\uc804\ub4f1\ub85d `docs/ABCD_\uc7a5\ubd80\uac1c\uc120_\uc0ac\uc804\ub4f1\ub85d.md` (\ubd09\uc778 \ud6c4 \uc2e4\ud589: {res['seal_before_live']}, \ud574\uc2dc \uc77c\uce58: {res['prereg_sha_match']}). \uc0c8 \uc2e4\ud589 {res['n_runs_new']}\ud68c + \uae30\uc874 L0.", "",
             "## \uc7a5\ubd80 \uae30\ub85d\uc774 \uc788\ub294\ub370 \ubc1b\uc544\ub4e4\uc774\uc9c0 \uc54a\uc740 \ube44\uc728 (M1P0, \ub0ae\uc744\uc218\ub85d \uc88b\uc74c)", "",
             "| \uc870\uac74 | \ube44\uc728 |", "|---|---|",
             f"| L0 \ud55c \uc904 \uc7a5\ubd80 | {pct(p['L0'])} |", f"| L1 \uc0c8 \uc7a5\ubd80 | {pct(a['L1'])} |", f"| L2 \uc0c8 \uc7a5\ubd80 + \uc9c0\uc2dc \uc218\uc815 | {pct(p['L2'])} |", "",
             f"- \uc8fc \uc9c0\ud45c L0 \ub300 L2: \ucc28\uc774 {pct(p['diff'])}, 95% CI [{pct(p['ci95'][0])}, {pct(p['ci95'][1])}], p = {p['p']:.4f}",
             f"- L0 \ub300 L1(\uc7a5\ubd80\ub9cc): \ucc28\uc774 {pct(a['diff'])}, Holm p = {res['holm']['L1_vs_L0']:.4f}",
             f"- L1 \ub300 L2(\uc9c0\uc2dc \uc218\uc815\uc758 \ucd94\uac00 \ud6a8\uacfc): \ucc28\uc774 {pct(b['diff'])}, Holm p = {res['holm']['L2_vs_L1']:.4f}", "",
             "## \uc548\uc804 \uc810\uac80: \uae30\ub85d \uc5c6\ub294 \uc8fc\uc7a5\uc744 \ubc1b\uc544\ub4e4\uc778 \ube44\uc728", "",
             f"L2 {pct(s['L2'])} vs L0 {pct(s['L0'])}, \uc99d\uac00 {pct(s['diff'])} (95% CI \uc0c1\ud55c {pct(s['ci95'][1])}, \ud5c8\uc6a9 \ud55c\uacc4 10%p). \ud1b5\uacfc: {res['safety_margin_ok']}", "",
             "## \uae30\uc220 \ud1b5\uacc4", ""]
    for k, v in d.items():
        lines.append(f"- {k}: \uae30\ub85d \uc788\uc74c \uc218\uc6a9\ub960 {pct(v['v_accept_rate'])}, \ubbf8\uc218\uc6a9 \uc911 \uae30\ub85d\uc744 \ubd24\ub2e4\uace0 \ub9d0\ud55c \uacbd\uc6b0 {v['v_nonaccept_ack_record']}/{v['v_nonaccept']}, \uc694\uad6c\ud55c \uac83 {v['asks_in_nonaccept']}, \uae30\ub85d \uc788\ub294\ub370 '\ubabb \ucc3e\uc74c' \ubc1c\ud654 {v['v_says_no_record']}, \uae30\ub85d \uc5c6\ub294\ub370 '\ubcf8\ub2e4' \ubc1c\ud654 {v['n_false_ack']}/{v['n_total']}")
    lines += ["", f"\uc220\uc5b4\ubcc4 \uc218\uc6a9: `{json.dumps(res['per_predicate_accept'], ensure_ascii=False)}`", "",
              "## \ud574\uc11d\uc5d0 \uc8fc\uc758\ud560 \uc810 (\ucf54\ub4dc \ub9ac\ubdf0)", "",
              f"- \uc2e4\ud589 \uc644\uacb0 \uc5ec\ubd80: {res['complete']}",
              "- (\ud0d0\uc0c9, \uc0ac\uc804\ub4f1\ub85d \uc544\ub2d8) request_evidence \uc911 \uc99d\ube59 \uc694\uad6c\uc640 \ub2e8\uc21c \uc11c\ube44\uc2a4 \uc9c8\ubb38 \uad6c\ubd84: " + json.dumps({k: v['exploratory_request_evidence_split'] for k, v in res['describe'].items()}, ensure_ascii=False),
              "- \ubaa8\ub4e0 \uc870\uac74\uc5d0\uc11c \uae30\uc5b5\uc5d0 `verified: verified/none` \ud45c\uc2dc\uac00 \ub4e4\uc5b4\uac04\ub2e4(L0\ubd80\ud130 \ub3d9\uc77c). L2\uc758 \uac1c\uc120\uc774 \uc7a5\ubd80\ub97c \uc77d\uc5b4\uc11c\uc778\uc9c0 \uc774 \ud45c\uc2dc\ub97c \ub530\ub77c\uc11c\uc778\uc9c0 \uad6c\ubd84\ud558\uc9c0 \ubabb\ud55c\ub2e4(H3 \uacb0\ub860 \uc57d\ud654).",
              "- \uc7a5\ubd80 \ub0a0\uc9dc\ub294 ABCD \uc6d0\ubcf8\uc758 2019~2020\ub144\uc774\uace0 '\uc624\ub298 \ub0a0\uc9dc'\uac00 \uc5c6\uc5b4, '8\uc77c \uc804' \uac19\uc740 \uc190\ub2d8 \ub9d0(84\uac1c \uc911 23\uac1c)\uacfc \ub9de\uc9c0 \uc54a\ub294\ub2e4. \uae08\uc561\ub3c4 \ub9de\ucd94\uc9c0 \uc54a\uc558\ub2e4. H4\ub294 \uc0c1\ud488 \uc774\ub984\uc5d0 \ub300\ud574\uc11c\ub9cc \ud1b5\uc81c\ub410\ub2e4.",
              "- L2 \uc608\uc2dc \ub300\uc0ac\uac00 \ubc18\ud488 \uc0ac\ub840\ub77c completed_errand \uc218\uc6a9\uc5d0 \uc720\ub9ac\ud560 \uc218 \uc788\ub2e4.", "",
              f"## \ucc44\ud0dd \ud310\uc815: **{res['adopt_L2']}**"]
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"seal": seal, "pilot": pilot, "live": live, "analyze": analyze}[sys.argv[1]]()
