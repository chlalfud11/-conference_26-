"""ABCD v4 build (.omo/plans/abcd-v4-answer-key.md).

Usage:
  python3 abcd4_build.py build   -> scenarios_abcd4/, ledger_abcd4/, answer_key_abcd4/, results/abcd4/review.md
  python3 abcd4_build.py seal    -> results/abcd4/prereg_seal.json (prereg, scenario set, ledger, answer key hashes)

Inputs: scenarios_abcd/A###v.json (customer text, ABCD source) and results/abcd/ledgers_v3/A###v.json (rows).
Each source becomes three scenarios with the same customer text, told by three different customers:
  v  P has the claimed record on the stated date        -> accept_as_belief
  n  Q has no such record                               -> request_evidence
  d  R has the record, 14-28 days before the stated date -> dispute
Scenario files carry no answer; the answer key is a separate CSV that the runner never opens.
"""
import csv
import hashlib
import json
import random
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import abcd4_ledger as LG
from npc import config

ROOT = Path(__file__).parent
if LG.HELDOUT:
    SRC_SC = ROOT / "results" / "abcd5" / "heldout_src" / "scenarios"
    SRC_LG = ROOT / "results" / "abcd5" / "heldout_src" / "ledgers"
    SCEN = ROOT / "scenarios_abcd5h"
    KEY = ROOT / "answer_key_abcd5h" / "answer_key.csv"
    OUT = ROOT / "results" / "abcd5" / "heldout"
    PREREG = ROOT / "docs" / "ABCD_v5_reverify_사전등록.md"
else:
    SRC_SC = ROOT / "scenarios_abcd"
    SRC_LG = ROOT / "results" / "abcd" / "ledgers_v3"
    SCEN = ROOT / "scenarios_abcd4"
    KEY = ROOT / "answer_key_abcd4" / "answer_key.csv"
    OUT = ROOT / "results" / "abcd4"
    PREREG = ROOT / "docs" / "ABCD_v4_사전등록.md"
OLD_TODAY, TODAY = date(2024, 6, 15), date(2019, 12, 1)
DAYS_FIX = {"A040": 30}  # v3 read "today" in "got my bill today ... bought last month"; the purchase was ~30 days ago
REVIEW_SOURCES = ("H001", "H021", "H041", "H061", "H081") if LG.HELDOUT else ("A001", "A021", "A030", "A050", "A065")
FIRST = ("Avery", "Blair", "Cameron", "Dakota", "Emerson", "Finley", "Gray", "Hayden", "Indira", "Jules", "Kai",
         "Lennox", "Marlow", "Noor", "Oakley", "Parker", "Quinn", "Reese", "Sasha", "Tatum", "Umar", "Vida", "Wren", "Yuki")
LAST = ("Abernathy", "Bellweather", "Castellano", "Delacroix", "Easterbrook", "Fairbanks", "Galloway", "Hargrove",
        "Ingersoll", "Jaworski", "Kingsley", "Lindqvist", "Montague", "Northcott", "Okonkwo", "Pemberton")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def shift(text, delta):
    return DATE.sub(lambda m: str(date.fromisoformat(m.group()) + delta), text)


def new_id(*parts):
    return str(int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16) % 10**10).zfill(10)


def is_claim_row(predicate, r):
    """Rows removed for the n customer: the claimed record, plus the charge that proves an order or purchase."""
    return LG.matches(predicate, r) or (predicate in ("reserved_item", "owns_item") and r["event"] == "charge")


