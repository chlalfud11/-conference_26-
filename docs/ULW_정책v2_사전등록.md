# P4 승격 정책 (fail-closed) 사전등록

작성일: 2026-10-15
상태: 봉인 전

## 1. 배경

M1P1 실험에서 오염 기준① 7건이 발생했다. 진단 결과:
- 7건 모두 NLU가 risk_truth=high_risk인 턴을 risk_nlu=low_risk로 읽음
- 6건: speech_act=claim, claim_predicate=none (NLU가 주장 화행은 인식했으나 내용을 못 읽음)
- 1건: claim_predicate=heard_rumor (NLU가 고위험 주장을 저위험 소문으로 오분류)

현행 정책(P1)의 `risk_of()` 함수는 알려지지 않은 술어를 low_risk로 처리한다 (fail-open).

## 2. 개입

P4 정책: `speech_act=claim AND claim_predicate=none` → high_risk (fail-closed)

```python
def risk_of_v2(predicate: str, speech_act: str) -> str:
    if predicate in HIGH_RISK_PREDICATES:
        return "high_risk"
    if speech_act == "claim" and predicate == "none":
        return "high_risk"
    return "low_risk"
```

## 3. 가설

H1 (주): M1P4는 M1P0보다 기준① 비율이 낮다.
H2 (부): M1P4는 M1P0보다 TCAR이 높다.

비교 대상이 M1P1이 아닌 M1P0인 이유:
- M1P0(구조화 기억만)이 논문의 기준선
- M1P1 대비는 TCAR 손실로 인해 유의하지 않을 가능성이 높음

## 4. 검정

### 4.1 주 검정 (H1)
- 지표: 기준① 비율 (시나리오별 합산)
- 방법: 쌍별 순열 검정 (27시나리오)
- 유의수준: α = 0.05, 양측

### 4.2 부 검정 (H2)
- 지표: TCAR (low_risk rumor 턴 중 accept_as_belief 비율)
- 방법: Fisher 정확 검정 또는 χ² 검정
- 유의수준: α = 0.05, 양측

### 4.3 보조 비교
- M1P4 vs M1P1: 기준① 비율
- M1P4 vs M0P0: 기준① 비율
- 다중비교 보정: Holm 방법

## 5. 실행 계획

### 5.1 시나리오
- 기존 18편 (scenarios/)
- 적대적 9편 (scenarios_adversarial/)
- 합계: 27편

### 5.2 조건
- M1P4: 새로 실행 (27 × 3seed = 81회)
- M1P0, M1P1, M0P0: 기존 로그 사용 (logs/runs.jsonl, logs/adversarial/runs.jsonl)

### 5.3 seed
- 11, 29, 47 (기존과 동일)

### 5.4 모델
- EXAONE-3.5-2.4B-Instruct-Q4_K_M (기존과 동일)

## 6. 종료 규칙

1. 81회 1회 실행, 결과를 근거로 시나리오·seed를 추가하지 않는다.
2. 분석 코드는 실행 전에 작성한다.
3. 계획한 검정 전부를 보고한다.
4. 봉인 후 코드를 수정하지 않는다.

## 7. 한계 (미리 명시)

1. 7건 중 1건(pred=heard_rumor 오분류)은 P4로 수정 불가 — 정책 범위 밖
2. M1P1 대비 TCAR 손실 예상 (18/27 → 15/27)
3. 오프라인 재생 기반 설계 — 실제 실행에서 NLU 출력이 달라질 수 있음

## 8. 봉인 대상 파일

- ulw_policy_v2.py
- ulw_policy_v2_run.py
- docs/ULW_정책v2_사전등록.md (이 파일)
- scenarios/*.json (18편)
- scenarios_adversarial/*.json (9편)

봉인 명령: `python3 ulw_policy_v2_run.py freeze`
