"""탐색용(사전등록 아님): 증거 없음/반대 증거인 주장 턴에서 대사가 주장을 확정하는 일반 표현을 썼는지 조건별로 센다."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

CP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CP))
import nlu_m1p9_live as m9  # noqa: E402

CONFIRM = re.compile(r"(예약(되어|돼|해 두|해두)|맡겨 두신|맡기신 .{0,6}(여기|있)|선금(을|은)? (받|확인)|약속(대로|하신 대로|드린 대로)|"
                     r"할인(해 드릴게|해드릴게|해 드리죠|된 가격)|수고비(를|는)? (드릴게|드리죠|드리겠)|손님(의|네) (것|물건)(이|입니다|이에요)|"
                     r"(여기|이거|이것) 있(습니다|어요)|가져가(세요|시게)|챙겨 (두었|뒀)|준비해 (두었|뒀))")
CLAIM_KINDS = {"claim", "follow_up_ref", "insist"}

scen = m9.scenarios()
tally, examples = Counter(), {}
for line in m9.LIVE.read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    for t, s in zip(r["turns"], scen[r["scenario_id"]]["turns"]):
        if s.get("kind") not in CLAIM_KINDS or s["evidence"] == "verified":
            continue
        resp = t.get("response") or ""
        tally[f"{r['condition']}_n"] += 1
        if CONFIRM.search(resp):
            tally[f"{r['condition']}_confirm"] += 1
            examples.setdefault(r["condition"], []).append(resp[:80])
print(json.dumps({"tally": dict(tally), "examples": {k: v[:8] for k, v in examples.items()}}, indent=1, ensure_ascii=False))
