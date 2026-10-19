"""Ledger-v3 / vector-DB run (.omo/plans/abcd-ledger-v3-vdb.md). Subcommands: seal pilot live analyze."""
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import abcd_live2 as B
from abcd_live import PILOT, SEEDS, claim, english, holm, leak, load, scenarios, sha, sign_flip

CP = Path(__file__).parent
B.OUT = CP / "results" / "abcd3"
B.RUNS = B.OUT / "runs"
B.PREREG = CP / "docs" / "ABCD_장부v3_사전등록.md"
B.VARIANTS = {"L3": ("v3", "fix"), "L4": ("v4", "fix")}
PLAN = [(v, "M1P0", s) for v in ("L3", "L4") for s in SEEDS]
L2 = CP / "results" / "abcd2" / "runs"
LEDGERS = CP / "results" / "abcd" / "ledgers_v3"
DATE = re.compile(r"\b(days?|weeks?|month|ago|dated|issued on)\b|\d{4}-\d{2}-\d{2}", re.I)


def pilot():
    n = B.run([("L3", "M1P0", 11), ("L4", "M1P0", 11)], PILOT)
    recs = load(B.RUNS / f"{v}_M1P0_11_{s}.json" for v in ("L3", "L4") for s in PILOT)
    turns = [t for r in recs for t in r["turns"]]
    today = sum("Today: 2024-06-15" in t["prompt"] for t in turns)
    l4 = [t for s in PILOT for t in json.loads((B.RUNS / f"L4_M1P0_11_{s}.json").read_text())["turns"]]
    searched = sum("Ledger search results" in t["prompt"] for t in l4)
    for r in recs:
        t = claim(r)
        print(r["scenario_id"], t["decision"], "|", t["response"][:100])
    ok = (n == 20 and sum(leak(t) for t in turns) == 0 and all(english(t["response"]) for t in turns)
          and today == len(turns) and searched == len(l4))
    print(f"today_in_prompt={today}/{len(turns)} search_blocks={searched}/{len(l4)}")
    print(f"pilot {'ok' if ok else 'FAIL'} {n}/20")


def live():
    print("live done", B.run(PLAN, sorted(scenarios())))


def hit(record):
    meta = json.loads((LEDGERS / f"{record['scenario_id']}.json").read_text())
    prompt = claim(record)["prompt"]
    key = {"reserved_item": "| order #", "owns_item": "| order #", "paid_deposit": "[duplicate",
           "completed_errand": "return received", "promised_discount": "promo code"}[meta["predicate"]]
    claim_row = next((r for r in meta["rows"] if key in r), None) if meta["verified"] else None
    own = all(r in prompt for r in meta["rows"])
    other = len(re.findall(r"\| ([A-Z][a-z]+ [A-Z][a-z]+ \([^)]+\)) \|", prompt))
    foreign = sum(1 for m in re.findall(r"\| ([A-Z][a-z]+ [A-Z][a-z]+ \([^)]+\)) \|", prompt) if m != meta["customer"])
    return {"claim_row_retrieved": bool(claim_row) and claim_row in prompt, "all_own_rows": own,
            "foreign_rows": foreign, "rows_shown": other}


