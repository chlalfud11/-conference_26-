# ABCD 데이터셋을 쓴 연구들

조사일: 2026-10-18. ABCD를 인용한 논문 98편(Semantic Scholar 기준)을 모두 모았고, 그중 arXiv 전문이 있는 77편은 본문에서 ABCD가 어떻게 쓰였는지 직접 확인했다 [Source 2, 3].

## 1. 한눈에 보기

- **ABCD는 "회사 지침을 지키며 일하는 상담원" 데이터다.** 손님이 원하는 것과 회사 규칙이 부딪힐 때, 상담원은 정해진 순서대로 행동(본인 확인, 구매 확인, 환불 등)을 해야 한다 [Source 1].
- **인용한 98편 중 실제로 ABCD를 실험에 쓴 논문은 약 30편이다.** 나머지는 관련 연구로 이름만 언급한다. 유명한 τ-bench도 이름만 언급한 쪽이다 [Source 3, 5].
- **쓰임새는 크게 다섯 갈래다.** 행동 예측과 업무 흐름 찾기, 대화 모델의 사전학습 재료, 개인정보 보호 실험, 최근(2025~2026년)의 사용자 시뮬레이터와 평가 도구, 에이전트 벤치마크의 참고 사례.
- **내 논문 실험과 같은 설계는 찾지 못했다.** 내 실험은 ABCD 손님 원문에 "장부 기록 있음/없음"을 짝지어, 모델과 결정표 중 어느 쪽이 근거 없는 주장을 덜 받아들이는지 비교했다. 비슷한 재료를 쓴 연구는 있지만 같은 질문을 던진 연구는 없었다. 이 결론은 반론 검토를 거쳐 범위를 좁힌 것이다(4장) [Source 4].

## 2. ABCD는 어떤 데이터인가

| 항목 | 내용 |
|---|---|
| 발표 | Chen 외, NAACL 2021, ASAPP [Source 1] |
| 규모 | 대화 10,042개(학습 8,034 / 검증 1,004 / 시험 1,004), 평균 22.1턴 [Source 1, 6] |
| 구조 | 상위 흐름 10개, 세부 흐름 55개(손님 의도), 상담원 행동 30종 [Source 1] |
| 수집 방법 | 시험을 통과한 크라우드워커(약 20%만 통과)가 상담원을, 다른 워커가 손님을 맡아 실시간 채팅 [Source 1] |
| 원래 과제 | AST(다음 행동 맞히기), CDS(대화 끝까지 단계별로 맞히기) [Source 1] |
| 원 논문 최고 성능 | AST 행동 정확도 65.8%(RoBERTa), CDS 31.9%(RoBERTa-Large). 사람은 CDS 82.7% [Source 1] |

쉽게 말해, 사람은 지침을 보며 잘 따라가는데 2021년 모델은 그 절반도 못 따라갔다. 이 차이를 줄이는 것이 ABCD 이후 연구의 출발점이었다.

알아 둘 점이 두 가지 있다.
- 원 논문에는 따로 한계 절이 없다 [Source 1].
- 데이터 안의 상담원은 손님이 스스로 말한 회원 등급을 시스템 조회 뒤 그대로 기록하기도 한다. 예: "Membership level of Silver has been noted"가 36회 나온다 [Source 6]. 즉 ABCD의 정답 행동이 늘 손님 주장을 검증하는 것은 아니다.

## 3. ABCD를 쓴 연구들

### 3.1 행동 예측과 업무 흐름 찾기

ABCD를 원래 목적에 가장 가깝게 쓴 연구들이다. 모두 ABCD로 직접 실험했다.

