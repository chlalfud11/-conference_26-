# 장부 v3(오늘 날짜) + 벡터DB 실험 결과

사전등록 `docs/ABCD_장부v3_사전등록.md` (봉인 후 실행: True, 해시 일치: True, 완결: True). 새 실행 1008회 + L2(이전 실험).

## 기록이 있는데 받아들이지 않은 비율 (M1P0, 낮을수록 좋음)

| 조건 | 비율 |
|---|---|
| L2 장부 v2 + 지시 수정 | 76.2% |
| L3 오늘 날짜 + 날짜 맞춤 장부(전체 제공) | 54.4% |
| L4 같은 장부를 벡터DB 검색 상위 5줄만 제공 | 79.0% |

- 주 지표 L2 대 L3: 차이 21.8%, 95% CI [13.1%, 31.0%], p = 0.0000
- L3 대 L4: 차이 -24.6%, Holm p = 0.0001

## 안전 점검 (기록 없는 주장 수용 증가)

- L3 − L2: 0.0% (CI 상한 0.0%), L4 − L2: 2.4% (CI 상한 6.0%). 통과: True

## 벡터DB 검색 품질 (L4)

- 기록 있음(v): 주장을 뒷받침하는 줄이 상위 5개에 든 비율 63.1%, 손님 본인 줄이 모두 든 비율 4.8%, 다른 손님 줄 평균 2.88개
- 기록 없음(n): 다른 손님 줄 평균 3.70개

## 기술 통계

- L2: {"decisions_v": {"reject": 7, "dispute": 105, "accept_as_belief": 60, "request_evidence": 64, "defer": 16}, "v_accept_rate": 0.23809523809523808, "disputes_mentioning_dates": 51, "n_accept": 0}
- L3: {"decisions_v": {"dispute": 66, "accept_as_belief": 115, "defer": 24, "request_evidence": 33, "reject": 14}, "v_accept_rate": 0.45634920634920634, "disputes_mentioning_dates": 16, "n_accept": 0}
- L4: {"decisions_v": {"request_evidence": 135, "accept_as_belief": 53, "dispute": 53, "defer": 9, "reject": 2}, "v_accept_rate": 0.21031746031746032, "disputes_mentioning_dates": 14, "n_accept": 6}
- 상대 날짜가 있는 원천(18개)의 수용: {"L2": {"rel_date_sources_accept": "12/54"}, "L3": {"rel_date_sources_accept": "16/54"}, "L4": {"rel_date_sources_accept": "6/54"}}

## 주의

- 기억의 `verified:` 표시는 여전히 모든 조건에 있다(비교 가능성 유지). 개선이 장부 때문인지 이 표시 때문인지 구분하지 못한다.
- L2와 L3는 날짜만이 아니라 장부 형식(행 형식, 손님 이름 포함)도 다르다. L2 대 L3의 차이를 날짜만의 효과로 보면 안 된다.
- 날짜 표현이 없는 원천은 '3일 전'을 기본값으로 썼다.