def analyze():
    sc = scenarios()
    seal_t = datetime.fromisoformat(json.loads((B.OUT / "prereg_seal.json").read_text())["sealed_at"]).timestamp()
    files = sorted(B.RUNS.glob("*.json"))
    seal_before = seal_t < min(p.stat().st_mtime for p in files)
    groups = defaultdict(list)
    for p in files:
        groups[p.stem.split("_")[0]].append(json.loads(p.read_text()))
    groups["L2"] = [json.loads(p.read_text()) for p in L2.glob("L2_M1P0_*.json")]
    sources = sorted({sid[:-1] for sid in sc})
    acc = lambda t: t["decision"] == "accept_as_belief"
    rej = lambda t: not acc(t)

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
        return {"n": len(common), a: statistics.fmean(pa[s] for s in common), b: statistics.fmean(pb[s] for s in common),
                "diff": statistics.fmean(diffs), "ci95": [boots[124], boots[4874]], "p": sign_flip(diffs)}

    primary = compare("L2", "L3", "v", rej)
    sec_a = compare("L3", "L4", "v", rej)
    safe3 = compare("L3", "L2", "n", acc)
    safe4 = compare("L4", "L2", "n", acc)
    holm_p = holm({"L3_vs_L4": sec_a["p"], "safety_L3": safe3["p"], "safety_L4": safe4["p"]})
    hits = {ver: [hit(r) for r in groups["L4"] if r["scenario_id"].endswith(ver)] for ver in "vn"}

    def describe(key):
        v = [claim(r) for r in groups[key] if r["scenario_id"].endswith("v")]
        disputes = [t for t in v if t["decision"] == "dispute"]
        return {"decisions_v": dict(Counter(t["decision"] for t in v)), "v_accept_rate": sum(map(acc, v)) / len(v),
                "disputes_mentioning_dates": sum(bool(DATE.search(t["response"])) for t in disputes),
                "n_accept": sum(acc(claim(r)) for r in groups[key] if r["scenario_id"].endswith("n"))}

    def compare_excl(a, b, ver, fn, excl):
        pa, pb = per_source(a, ver, fn), per_source(b, ver, fn)
        common = [s for s in sources if s in pa and s in pb and s not in excl]
        diffs = [pa[s] - pb[s] for s in common]
        return {"n": len(common), a: statistics.fmean(pa[s] for s in common), b: statistics.fmean(pb[s] for s in common),
                "diff": statistics.fmean(diffs), "p": sign_flip(diffs)}

    date_bad, l4_turn_leak = {"A040"}, {"A002", "A003", "A038", "A041", "A044", "A068"}
    sensitivity = {"excluded_date_misparse": sorted(date_bad), "excluded_l4_earlier_turn_query": sorted(l4_turn_leak),
                   "primary_L2_vs_L3": compare_excl("L2", "L3", "v", rej, date_bad),
                   "L3_vs_L4": compare_excl("L3", "L4", "v", rej, date_bad | l4_turn_leak),
                   "safety_L4_minus_L2": compare_excl("L4", "L2", "n", acc, date_bad | l4_turn_leak)}
    rel = {s for s in sources if json.loads((LEDGERS / f"{s}v.json").read_text())["days_ago"] != 3}
    by_date = {k: {"rel_date_sources_accept": f"{sum(acc(claim(r)) for r in groups[k] if r['scenario_id'][:-1] in rel and r['scenario_id'].endswith('v'))}"
                   f"/{sum(1 for r in groups[k] if r['scenario_id'][:-1] in rel and r['scenario_id'].endswith('v'))}"}
               for k in ("L2", "L3", "L4")}
    res = {"n_runs_new": len(files), "complete": len(files) == 1008 and primary["n"] == 84,
           "seal_before_live": seal_before,
           "prereg_sha_match": json.loads((B.OUT / "prereg_seal.json").read_text())["sha256"] == sha(B.PREREG),
           "primary_overrejection_L2_vs_L3": primary, "secondary_L3_vs_L4": sec_a,
           "safety_L3_minus_L2": safe3, "safety_L4_minus_L2": safe4, "holm": holm_p,
           "safety_ok": safe3["ci95"][1] <= 0.10 and safe4["ci95"][1] <= 0.10,
           "retrieval": {ver: {"claim_row_hit_rate": sum(h["claim_row_retrieved"] for h in hs) / max(1, len(hs)),
                               "all_own_rows_rate": sum(h["all_own_rows"] for h in hs) / max(1, len(hs)),
                               "mean_foreign_rows": statistics.fmean(h["foreign_rows"] for h in hs) if hs else None}
                         for ver, hs in hits.items()},
           "describe": {k: describe(k) for k in ("L2", "L3", "L4")}, "relative_date_sources": len(rel), "by_date": by_date,
           "sensitivity_post_hoc": sensitivity}
    (B.OUT / "analysis.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    report(res)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"seal_before_live={str(seal_before).lower()}")


def report(res):
    pct = lambda x: f"{x:.1%}"
    p, a = res["primary_overrejection_L2_vs_L3"], res["secondary_L3_vs_L4"]
    r = res["retrieval"]
    lines = ["# \uc7a5\ubd80 v3(\uc624\ub298 \ub0a0\uc9dc) + \ubca1\ud130DB \uc2e4\ud5d8 \uacb0\uacfc", "",
             f"\uc0ac\uc804\ub4f1\ub85d `docs/ABCD_\uc7a5\ubd80v3_\uc0ac\uc804\ub4f1\ub85d.md` (\ubd09\uc778 \ud6c4 \uc2e4\ud589: {res['seal_before_live']}, \ud574\uc2dc \uc77c\uce58: {res['prereg_sha_match']}, \uc644\uacb0: {res['complete']}). \uc0c8 \uc2e4\ud589 {res['n_runs_new']}\ud68c + L2(\uc774\uc804 \uc2e4\ud5d8).", "",
             "## \uae30\ub85d\uc774 \uc788\ub294\ub370 \ubc1b\uc544\ub4e4\uc774\uc9c0 \uc54a\uc740 \ube44\uc728 (M1P0, \ub0ae\uc744\uc218\ub85d \uc88b\uc74c)", "",
             "| \uc870\uac74 | \ube44\uc728 |", "|---|---|",
             f"| L2 \uc7a5\ubd80 v2 + \uc9c0\uc2dc \uc218\uc815 | {pct(p['L2'])} |",
             f"| L3 \uc624\ub298 \ub0a0\uc9dc + \ub0a0\uc9dc \ub9de\ucda4 \uc7a5\ubd80(\uc804\uccb4 \uc81c\uacf5) | {pct(p['L3'])} |",
             f"| L4 \uac19\uc740 \uc7a5\ubd80\ub97c \ubca1\ud130DB \uac80\uc0c9 \uc0c1\uc704 5\uc904\ub9cc \uc81c\uacf5 | {pct(a['L4'])} |", "",
             f"- \uc8fc \uc9c0\ud45c L2 \ub300 L3: \ucc28\uc774 {pct(p['diff'])}, 95% CI [{pct(p['ci95'][0])}, {pct(p['ci95'][1])}], p = {p['p']:.4f}",
             f"- L3 \ub300 L4: \ucc28\uc774 {pct(a['diff'])}, Holm p = {res['holm']['L3_vs_L4']:.4f}", "",
             "## \uc548\uc804 \uc810\uac80 (\uae30\ub85d \uc5c6\ub294 \uc8fc\uc7a5 \uc218\uc6a9 \uc99d\uac00)", "",
             f"- L3 \u2212 L2: {pct(res['safety_L3_minus_L2']['diff'])} (CI \uc0c1\ud55c {pct(res['safety_L3_minus_L2']['ci95'][1])}), L4 \u2212 L2: {pct(res['safety_L4_minus_L2']['diff'])} (CI \uc0c1\ud55c {pct(res['safety_L4_minus_L2']['ci95'][1])}). \ud1b5\uacfc: {res['safety_ok']}", "",
             "## \ubca1\ud130DB \uac80\uc0c9 \ud488\uc9c8 (L4)", "",
             f"- \uae30\ub85d \uc788\uc74c(v): \uc8fc\uc7a5\uc744 \ub4b7\ubc1b\uce68\ud558\ub294 \uc904\uc774 \uc0c1\uc704 5\uac1c\uc5d0 \ub4e0 \ube44\uc728 {pct(r['v']['claim_row_hit_rate'])}, \uc190\ub2d8 \ubcf8\uc778 \uc904\uc774 \ubaa8\ub450 \ub4e0 \ube44\uc728 {pct(r['v']['all_own_rows_rate'])}, \ub2e4\ub978 \uc190\ub2d8 \uc904 \ud3c9\uade0 {r['v']['mean_foreign_rows']:.2f}\uac1c",
             f"- \uae30\ub85d \uc5c6\uc74c(n): \ub2e4\ub978 \uc190\ub2d8 \uc904 \ud3c9\uade0 {r['n']['mean_foreign_rows']:.2f}\uac1c", "",
             "## \uae30\uc220 \ud1b5\uacc4", ""]
    lines += [f"- {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in res["describe"].items()]
    lines += [f"- \uc0c1\ub300 \ub0a0\uc9dc\uac00 \uc788\ub294 \uc6d0\ucc9c({res['relative_date_sources']}\uac1c)\uc758 \uc218\uc6a9: {json.dumps(res['by_date'], ensure_ascii=False)}", "",
              "## \uc8fc\uc758", "",
              "- \uae30\uc5b5\uc758 `verified:` \ud45c\uc2dc\ub294 \uc5ec\uc804\ud788 \ubaa8\ub4e0 \uc870\uac74\uc5d0 \uc788\ub2e4(\ube44\uad50 \uac00\ub2a5\uc131 \uc720\uc9c0). \uac1c\uc120\uc774 \uc7a5\ubd80 \ub54c\ubb38\uc778\uc9c0 \uc774 \ud45c\uc2dc \ub54c\ubb38\uc778\uc9c0 \uad6c\ubd84\ud558\uc9c0 \ubabb\ud55c\ub2e4.",
              "- L2\uc640 L3\ub294 \ub0a0\uc9dc\ub9cc\uc774 \uc544\ub2c8\ub77c \uc7a5\ubd80 \ud615\uc2dd(\ud589 \ud615\uc2dd, \uc190\ub2d8 \uc774\ub984 \ud3ec\ud568)\ub3c4 \ub2e4\ub974\ub2e4. L2 \ub300 L3\uc758 \ucc28\uc774\ub97c \ub0a0\uc9dc\ub9cc\uc758 \ud6a8\uacfc\ub85c \ubcf4\uba74 \uc548 \ub41c\ub2e4.",
              "- \ub0a0\uc9dc \ud45c\ud604\uc774 \uc5c6\ub294 \uc6d0\ucc9c\uc740 '3\uc77c \uc804'\uc744 \uae30\ubcf8\uac12\uc73c\ub85c \uc37c\ub2e4.",
              "", "## \uac80\ud1a0\uc5d0\uc11c \ubc1c\uacac\ub41c \ubb38\uc81c\uc640 \ubbfc\uac10\ub3c4 \ubd84\uc11d (\uc0ac\ud6c4)", "",
              "- \ub0a0\uc9dc \ud30c\uc2f1 \uc624\ub958 1\uac74: A040\uc740 '\uc624\ub298 \uccad\uad6c\uc11c\ub97c \ubc1b\uc558\ub294\ub370 \uc9c0\ub09c\ub2ec\uc5d0 \uc0b0 \ucf54\ud2b8\uac00 \ub450 \ubc88 \uccad\uad6c'\ub77c\ub294 \ub9d0\uc5d0\uc11c 'today'\ub97c \uc7a1\uc544 \uad6c\ub9e4\uc77c\uc744 \uc624\ub298\ub85c \uc801\uc5c8\ub2e4(\uc62c\ubc14\ub978 \uac12\uc740 \uc57d 30\uc77c \uc804).",
              "- L4 \uac80\uc0c9 \uc9c8\uc758 \ubb38\uc81c: \uc778\uc0ac \ud134\uc774 \uc788\ub294 6\uac1c \uc6d0\ucc9c(36\ud68c \uc2e4\ud589)\uc5d0\uc11c \uccab \ud134\uc758 \uac80\uc0c9\uc5d0\ub3c4 \ub9c8\uc9c0\ub9c9 \ud134 \ubb38\uc7a5\uc744 \uc37c\ub2e4. \uc8fc\uc7a5 \ud134 \uc790\uccb4\uc758 \uac80\uc0c9\uc740 \uc62c\ubc14\ub974\uc9c0\ub9cc, \uc9c1\uc804 \ud134 \ub300\uc0ac\uac00 \ubbf8\ub798 \uc815\ubcf4\uc5d0 \uc601\ud5a5\ubc1b\uc558\uc744 \uc218 \uc788\ub2e4.",
              "- \uac80\uc0c9 \uc801\uc911\ub960 \uc9c0\ud45c\ub97c \uace0\ucce4\ub2e4: \uc608\uc804\uc5d0\ub294 \ub9c8\uc9c0\ub9c9 \uc904\uc744 \uae30\uc900\uc73c\ub85c \ud588\uc73c\ub098, \uc8fc\uc7a5 \uc720\ud615\ubcc4\ub85c \ub4b7\ubc1b\uce68\ud558\ub294 \uc904(\uc8fc\ubb38/\uc911\ubcf5 \uccad\uad6c/\ubc18\ud488/\ud504\ub85c\ubaa8)\uc744 \uae30\uc900\uc73c\ub85c \ubc14\uafe8\ub2e4(\uc704 \ud45c\uc758 \uc801\uc911\ub960\uc740 \uace0\uce5c \uac12).",
              "- \uc81c\uc678 \ud6c4 \ubbfc\uac10\ub3c4: " + json.dumps(res["sensitivity_post_hoc"], ensure_ascii=False)]
    (B.OUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    {"seal": B.seal, "pilot": pilot, "live": live, "analyze": analyze}[sys.argv[1]]()