| 연구 | 한 일 | 핵심 결과 |
|---|---|---|
| Workflow Discovery (Hattami 외, TMLR) [Source 7] | 대화를 보고 상담원이 따른 업무 흐름을 글로 적어 내기 | AST에서 T5-Small이 89.1%로, 원 논문 65.8%를 크게 넘음 |
| AnyTOD (Zhao 외, EMNLP 2022) [Source 8] | 모델은 대화 상태만 읽고, 다음 행동은 규칙 프로그램이 정함 | 행동 정확도 90.5~91.9%. 흐름 하나만 배우고 나머지 9개에 적용하면 48.9~67.0% |
| KADS (White 외, ACL 2023) [Source 9] | 지침 문서를 찾아 붙여 행동 예측 | b-slot(행동 버튼) 정확도 79.5% → 85.2% |
| Workflows and Action Plans (Raimondo 외, 2023) [Source 10] | 처음 보는 흐름에 행동 계획을 줌 | 계획을 주면 5~6점 오름. 흐름 이름만 주면 효과 없음 |
| Multi-Step Workflow Action Prediction (ASAPP, 2023) [Source 11] | 여러 단계를 한 번에 예측 | 행동 F1 0.537 → 0.801 |
| Turning Conversations into Workflows (Salesforce, 2025) [Source 12] | 대화에서 업무 흐름 뽑아내기 | ABCD 상담원은 흐름을 자주 건너뛰거나 순서를 바꿔, 대화에 "잡음이 많다" |

**AnyTOD**는 내 논문과 구조가 가장 닮았다. "모델은 읽기만 하고, 결정은 규칙이 한다"는 점에서 결정표 방식과 같은 발상이다 [Source 8].

### 3.2 대화 모델의 사전학습 재료

- DialogStudio: 여러 대화 데이터를 모은 학습 묶음에 ABCD를 넣었다 [Source 13].
- SPACE-3: 사전학습 데이터 표에 ABCD가 있다. 표 제목은 확인하지 못했다 [Source 14].
- SM2(소수 예시 대화 상태 추적): 메타학습 재료로 ABCD 8,034개를 썼다 [Source 15].
- GALAXY는 참고문헌에만 ABCD가 있고 실제로는 쓰지 않았다 [Source 14].

### 3.3 개인정보 보호 실험

ABCD에는 손님 이름, 주문번호, 주소 같은 개인정보가 들어 있다. 그래서 개인정보를 숨기거나 공격하는 실험의 재료로 쓰인다.
- 임베딩에서 원문을 복원하는 공격(GEIA, ACL Findings 2023) [Source 16]
- 선택적 차분 프라이버시(JFT, EMNLP 2022) [Source 17]
- 대규모 언어 모델(LLM)로 개인정보 지우기(2023, 2026) [Source 18]

한 논문은 ABCD를 "포럼 게시글, 의료 키워드가 있는 데이터"라고 잘못 소개했다(ATDP, 2025) [Source 3]. 인용할 때 원 논문으로 직접 확인해야 하는 이유다.

### 3.4 시뮬레이터·평가자·지침 준수

| 연구 | ABCD를 쓴 방식 | 내 논문과의 관계 |
|---|---|---|
| MIMESIS (Meta, 2026) [Source 19] | ABCD 시나리오에서 까다로운 손님을 흉내 내는 시뮬레이터를 강화학습으로 훈련. 13가지 행동 중 하나가 "거짓 전제 말하기"(B8) | **가장 가깝다.** 다만 거짓말하는 손님을 잘 만드는 것이 목표다. 상담원이 그 말에 속는지는 재지 않는다 |
| TOD-ProcBench (Amazon, 2025) [Source 20] | ABCD 지침으로 의도 55개에 대한 조건-행동 지침서를 만들고, 응답이 지침을 어겼는지 판정 | 회원 등급처럼 손님이 말한 속성은 행동 전에 확인해야 한다는 지침이 있다. 하지만 미리 만든 대화를 판정할 뿐, 손님 주장이 사실인지는 다루지 않는다 |
| SAGE (2026) [Source 21] | ABCD 223턴으로 평가자 비교. 규칙과 작은 모델을 묶은 평가자(F1 0.929)가 GPT-4.1 판정자(0.873)보다 높음. 보정 후에는 차이가 통계적으로 유의하지 않음 | "규칙 대 LLM" 구도가 비슷하다. 다만 손님 말과 맞는지를 볼 뿐, 장부와 맞는지는 보지 않는다 |
| LAVOIR (2026) [Source 22] | ABCD 시험 대화 918개로 "언제 되물을지" 결정 | 작은 모델이 ABCD 손님 첫 말로 결정한다는 점이 비슷하다 |
| CUE (2026) [Source 23] | 사용자 시뮬레이터 학습에 ABCD 8,034개를 씀 | 실패 유형에 "부적절한 신원 전환을 받아들여 다른 사람 정보 노출"이 있다(τ2 데이터) |

