# M1P8 리뷰 자료 (리뷰어 전달용)

계획: /Users/miryeong/0/08 졸업논문/start/.omo/plans/m1p8-ear-output.md (사용자 승인)

## 새로 만든 파일 (기존 파일 수정 없음)
- conference-paper/nlu_m1p8_live.py
- conference-paper/docs/M1P8_사전등록.md
- conference-paper/scenarios_m1p8/S50.json ~ S73.json (블라인드 에이전트 작성, 24편)
- conference-paper/logs/m1p8/{precheck,prompt_freeze,set_freeze}.json, runs.jsonl, live.log
- (실행 후) conference-paper/results/bottleneck/m1p8_analysis.json, m1p8_report.md

## 봉인 순서 증거
- precheck: 2026-10-16T14:11:27.641232+00:00
- prompt_freeze: 2026-10-16T14:11:59.891137+00:00, set_exists=false, hearsay_rule_enabled=false, 해시 19개 파일
- set_freeze: 2026-10-16T14:15:21.157970+00:00, 시나리오 24편, 192턴

## 사전 점검
- P1 소문 규칙: 고위험 문장 1줄이 소문으로 바뀜 (아버지 숫돌이요, 이름 써 붙여 놨대요.) → 계획 기준(0줄) 미달 → 규칙 비활성화
- P2 승계 규칙 재생(M1P7 기록): 결정 일치 405 → 423 / 432, 승계 27/27 실제 주장 (설계 근거, 결과 아님)
- 단위 점검(가짜 kNN 판정 7줄): ALL_OK — 지시어/그+명사 승계 O, 물건 이름만 X, 전언 소문 → heard_rumor(함수 단위), 가족 전언 거래 주장 유지

## 확인 요청 사항
1. 계획 대비 이탈 여부(소문 규칙 비활성화는 계획 5절 P1 규칙에 따른 것)
2. analyze의 검정·판정 규칙이 사전등록 6~7절과 일치하는지
3. 기존 파일 비수정 여부
