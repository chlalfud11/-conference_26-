# 실험 시스템 아키텍처

학술대회 논문 「구조화 기억과 승격 정책의 효과 분리」의 구현 명세.
기준 문서: `../학술대회-축소안.md`, `../topic.md`, `../요구사항 정리.md`

---

## 1. 폴더 구조

```
conference-paper/
├── npc/
│   ├── config.py      실험 고정 설정 · 승격 결정표 · 출처 대조표
│   ├── engine.py      게임 엔진 (World Truth 쓰기 독점, 5종 원장, 원자적 거래)
│   ├── llm.py         로컬 추론 클라이언트 (stdlib urllib 만 사용)
│   ├── adapters.py    조건별 기억 어댑터 — 세 조건의 유일한 차이점
│   ├── runner.py      대화 루프
│   ├── cli.py         실행 진입점
│   ├── eval.py        지표 계산 (CCR / TCAR / Macro-F1 / PCFBR)
│   └── diagnose.py    NLU 입력 이해 진단 (topic.md §18.8)
├── scenarios/         시나리오 6유형 JSON
├── logs/runs.jsonl    실행 로그 (1 run = 1 line)
├── results/           metrics.csv, nlu_diagnostic.json
├── figures/           논문 그림
├── paper/             논문 초안
├── slides/            발표자료
├── tests/             pytest
└── models/            GGUF (저장소에 커밋하지 않음)
```

---

## 2. 레이어와 권한

```
플레이어 발화
      │
      ▼
[1] SLM 입력 이해 (NLU)          JSON Schema 강제, claim_predicate enum
      │
      ▼
[2] Player Claim 원장 기록        save_claim — 사실로 확정하지 않음
      │
      ▼
[3] 결정                          M0P0·M1P0: SLM 자유 선택
      │                           M1P1: 정책 결정표
      ▼
[4] 승격                          accept_as_belief 일 때만 NPC Belief 생성
      │                           World Truth 는 어떤 경우에도 불변
      ▼
[5] SLM 대사 표현                 승인된 결정을 한국어로
      │
      ▼
[6] Generated Text 기록           memory_eligible = 0 (DB CHECK 제약)
```

게임 엔진은 Unity 가 아니라 **`World Truth` 의 유일한 쓰기 권한을 가진 Python 런타임**(`engine.py`)이다.
세 조건 모두 같은 엔진을 쓰며, P0 조건에서도 엔진의 World Truth 보호를 우회하지 않는다.

---

## 3. 5종 기억 원장 (SQLite)

| 테이블 | 역할 | 구조적 제약 |
|---|---|---|
| `world_truth` | 게임의 정규 사실(골드·재고·예약·인벤토리) | `CHECK (source = 'game_engine')` |
| `committed_event` | 실제로 일어난 사건 (append-only) | `world_version_before/after` 로 상태와 연결 |
| `player_claim` | 플레이어가 주장한 내용 | `risk`, `evidence` enum 강제 |
| `npc_belief` | NPC 가 믿는 내용 | `claim_id` 외래키로 출처 추적 |
| `generated_text` | 모델이 생성한 문장 | `CHECK (memory_eligible = 0)` |

두 CHECK 제약이 논문의 구조적 불변조건을 **DB 레벨에서** 강제한다.

- `generated_text` 를 기억 대상으로 승격하려는 UPDATE → `IntegrityError`
- `player_claim` 을 출처로 하는 `world_truth` INSERT → `IntegrityError`

둘 다 `tests/test_atomicity.py` 에서 `pytest.raises` 로 고정했다.

---

## 4. 세 조건의 정확한 차이

| | M0P0 | M1P0 | M1P1 |
|---|---|---|---|
| 기억 표현 | 원문 chunk 평면 텍스트 | 5종 원장 구조화 | 5종 원장 구조화 |
| 검색 | bge-m3 임베딩 코사인 top-4 | 유형별 전체 조회 | 유형별 전체 조회 |
| NPC 가 보는 필드 | `text` | `type`, `text`, `source` | `type`, `text`, `source`, `verified`, `confidence` |
| 결정 주체 | SLM | SLM | 정책 결정표 |

**나머지는 전부 동일하다**: 모델, persona, 가게 상태 블록, 시나리오, 입력 발화,
temperature 0.2, top_p 0.9, max_tokens 256, seed, 턴당 추론 호출 2회, 평가 코드.
턴당 호출 횟수를 맞춘 것은 조건 간 지연 비교를 공정하게 하기 위해서다.

---

## 5. 승격 결정표

`config.expected_decision(risk, evidence, trust, contradicts_state)`

| 위험도 | 증거 상태 | trust | 결정 |
|---|---|---|---|
| — | 현재 상태와 명백히 모순 | — | `reject` |
| — | 주장과 반대되는 접근 가능 증거 | — | `dispute` |
| high | 접근 가능한 증거 없음 | — | `request_evidence` |
| high | 검증된 증거 있음 | — | `accept_as_belief` |
| low | 상충 증거 없음 | ≥ 2 | `accept_as_belief` |
| low | 상충 증거 없음 | < 2 | `defer` |

축소안 §7 의 표에서 저위험 + 반대 증거 칸이 비어 있었다. `dispute` 로 완성했다.

`trust` 는 0~3 정수다. 모듈 로드 시점의 `assert` 가 0~100 스케일 값의 유입을 차단한다.
`TRUST_ACCEPT_THRESHOLD = 70` 을 주입하면 import 단계에서 즉시 실패한다 (변이 검증 완료).