### 3.5 에이전트 벤치마크는 ABCD를 이름만 언급한다

τ-bench, τ²-bench, CAR-bench는 모두 ABCD를 "미리 녹화된 대화로만 시험하는 오래된 방식"의 예로 든다. 데이터는 쓰지 않는다 [Source 5].

다만 τ-bench의 정책에는 내 논문과 같은 규칙이 있다. "사용자가 ID를 이미 말했더라도 반드시 본인 인증을 하라"와 "사실을 확인한 뒤에만 보상하라"이다. 그런데 채점은 최종 DB 상태로만 해서, 이 절차를 건너뛰어도 잡아내지 못한다. τ-bench 논문 스스로 그렇게 밝혔다 [Source 5].

## 4. 내 논문과의 관계

**새로운 점.** 확인한 범위에서, 손님 주장이 장부 기록으로 뒷받침되지 않거나 기록과 어긋날 때 에이전트가 그 주장을 받아들이는지를 ABCD로 측정한 연구는 없었다. 장부 기록 있음/없음을 통제하고 모델과 결정표를 비교한 연구도 없었다 [Source 3, 4].

**반론 검토에서 좁힌 부분.**
- **MIMESIS를 반드시 인용하고 차이를 밝혀야 한다.** ABCD 위에 거짓 전제 손님을 이미 만들었기 때문이다. 차이는 측정 대상이다. MIMESIS는 손님을 만드는 쪽을, 내 실험은 상담원이 받아들이는지를 잰다 [Source 19].
- **새로운 것은 "주장을 확인한다"는 발상이 아니라 통제된 실험 설계다.** ABCD 안에도 시스템 조회 단계가 있고, 손님이 말한 회원 등급을 그대로 기록하는 정답도 있다. 그래서 "장부 없음" 조건이 ABCD 원래 정답과 다를 수 있다는 점도 논문에 적어야 한다 [Source 6].
- **ABCD 밖에서는 이미 연구가 있다.** 속이는 손님을 상대로 에이전트를 시험한 연구로 CRAFT(EMNLP 2025, τ-bench 기반)와 이익 추구형 고객 공격 연구가 있다 [Source 24]. 그러니 "속이는 손님 연구가 처음"이라고 쓰면 안 된다.

**논문에 쓸 수 있는 문장(예시).** "ABCD는 업무 흐름 예측, 사전학습, 개인정보, 사용자 시뮬레이션 연구에 널리 쓰였다. 하지만 장부 기록 있음/없음을 통제해 에이전트가 근거 없는 고객 주장을 받아들이는지 측정한 연구는 찾지 못했다(MIMESIS, TOD-ProcBench, SAGE와 구별됨)."

**인용 추천.**
- 가장 가까운 연구: MIMESIS, TOD-ProcBench, SAGE
- 결정표와 같은 발상: AnyTOD
- 검증 규칙이 있지만 절차는 채점하지 않는 사례: τ-bench
- ABCD 상담원도 흐름을 자주 어긴다는 근거: Turning Conversations into Workflows [Source 12]

## 5. 한계

- Semantic Scholar가 찾은 인용 논문은 98편이다. Google Scholar는 보통 더 많이 잡으므로 빠진 논문이 있을 수 있다 [Source 2].
- arXiv 판이 없는 21편은 본문을 확인하지 못했다.
- GuidedTOD(Chained Prior, NAACL Findings 2025)는 반론 검토자가 PDF를 읽어 손님 주장 검증과 관련 없다고 봤지만, 다른 관찰자의 교차 확인은 없다 [Source 4].
- 데이터 버전 v1과 v1.1의 차이는 알 수 없다. ACL 최종본 PDF는 읽지 못했다.
- 검색 엔진 접속 제한 때문에 보조 조사 2개가 실패했다. 그 몫은 Semantic Scholar API와 arXiv 원문 직접 확인으로 대신했다 [Source 3].

