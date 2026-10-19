# ABCD v4 결과 (정답 분리, 가게 장부 하나, 날짜 필드)

사전등록 `docs/ABCD_v4_사전등록.md`. 실행 2268회, 완결: True, 봉인 후 실행: True, 해시 일치: {'prereg': True, 'scenarios': True, 'ledger': True, 'answer_key': True}.

## 주장 턴 결정 정확도 (높을수록 좋음)

| 조건 | 기록 있음 v | 기록 없음 n | 날짜 불일치 d |
|---|---|---|---|
| F-M1P0 | 52.8% | 56.3% | 27.8% |
| S-M1P0 | 32.9% | 76.6% | 12.3% |
| F-M1P1 | 91.3% | 83.7% | 75.0% |

- **주 지표** 정확도 F-M1P1 83.3% vs F-M1P0 45.6%: 차이 37.7%p, 95% CI [30.6%p, 44.7%p], p = 5.00e-05 (원천 84개)
- 사전등록 채택 규칙 충족: **True**

## 부 지표 (Holm 보정)

- (a) 기록 있음(v) 과잉 거절률, M1P1 - M1P0: 차이 -38.5%p, 95% CI [-48.8%p, -28.6%p], Holm p = 0.0002
- (b) 기록 없음(n) 수용률, M1P1 - M1P0: 차이 14.3%p, 95% CI [6.3%p, 22.2%p], Holm p = 0.0011
- (c) 날짜 불일치(d) 반박률, M1P1 - M1P0: 차이 47.2%p, 95% CI [34.5%p, 59.1%p], Holm p = 0.0002
- (d) 정확도, 전체 장부(F) - 검색(S), 둘 다 M1P0: 차이 5.0%p, 95% CI [0.1%p, 9.8%p], Holm p = 0.0520

## 기술 통계

- 반박 판(d)을 뺀 v·n 정확도: F-M1P1 87.5% vs F-M1P0 54.6%, 차이 32.9%p, p = 5.00e-05
- F-M1P0: NLU 술어 정확도 75.0%, 오답 411건 중 NLU 오독 108건, 장부 인정 발화 510, 날짜 언급 발화 496
  - 결정 분포: {"v": {"request_evidence": 31, "accept_as_belief": 133, "dispute": 63, "defer": 19, "reject": 6}, "n": {"request_evidence": 142, "reject": 22, "accept_as_belief": 5, "dispute": 79, "defer": 4}, "d": {"request_evidence": 54, "accept_as_belief": 106, "dispute": 70, "defer": 15, "reject": 7}}
- S-M1P0: NLU 술어 정확도 75.0%, 오답 449건 중 NLU 오독 116건, 장부 인정 발화 395, 날짜 언급 발화 305, 검색 적중률(v·d) 97.0%, 다른 손님 줄 평균 3.50개
  - 결정 분포: {"v": {"dispute": 30, "accept_as_belief": 83, "request_evidence": 126, "reject": 4, "defer": 9}, "n": {"request_evidence": 193, "accept_as_belief": 16, "dispute": 37, "defer": 3, "reject": 3}, "d": {"request_evidence": 162, "accept_as_belief": 49, "dispute": 31, "defer": 3, "reject": 7}}
- F-M1P1: NLU 술어 정확도 75.0%, 오답 126건 중 NLU 오독 126건, 장부 인정 발화 610, 날짜 언급 발화 542
  - 결정 분포: {"v": {"accept_as_belief": 230, "request_evidence": 22}, "n": {"request_evidence": 211, "accept_as_belief": 41}, "d": {"dispute": 189, "accept_as_belief": 41, "request_evidence": 22}}

## 해석에 주의할 점

- 정답은 설계로 정해진다(v 믿기, n 증거 요구, d 반박). 사람 라벨이 아니다.
- d의 날짜 불일치는 14~28일이다. 날짜가 달라도 같은 사건일 수 있으므로, d에서 믿기를 고른 응답이 꼭 틀렸다고 보기 어렵다. 그래서 v·n만의 정확도를 함께 보고한다.
- M1P1은 NLU가 읽은 술어로 엔진이 장부를 조회해 결정한다. NLU가 맞으면 결정표는 정답과 같은 규칙을 따르므로, M1P1의 오답은 대부분 NLU 오독에서 나온다.
- 대사 오염은 판정하지 않았다. 장부 인정·날짜 언급은 정규식 기술 통계다.