이 함수는 **두 역할을 겸한다**: M1P1 의 결정 주체이자, 세 조건 공통의 정답 라벨.
M1P1 은 `risk` 를 NLU 가 추출한 predicate 에서 유도하므로 NLU 오류가 정책으로 전파된다.
오라클을 쓰지 않는 end-to-end 구성이며, NLU 정확도는 `diagnose.py` 로 따로 보고한다.

### 증거 접근성의 출처

`evidence` 는 `read` Skill 의 산출물이 아니라 **시나리오가 주는 입력**이다.
이는 "System Truth 와 NPC Accessible Evidence 를 분리한다"(`topic.md:572-603`)는 설계와
일치하므로 Skill 축소에 따른 논리 손실이 없다.

---

## 6. 지표와 조작적 정의

### CCR (Player-Claim Contamination Rate)

```
CCR = 오염 판정된 주장 수 / 주입한 미검증 주장 수
```

분모: `scored` 턴 중 `evidence ∈ {none, contradicting}`.
분자: 아래 네 기준 중 **하나라도** 걸린 턴.

| 기준 | 판정 방법 |
|---|---|
| `promoted_without_policy` | `decision == accept_as_belief` 인데 정답이 아님 |
| `asserted_as_fact_in_utterance` | 대사가 시나리오의 `forbidden_assertions` 정규식에 매칭 |
| `used_as_action_basis` | 거짓 주장에 근거한 거래가 성사됨 |
| `world_truth_changed` | 시나리오 `invariants` 의 fact 가 0 이 아님 |

### 조건 간 비교 가능성

M0P0 에는 구조화된 Belief 개념이 없다. 그러나 세 조건 모두 같은 엔진을 쓰므로
결정 라벨과 Belief 레코드는 세 조건에서 동일하게 수집된다.
**조건별로 다른 것은 모델이 보는 입력과 결정 주체뿐**이며, 측정 코드는 하나다.

### 나머지 지표

```
TCAR    = 올바르게 수용한 주장 수 / 수용 대상(정답이 accept_as_belief) 주장 수
MacroF1 = 5지 결정의 Macro-F1
PCFBR   = (Belief 로만 남고 World Truth 불변) / (정책상 믿어야 하는 거짓 주장 수)
```

신뢰구간은 Wilson score interval (z=1.96). scipy 없이 stdlib 로 계산한다.

보조 지표: NLU predicate 정확도, JSON Schema 성공률, 지연 p50/p95.

---

## 7. 재현 조건

| 항목 | 값 |
|---|---|
| 추론 런타임 | llama.cpp 0.6.0 (build 11429), `llama-server` |
| 생성 모델 | EXAONE-3.5-2.4B-Instruct-Q4_K_M, sha256 head `1660a3794acc3343` |
| 임베딩 모델 | bge-m3-FP16, sha256 head `daec91ffb5dd0c27` |
| 생성 설정 | temperature 0.2, top_p 0.9, max_tokens 256(NLU 160), context 4096 |
| seed | 11, 29, 47 |
| 외부 API | 사용하지 않음 |

같은 seed 로 두 번 호출하면 출력이 문자 단위로 동일함을 확인했다.
각 턴은 전체 messages 의 SHA-256 앞 16자리를 `prompt_hash` 로 기록한다.

### 모델 대체 사유

`요구사항 정리.md:84` 가 **로컬 추론 가능 여부와 재현 가능성**을 선정 게이트로 규정했다.
`Mi:dm 2.0 Mini Instruct 2.3B` 는 공식 GGUF 저장소가 접근 불가(401)이고
본체 저장소에 GGUF 가 없어 이 게이트에서 탈락했다.
동급(2.4B) 한국어 모델로 대체했으며 **세 조건 모두 동일 모델**을 사용하므로
조건 간 비교 타당성은 유지된다.

---

## 8. 실행

```bash
llama-server -m models/EXAONE-3.5-2.4B-Instruct-Q4_K_M.gguf \
             --host 127.0.0.1 --port 8080 -c 4096 -ngl 99 --jinja
llama-server -m models/bge-m3-FP16.gguf \
             --host 127.0.0.1 --port 8081 --embedding --pooling cls -c 8192 -ngl 99

python3 -m pytest tests/ -q
python3 -m npc.cli list
python3 -m npc.cli run --condition M1P1 --scenario S05_v1 --seed 11
python3 -m npc.cli runall --resume
python3 -m npc.eval
python3 -m npc.diagnose
```

---

## 9. 알려진 한계

1. **정책은 결정을 통제하지만 대사를 통제하지 못한다.** M1P1 에서 결정이
   `request_evidence` 인데 대사가 예약을 사실처럼 단정하는 사례를 관측했다.
   `topic.md` 아키텍처의 [8] 출력 검증 단계가 축소안 범위 밖이기 때문이며,
   결함이 아니라 **보고할 결과**로 다룬다. CCR 의 네 번째 기준이 이를 측정한다.
2. **NLU 오류가 정책으로 전파된다.** 오라클을 쓰지 않은 end-to-end 구성의 대가다.
   `diagnose.py` 로 정확도를 별도 보고한다.
3. **대사의 사실 단정 판정은 정규식 기반 1차 판정이다.** 저자 1인이 무작위 표본을
   재검해 일치율을 보고한다. 원어민 패널은 저널로 넘긴다.
4. **trust 는 대화 중 변하지 않는다.** 시나리오 단위 상수로 고정해 교란을 줄였다.
   관계 변화 동역학은 저널 범위다.
5. **NPC 1명, 상점 1개, 폐쇄 세계.** 일반화 주장을 하지 않는다.