## 조사 방법 (Method)

- 연구원 8명이 분야를 하나씩 맡았다. 원 논문, 업무 흐름 연구, LLM 에이전트, 사전학습, 프라이버시, 정책 준수·사용자 시뮬레이션, 데이터셋 비판을 맡은 7명과 반론 검토 1명이다. 보조 조사 3건을 돌렸고 그중 2개는 도구 문제로 실패했다.
- 두 차례 조사했다. 인용 목록은 Semantic Scholar API에서 인용 문맥과 함께 받았다.
- arXiv 전문 77편에서 "ABCD"가 어디에 몇 번 나오는지 직접 세어, 실제 사용과 단순 인용을 구분했다.
- 표현이 다르게 쓰인 경우를 잡으려고 "거짓 전제", "날조" 같은 말로 다시 검색했다. ABCD 데이터에서는 시스템 조회 뒤의 행동을 직접 셌다.
- 반론 검토를 세 차례 거쳤다.
  - τ-bench가 ABCD를 썼다는 주장: 기각
  - 두 프라이버시 논문이 ABCD를 쓰지 않았다는 연구원 보고: 원문 확인으로 기각(실제로는 썼음)
  - 내 실험의 신규성: 범위를 좁혀 유지
- 모든 기록은 세션 저널(.omo/ulw-research/20261018-161621/)에 실시간으로 남겼다.

## 출처 (Sources)

1. Chen 외, Action-Based Conversations Dataset, NAACL 2021, https://arxiv.org/abs/2104.00783 ; https://github.com/asappresearch/abcd
2. Semantic Scholar 인용 API(인용 맥락 포함, 98편), https://api.semanticscholar.org/graph/v1/paper/arXiv:2104.00783/citations (접근일 2026-10-18)
3. 이 조사의 원문 검증 기록: verify-fulltext.md, verify-fulltext-abcd-mentions.json, verify-paraphrase-regrep.json (세션 저널)
4. 반론 검토 기록: debate-log.md D1~D3, claim-graph.md C13 (세션 저널)
5. τ-bench, https://arxiv.org/abs/2406.12045 ; τ²-bench, https://arxiv.org/abs/2506.07982 ; CAR-bench, https://arxiv.org/abs/2601.22027
6. ABCD v1.1 데이터 직접 집계(verify-abcd-oracle.md); DialogStudio 통계, https://github.com/salesforce/DialogStudio
7. Workflow Discovery, https://arxiv.org/abs/2205.11690
8. AnyTOD, https://arxiv.org/abs/2212.09939
9. KADS, https://arxiv.org/abs/2306.03959
10. Workflows and Action Plans, https://arxiv.org/abs/2306.01729
11. Multi-Step Dialogue Workflow Action Prediction, https://arxiv.org/abs/2311.09593
12. Turning Conversations into Workflows, https://arxiv.org/abs/2502.17321
13. DialogStudio, https://arxiv.org/abs/2307.10172
14. SPACE-3, https://arxiv.org/abs/2209.06664 ; GALAXY, https://arxiv.org/abs/2111.14592
15. SM2 few-shot DST, https://arxiv.org/abs/2302.05932
16. GEIA, https://arxiv.org/abs/2305.03010
17. Just Fine-tune Twice, https://arxiv.org/abs/2204.07667
18. Text Sanitization, https://arxiv.org/abs/2311.10785 ; Anonymous-by-Construction, https://arxiv.org/abs/2603.17217
19. MIMESIS, https://arxiv.org/abs/2610.09484
20. TOD-ProcBench, https://arxiv.org/abs/2511.15976
21. SAGE, https://arxiv.org/abs/2609.00434
22. LAVOIR, https://arxiv.org/abs/2609.30706
23. CUE, https://arxiv.org/abs/2610.02460
24. CRAFT, https://aclanthology.org/2025.emnlp-main.114/ ; 이익 추구형 고객 공격, https://arxiv.org/abs/2512.24415
