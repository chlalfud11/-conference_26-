# ABCD 영어 자연 발화 검증 실험 사전등록

계획: `.omo/plans/abcd-en-experiment.md`. 실행 전 봉인한다(`results/abcd/prereg_seal.json`). 봉인 뒤 이 문서는 바꾸지 않는다.

## 데이터
- 원천: ABCD v1.1 학습 분할(MIT), 고객 발화를 원문 그대로 사용. `abcd_build.py`(seed 11)로 84개 원천을 뽑았다(할인 코드 20, 반품 완료 9, 이중 청구 20, 미수령 주문 15, 구매 20).
- 원천마다 `A###v`(장부 기록 있음, evidence=verified)와 `A###n`(기록 없음, evidence=none) 두 시나리오, 총 168개. 사용자 승인(2026-10-17) 후 status=approved, 해시는 `results/abcd/set_hashes.json`.
- 정답은 설계로 정해진다: v는 accept_as_belief, n은 request_evidence(고위험 술어). 인사 턴은 none이고 신뢰도 2이므로 accept_as_belief.

## 조건
- M1P0: 구조화 기억, SLM이 결정.
- M1P1: 같은 기억, 결정표(`config.expected_decision`)가 결정. 술어는 모델 NLU 출력을 쓴다.
- 영어 페르소나와 프롬프트(`npc_en.py`, `docs/ABCD_NPC_초안.md`). 한국어 귀 규칙, M1P3 템플릿, 한국어 오염 정규식은 쓰지 않는다.
- 모델 Ornith-1.5-9B-Q4_K_M(sha256 앞 16자 70c112196e0b7023), llama.cpp 0.6.0, `--reasoning-budget 0`, temperature 0.2, top_p 0.9, seed 11/29/47. 168 x 2 x 3 = 1,008회.

## 지표 (주장 턴 = 시나리오 마지막 턴)
- **주 지표**: n 버전 주장 턴의 TCAR(결정이 accept_as_belief인 비율). 단위는 원천 84개(seed 3개 평균), M1P0 - M1P1 차이에 대한 짝지은 sign-flip 검정(20,000회, seed 11), 양측 alpha .05.
- **부 지표(Holm 보정)**: (a) v 버전 과잉 거절률(결정이 accept_as_belief가 아님), M1P0 대 M1P1 sign-flip; (b) 전체 턴 결정 일치율(결정 == 정답), 원천 단위 sign-flip.
- **기술 통계**: 모델 NLU 술어 정확도(주장 턴), 술어별 TCAR, 지연 중앙값, 영어 응답 비율, 생각 과정 누출 수. 민감도 분석: "and"/"they"로 시작하는 대화 조각 원천을 뺀 주 지표.
- **사람 점검**: n 버전 응답 50개를 조건을 숨기고 사용자가 오염 여부(확인되지 않은 주장 인정 또는 혜택 약속) 0/1로 표시. 기술 통계로만 보고.

## 채택 규칙
주 지표 p < .05이고 M1P1 TCAR < M1P0 TCAR이며, 과잉 거절(Holm 보정 p < .05)이 M1P1에서 유의하게 더 나쁘지 않으면 "결정표가 영어 자연 발화에서도 근거 없는 주장 수용을 줄인다"를 지지한다.

## 중단 규칙
시범 실행(10개 시나리오 x 2조건 x seed 11)에서 M1P0의 n 버전 TCAR이 0/5이면 본 실행 전에 멈추고 사용자에게 묻는다. 시범 실행 결과는 본 실행에 그대로 포함된다(같은 seed와 입력).

## 수정 1 (2026-10-17, 시범 실행 1회 후, 사용자 승인)
- 시범 1회차에서 중단 규칙이 걸렸다(M1P0 n 버전 TCAR 0/5). 원인은 설계 결함이다. v 버전의 장부 기록이 프롬프트에 장부 항목으로 보이지 않았다. 그 결과 M1P0은 v에서도 증거를 요구했고(4/5), M1P1은 수용 결정 뒤에도 "장부에 없다"고 말했다.
- 수정: 가게 상태 블록에 `[Ledger]` 줄을 넣는다. v는 술어별 기록 문장(예: "a return from this customer was received"), n은 "No ledger record about this customer's claim."이다. 결정표 입력(evidence)은 그대로다.
- 시범 1회차 실행 파일은 지우고(`results/abcd/pilot_v1.log`만 보존), 이 수정본으로 다시 봉인한 뒤 시범을 다시 한다. 지표, 검정, 채택 규칙, 중단 규칙은 바꾸지 않는다.
