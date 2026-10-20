# ABCD v6 결과: 도구 호출(tool-calling) 기준선 T-M1P0

사전등록 `docs/ABCD_v6_toolcall_사전등록.md`. 봉인 후 실행: True, 해시 일치: True.

## v4 데이터 (84원천)

| 조건 | 실행 | 정확도 | 반박 정답 (d) | 잘못 수용 (n·d) | 잘못 거부 (v) | 보류 (v) |
|---|---|---|---|---|---|---|
| F-M1P0 | 756 | 45.6% | 27.8% | 22.0% | 27.4% | 19.8% |
| F-M1P1 | 756 | 83.3% | 75.0% | 16.3% | 0.0% | 8.7% |
| S-M1P0 | 756 | 40.6% | 12.3% | 12.9% | 13.5% | 53.6% |
| T-M1P0 | 756 | 63.4% | 28.2% | 24.4% | 11.9% | 24.2% |

- **주 지표** 정확도 F-M1P1 - T-M1P0: +20.0%p, 95% CI [+14.3%p, +25.7%p], Holm p = 1.00e-04 → 결정표가 더 나음: **True**
- 도구 호출률 96.4%, 고른 종류가 정답 술어인 비율 93.6%, 형식 실패 0회
- T-M1P0 결정 분포: {"v": {"accept_as_belief": 161, "dispute": 29, "request_evidence": 57, "defer": 4, "reject": 1}, "n": {"request_evidence": 247, "dispute": 3, "accept_as_belief": 1, "reject": 1}, "d": {"dispute": 71, "accept_as_belief": 122, "request_evidence": 50, "defer": 8, "reject": 1}}

## v5 검증 세트 (59원천)

| 조건 | 실행 | 정확도 | 반박 정답 (d) | 잘못 수용 (n·d) | 잘못 거부 (v) | 보류 (v) |
|---|---|---|---|---|---|---|
| F-M1P1 | 531 | 74.8% | 62.7% | 24.9% | 0.0% | 13.0% |
| T-M1P0 | 531 | 64.6% | 26.6% | 27.7% | 18.6% | 12.4% |

- **주 지표** 정확도 F-M1P1 - T-M1P0: +10.2%p, 95% CI [+1.7%p, +18.5%p], Holm p = 0.0223 → 결정표가 더 나음: **True**
- 도구 호출률 99.8%, 고른 종류가 정답 술어인 비율 94.0%, 형식 실패 0회
- T-M1P0 결정 분포: {"v": {"accept_as_belief": 122, "request_evidence": 21, "dispute": 33, "defer": 1}, "n": {"request_evidence": 174, "dispute": 3}, "d": {"accept_as_belief": 98, "dispute": 47, "request_evidence": 29, "defer": 3}}

## 부 지표 (Holm)

- a_T_vs_F-M1P0_accuracy_v4: +17.7%p, 95% CI [+12.0%p, +23.4%p], Holm p = 0.0002
- b_dispute_d_P1_vs_T_v4: +46.8%p, 95% CI [+35.3%p, +57.5%p], Holm p = 0.0002
- c_wrong_accept_nd_P1_vs_T_v4: -8.1%p, 95% CI [-17.1%p, +1.0%p], Holm p = 0.1914
- b_dispute_d_P1_vs_T_heldout: +36.2%p, 95% CI [+22.0%p, +50.3%p], Holm p = 0.0002
- c_wrong_accept_nd_P1_vs_T_heldout: -2.8%p, 95% CI [-14.1%p, +9.0%p], Holm p = 0.6755

## 해석에 주의할 점

- 도구 호출은 llama-server의 tools API가 아니라 JSON 구조화 출력으로 흉내 냈다. 실제 function calling과 다를 수 있다.
- τ-bench 자체를 재현한 것이 아니라, τ-bench가 평가하는 tool-calling 에이전트 방식을 이 과제에 구현한 것이다.
- 수용/보류/거부 열은 v4·v5와 같은 사후 3분류 기준(`docs/ABCD_3way_사후분석.md`)으로 계산했다.
- 검증 세트에는 F-M1P0이 없다.
