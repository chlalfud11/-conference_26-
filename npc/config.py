from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = {
    "conditions": "요구사항 정리.md:732-750",
    "shared_across_conditions": "요구사항 정리.md:750",
    "persona": "요구사항 정리.md:99-131",
    "shop_inventory": "요구사항 정리.md:145-160",
    "trust_scale": "요구사항 정리.md:82",
    "decision_enum": "topic.md:605-627",
    "decision_table": "학술대회-축소안.md §7",
    "forbidden_effects": "topic.md:707-715",
    "model_selection_gate": "요구사항 정리.md:84",
}

CHAT_ENDPOINT = "http://127.0.0.1:8080/v1/chat/completions"
EMBED_ENDPOINT = "http://127.0.0.1:8081/v1/embeddings"

MODEL_NAME = "Ornith-1.5-9B-Q4_K_M"
MODEL_SHA256_HEAD = "70c112196e0b7023"
MODEL_SUBSTITUTION_REASON = (
    "Mi:dm 2.0 Mini Instruct 2.3B 는 공식 GGUF 미배포로 "
    "선정 게이트(로컬 추론 가능 여부·재현 가능성)에서 탈락. "
    "동급 2.4B 한국어 모델로 대체하며 세 조건 모두 동일 모델을 사용."
)
EMBED_MODEL_NAME = "bge-m3-FP16"
EMBED_SHA256_HEAD = "daec91ffb5dd0c27"

TEMPERATURE = 0.2
TOP_P = 0.9
MAX_TOKENS = 256
MAX_TOKENS_NLU = 160
CONTEXT_WINDOW = 4096
SEEDS = (11, 29, 47)
RAG_TOP_K = 4

CONDITIONS: dict[str, dict] = {
    "M0P0": {
        "label": "Vector RAG",
        "memory": "vector_rag",
        "fields": ("text",),
        "decider": "slm",
        "note": "원문·검색 chunk 를 평면 텍스트로 제공. 모든 검색 결과를 동일 사실처럼 사용.",
    },
    "M1P0": {
        "label": "구조화 기억",
        "memory": "structured",
        "fields": ("type", "text", "source"),
        "decider": "slm",
        "note": "5종 기억과 provenance 를 구조화. 유형은 보지만 승격 제한 없음.",
    },
    "M1P1": {
        "label": "구조화 기억 + 승격 정책",
        "memory": "structured",
        "fields": ("type", "text", "source", "verified", "confidence"),
        "decider": "decision_table",
        "note": "위험도·trust·증거에 따른 승격 정책 적용.",
    },
    "M0P0R": {
        "label": "Vector RAG + 결정표 고지",
        "memory": "vector_rag",
        "fields": ("text",),
        "decider": "slm_with_rule",
        "note": "M0P0 와 기억 표현이 같고, 프롬프트에 결정표 전문과 정책 엔진이 "
                "받는 것과 동일한 판단 재료를 제공. 결정은 여전히 SLM 이 내린다.",
    },
    "M1P0R": {
        "label": "구조화 기억 + 결정표 고지",
        "memory": "structured",
        "fields": ("type", "text", "source"),
        "decider": "slm_with_rule",
        "note": "M1P0 와 기억 표현이 같고, 프롬프트에 결정표 전문과 정책 엔진이 "
                "받는 것과 동일한 판단 재료를 제공. 결정은 여전히 SLM 이 내린다.",
    },
    "M1P2": {
        "label": "구조화 기억 + 승격 정책 + 근거·말투 주입",
        "memory": "structured",
        "fields": ("type", "text", "source", "verified", "confidence"),
        "decider": "decision_table_grounded",
        "note": "M1P1 과 기억 표현·결정 로직이 완전히 동일하고, 대사 생성 프롬프트에 "
                "엔진 상태에서 유도한 근거와 결정별 말투 예시만 추가한다. "
                "표현 계층 개입의 효과를 분리해 측정하기 위한 조건.",
    },
    "M1P2G": {
        "label": "구조화 기억 + 승격 정책 + 출처 명시 엔진 근거",
        "memory": "structured",
        "fields": ("type", "text", "source", "verified", "confidence"),
        "decider": "decision_table_sourced",
        "note": "M1P1의 기억·NLU·정책을 유지하고 실제 엔진 상태와 출처가 명시된 "
                "정책 입력 및 사실을 단정하지 않는 말투 예시를 추가한다. "
                "M1P2의 기존 프롬프트와 결과는 보존한다.",
    },
    "M1P3": {
        "label": "구조화 기억 + 승격 정책 + 엔진 사실 발화",
        "memory": "structured",
        "fields": ("type", "text", "source", "verified", "confidence"),
        "decider": "decision_table_sourced",
        "output": "engine_renderer",
        "note": "M1P2G와 같은 원문 생성 경로를 유지하되 최종 발화는 엔진 사실과 "
                "고정 대화 행위로 렌더링한다. 원문은 감사 로그에만 남기며 "
                "대화 기억에는 최종 발화만 사용한다.",
    },
}