def build():
    rng = random.Random(11)
    sources = sorted(p.stem[:-1] for p in SRC_SC.glob("*v.json"))
    metas = {s: json.loads((SRC_LG / f"{s}v.json").read_text()) for s in sources}
    taken = {LG.split_who(m["customer"])[0] for m in metas.values()}
    pool = [f"{f} {l}" for f in FIRST for l in LAST]
    rng.shuffle(pool)
    pool = [n for n in pool if n not in taken]
    names, accounts = set(), set()

    def claim_identity(name, account):
        assert name not in names and account not in accounts, (name, account)
        names.add(name)
        accounts.add(account)
        return name, account

    def fresh():
        name = pool.pop(0)
        return claim_identity(name, name.replace(" ", "").lower())

    ledger, scenarios, key, edits = [], {}, [], []
    for s in sources:
        sc, meta = json.loads((SRC_SC / f"{s}v.json").read_text()), metas[s]
        pred, trust = meta["predicate"], sc["trust"]
        name, account = LG.split_who(meta["customer"])
        p_who = fresh() if name in names or account in accounts else claim_identity(name, account)
        level = re.search(r"member: (\w+)", meta["header"]).group(1)
        days = DAYS_FIX.get(s, meta["days_ago"])
        stated = str(TODAY - timedelta(days=days))
        texts = [shift(t, (TODAY - OLD_TODAY) + timedelta(days=meta["days_ago"] - days)) for t in meta["rows"]]
        base = []
        for t in texts:
            r = LG.parse(t)
            assert LG.render(r) == t, t
            base.append(r)
        rows_p = [r | {"customer": p_who[0], "account": p_who[1]} for r in base]
        q_who, r_who = fresh(), fresh()
        rows_q = [r | {"customer": q_who[0], "account": q_who[1], "order_id": r["order_id"] and new_id(s, "Q", r["order_id"])}
                  for r in base if not is_claim_row(pred, r)]
        back = timedelta(days=-rng.randint(14, 28))
        rows_r = [r | {"customer": r_who[0], "account": r_who[1], "date": shift(r["date"], back), "note": shift(r["note"], back),
                       "order_id": r["order_id"] and new_id(s, "R", r["order_id"]),
                       "items": ("NG" + hashlib.sha256(f"promo{s}R".encode()).hexdigest()[:6].upper()) if r["event"] == "promo" else r["items"]}
                  for r in base]
        expect = {"v": "verified", "n": "none", "d": "contradicting"}
        role_ids = {"v": lambda o: o, "n": lambda o: new_id(s, "Q", o), "d": lambda o: new_id(s, "R", o)}
        for ver, who, rows in (("v", p_who, rows_p), ("n", q_who, rows_q), ("d", r_who, rows_r)):
            got = LG.lookup(rows, who[1], pred, stated)
            assert got == expect[ver], (s, ver, got)
            ledger += rows
            sid = f"{s}{ver}"
            turns = []
            for t in sc["turns"]:
                text = re.sub(rf"\b{re.escape(name)}\b", who[0], t["player"], flags=re.I)
                for r in base:
                    if r["order_id"]:
                        text = text.replace(r["order_id"], role_ids[ver](r["order_id"]))
                if text != t["player"]:
                    edits.append({"scenario_id": sid, "original": t["player"], "edited": text})
                turns.append({"player": text})
            turns[-1]["date"] = stated
            scenarios[sid] = {"scenario_id": sid, "customer": f"{who[0]} ({who[1]})", "member_level": level, "trust": trust,
                              "source": {k: sc["source"][k] for k in ("dataset", "split", "convo_id", "flow", "subflow")},
                              "turns": turns}
            for i, t in enumerate(sc["turns"], 1):
                last = i == len(sc["turns"])
                tp, ev = (pred, expect[ver]) if last else (t["truth_predicate"], "none")
                key.append({"scenario_id": sid, "turn": i, "truth_predicate": tp, "evidence": ev,
                            "expected_decision": config.expected_decision(config.risk_of(tp), ev, trust)})

    SCEN.mkdir(exist_ok=True)
    for old in SCEN.glob("*.json"):
        old.unlink()
    for sid, sc in scenarios.items():
        (SCEN / f"{sid}.json").write_text(json.dumps(sc, indent=1, ensure_ascii=False) + "\n")
    ledger.sort(key=lambda r: (r["date"], r["account"], r["event"]))
    LG.write(ledger, str(TODAY))
    KEY.parent.mkdir(exist_ok=True)
    with KEY.open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=("scenario_id", "turn", "truth_predicate", "evidence", "expected_decision"),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(key)
    write_review(scenarios, ledger, key)
    (OUT / "text_edits.json").write_text(json.dumps(edits, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(scenarios)} scenarios, {len(ledger)} ledger rows, {len(key)} key rows, "
          f"{len(names)} customers, {len(edits)} utterances with the speaker's own name/order id substituted")


def write_review(scenarios, ledger, key):
    lines = ["# ABCD v4 검토표", "", f"오늘 날짜: {TODAY}. 원천 {len(REVIEW_SOURCES)}개 x 3판. "
             "모델은 '시나리오'와 '장부' 부분만 본다. '정답'은 채점표에만 있다.", ""]
    for s in [x for x in REVIEW_SOURCES if f"{x}v" in scenarios]:
        lines += [f"## {s}", ""]
        for ver in "vnd":
            sc = scenarios[f"{s}{ver}"]
            account = LG.split_who(sc["customer"])[1]
            own = [LG.render(r) for r in ledger if r["account"] == account] or ["(none)"]
            answer = [k for k in key if k["scenario_id"] == sc["scenario_id"]][-1]
            lines += [f"### {sc['scenario_id']}", "", "시나리오:", "```json", json.dumps(sc, indent=1, ensure_ascii=False), "```",
                      "장부(이 손님의 줄):", "```", *own, "```",
                      f"정답(채점표): evidence={answer['evidence']}, expected={answer['expected_decision']}", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "review.md").write_text("\n".join(lines) + "\n")


def set_hash(paths):
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def hashes():
    return {"prereg": set_hash([PREREG]), "scenarios": set_hash(SCEN.glob("*.json")),
            "ledger": set_hash(LG.DIR.glob("*")), "answer_key": set_hash([KEY])}


def seal():
    path = OUT / "prereg_seal.json"
    assert not path.exists(), "already sealed"
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sealed_at": datetime.now(timezone.utc).isoformat(), **hashes()}, indent=1) + "\n")
    print("sealed", {k: v[:12] for k, v in hashes().items()})


if __name__ == "__main__":
    {"build": build, "seal": seal}[sys.argv[1]]()
