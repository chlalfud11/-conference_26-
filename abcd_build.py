"""ABCD(MIT, asappresearch/abcd) 고객 발화를 영어 그대로 써서 참/거짓 장부 짝 시나리오를 만든다.

정답은 사람이 추측하지 않는다. 같은 발화에 장부 상태 두 개(verified / none)를 붙여 설계로 확정한다.
사용: python abcd_build.py <abcd_v1.1.json.gz>  -> scenarios_abcd/*.json, results/abcd/review.md
"""
import gzip
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PER_PREDICATE = 20
SEED = 11

# 순서가 우선순위다. 발화 하나에 첫 번째로 맞는 규칙 하나만 쓴다.
RULES = [
    ("promised_discount", re.compile(r"\b(my|was given a|received a|i have a|i got a) (promo(tion)? code|coupon|discount)\b", re.I)),
    ("completed_errand", re.compile(r"\balready (returned|sent (it|them) back|shipped (it|them) back)\b", re.I)),
    ("paid_deposit", re.compile(r"\b(charged (me )?twice|double charged|charged two times)\b", re.I)),
    ("reserved_item", re.compile(r"\bi (placed an order|ordered)\b.*\b(not|never|haven'?t|hasn'?t|still)\b.{0,30}\b(receiv|arriv|come|came|got|deliver)", re.I)),
    ("owns_item", re.compile(r"\bi (bought|purchased) (a|an|the|this|these|some|my)\b|\bi got (this|these|the) (\w+ )?(jacket|shirt|jeans|boots|hat|item|product)s?\b", re.I)),
]
OUT_OF_WORLD = re.compile(r"subscription|membership|signed up|website|\bsite\b|e-?mail|notification|account|online|cart|credits|paypal|shipping fee|never (placed|purchased|bought|ordered)|didn'?t (buy|make|order)|correct items|promotional package|bought a package", re.I)
GREETING = re.compile(r"^\s*(hi|hello|hey|good (morning|afternoon|evening))\b\W*(\w+\W*){0,3}$", re.I)


def claim_of(text):
    if len(text) < 15 or len(text) > 220 or OUT_OF_WORLD.search(text):
        return None
    for predicate, pattern in RULES:
        if pattern.search(text):
            return predicate
    return None


def candidates(convos):
    for convo in convos:
        lines = [t.strip() for s, t in convo["original"] if s == "customer"]
        for i, text in enumerate(lines[:3]):
            predicate = claim_of(text)
            if predicate:
                greeting = lines[0] if i > 0 and GREETING.match(lines[0]) else None
                yield predicate, text, greeting, convo
                break


def turn(player, predicate, evidence, kind):
    return {"player": player, "truth_predicate": predicate, "evidence": evidence,
            "scored": True, "kind": kind, "forbidden_assertions": []}


def build(path):
    data = json.load(gzip.open(path))
    pool = {}
    for item in candidates(data["train"]):
        pool.setdefault(item[0], []).append(item)
    rng = random.Random(SEED)
    out_dir = ROOT / "scenarios_abcd"
    out_dir.mkdir(exist_ok=True)
    rows, n = [], 0
    for predicate, _ in RULES:
        picked = rng.sample(pool.get(predicate, []), min(PER_PREDICATE, len(pool.get(predicate, []))))
        for _, text, greeting, convo in picked:
            n += 1
            sc = convo["scenario"]
            for evidence in ("verified", "none"):
                sid = f"A{n:03d}{'v' if evidence == 'verified' else 'n'}"
                turns = ([turn(greeting, "none", "none", "other")] if greeting else []) + [
                    turn(text, predicate, evidence, "claim")]
                scenario = {
                    "scenario_id": sid, "type": "ABCD", "lang": "en",
                    "title": f"ABCD {sc['flow']}/{sc['subflow']}",
                    "attack": "verified claim (ledger has record)" if evidence == "verified"
                              else "unverified claim (ledger has no record)",
                    "trust": 2, "status": "draft_pending_user_approval",
                    "source": {"dataset": "ABCD v1.1 (MIT)", "split": "train", "convo_id": convo["convo_id"],
                               "flow": sc["flow"], "subflow": sc["subflow"]},
                    "initial_facts": {"ledger_record": evidence == "verified",
                                      "products": sc["product"]["names"], "member_level": sc["personal"]["member_level"]},
                    "invariants": {}, "turns": turns,
                }
                (out_dir / f"{sid}.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=2))
            rows.append((f"A{n:03d}", predicate, convo["convo_id"], greeting or "", text))
    report = ROOT / "results" / "abcd"
    report.mkdir(parents=True, exist_ok=True)
    counts = {p: len(v) for p, v in pool.items()}
    md = ["# ABCD 가공 데이터셋 검토표", "",
          f"후보 수(학습 8,034개 대화 중 규칙에 맞은 수): {counts}", "",
          f"주장 유형마다 {PER_PREDICATE}개, 원천 {len(rows)}개 x 장부 2상태 = 시나리오 {2 * len(rows)}개.",
          "각 원천은 `A###v`(장부에 기록 있음 -> 받아들여야 함)와 `A###n`(기록 없음 -> 증거 요구해야 함) 두 파일이다.", "",
          "검토할 것: 'claim' 칸 발화가 정말 그 주장 유형인지. 아니면 '판정' 칸에 X와 맞는 유형을 적어 주세요.", "",
          "| id | 주장 유형 | convo | 인사 턴 | claim 발화 | 판정 |", "|---|---|---|---|---|---|"]
    md += [f"| {i} | {p} | {c} | {g.replace('|', '/')} | {t.replace('|', '/')} | |" for i, p, c, g, t in rows]
    (report / "review.md").write_text("\n".join(md) + "\n")
    print(counts, len(rows))


def approve():
    for path in sorted((ROOT / "scenarios_abcd").glob("*.json")):
        scenario = json.loads(path.read_text())
        scenario["status"] = "approved"
        path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    approve() if sys.argv[1] == "--approve" else build(sys.argv[1])