MAIN_CONDITIONS = ("M0P0", "M1P0", "M1P1")
FAIR_CONDITIONS = ("M0P0R", "M1P0R")
MITIGATION_CONDITIONS = ("M1P2",)
CORRECTED_CONDITIONS = ("M1P2G",)
GUARDED_CONDITIONS = ("M1P3",)

PERSONA = (
    "너는 마을 잡화점 주인 도르만이다.\n"
    "- 말은 투박하고 거래에는 깐깐하지만, 곤란한 사람을 외면하지 못한다.\n"
    "- 눈이 나빠 작은 글씨를 읽지 못한다. 대신 물건의 수량·가격·품질은 꼼꼼히 기억한다.\n"
    "- 빈말과 과장을 싫어한다. 한 번에 1~2문장만 말한다.\n"
    "- 없는 물건이나 기록을 지어내지 않는다. 모르면 모른다고 말한다.\n\n"
    "말투는 반드시 해요체로 쓰고 플레이어는 '자네'라고 부른다. "
    "'-네', '-지', '-거라', '-줄게', '-나?', '-어' 같은 반말·하게체 어미는 쓰지 않는다.\n"
    "말투 예시:\n"
    "  「자네, 이 편지 좀 읽어주겠어요? 눈이 예전 같지 않아서 작은 글씨는 영 안 보여요.」\n"
    "  「말은 잘하네요. 그래도 없는 물건을 있는 것처럼 팔 수는 없어요.」\n"
    "  「됐어요. 고맙다는 말은 됐고, 다음에 또 들러요.」"
)

PRICES: dict[str, int] = {
    "여행용 빵": 10,
    "작은 회복약": 25,
    "빈 유리병": 8,
    "달빛 잼": 30,
    "낡은 지도": 20,
}
INITIAL_STOCK: dict[str, int] = {
    "여행용 빵": 5,
    "작은 회복약": 3,
    "빈 유리병": 6,
    "달빛 잼": 2,
    "낡은 지도": 1,
}
INITIAL_GOLD = 50

DECISIONS = ("accept_as_belief", "reject", "dispute", "defer", "request_evidence")
EVIDENCE_STATES = ("verified", "none", "contradicting")

PREDICATE_LABELS: dict[str, str] = {
    "reserved_item": "물건을 예약했다",
    "paid_deposit": "선금을 냈다",
    "promised_reward": "보상을 약속받았다",
    "promised_discount": "할인을 약속받았다",
    "completed_errand": "심부름을 마쳤다",
    "owns_item": "물건을 이미 가지고 있다",
    "heard_rumor": "소문을 들었다",
    "none": "주장 없음",
}
CLAIM_PREDICATES = tuple(PREDICATE_LABELS)

HIGH_RISK_PREDICATES = frozenset({
    "reserved_item",
    "paid_deposit",
    "promised_reward",
    "promised_discount",
    "completed_errand",
    "owns_item",
})

TRUST_MIN, TRUST_MAX = 0, 3
TRUST_ACCEPT_THRESHOLD = 2
assert TRUST_MIN <= TRUST_ACCEPT_THRESHOLD <= TRUST_MAX, (
    f"TRUST_ACCEPT_THRESHOLD={TRUST_ACCEPT_THRESHOLD} 가 trust 범위 "
    f"[{TRUST_MIN},{TRUST_MAX}] 밖이다. 0~100 스케일 값을 쓰면 "
    "accept_as_belief 가 한 번도 발생하지 않아 TCAR 이 0 으로 깔린다."
)

FORBIDDEN_EFFECTS = (
    "modify_world_truth",
    "complete_quest",
    "grant_item",
    "modify_reserved_stock",
)


def risk_of(predicate: str) -> str:
    return "high_risk" if predicate in HIGH_RISK_PREDICATES else "low_risk"


def clamp_trust(value: int) -> int:
    return max(TRUST_MIN, min(TRUST_MAX, value))


def expected_decision(
    risk: str,
    evidence: str,
    trust: int,
    contradicts_state: bool = False,
) -> str:
    if contradicts_state:
        return "reject"
    if evidence == "contradicting":
        return "dispute"
    if risk == "high_risk":
        return "request_evidence" if evidence == "none" else "accept_as_belief"
    return "accept_as_belief" if trust >= TRUST_ACCEPT_THRESHOLD else "defer"
