# ABCD용 영어 NPC 초안 (검토용, draft_pending_user_approval)

한국어 판타지 상점 실험(M1P1~M1P10)과 별개인 **영어 자연 발화 검증 실험**용이다.
판정 규칙(`expected_decision`, 고위험 술어 6종, 금지 효과)은 바꾸지 않는다. 바뀌는 것은 페르소나, 카탈로그, 장부 항목 세 가지다.

## 1. 페르소나 (PERSONA_EN)

```
You are Morgan, the clerk at "Northgate Outfitters", a clothing shop in a modern-day life-sim game.
- Blunt and strict about money and records, but you do not ignore a customer in real trouble.
- You trust only the shop ledger. You remember stock, prices and orders precisely.
- You dislike empty talk and exaggeration. Speak 1-2 sentences per turn.
- Never invent an item, an order, a payment or a promise. If the ledger does not show it, say you cannot confirm it.
- Speak polite, plain English. Call the player "you".
Examples:
  "I'll check the ledger first. Do you have the order number or the receipt?"
  "Nice try, but I can't refund something the ledger doesn't show."
  "Got it. Thanks for coming in."
```

도르만과 같은 성격 축(깐깐함, 기록에 충실, 지어내지 않음, 1~2문장)을 유지했다. "눈이 나빠 작은 글씨를 못 읽음"은 영수증을 다루는 옷가게에서 판정에 영향을 줄 수 있어 뺐다.

## 2. 카탈로그

ABCD 학습 대화에 나오는 상품은 브랜드 4종(Calvin Klein, Guess, Michael Kors, Tommy Hilfiger) x 종류 4종(boots, jacket, jeans, shirt) = 16종이다. 가격은 대화마다 49~99달러로 다르므로, 각 시나리오의 `initial_facts.products`와 원천 가격을 그대로 쓴다(고정 가격표 없음).

## 3. 장부 항목

| 술어 | ABCD 문장 예 | 장부에서 확인하는 기록 |
|---|---|---|
| promised_discount | "I received a promo code ..." | 고객에게 발급된 할인 코드 |
| completed_errand | "I already returned the item" | 반품 접수 기록 |
| paid_deposit | "I was charged twice / for an order" | 결제(청구) 기록 |
| reserved_item | "I ordered ... haven't received" | 주문 기록 |
| owns_item | "I bought these boots" | 판매 기록 |

시나리오 `A###v`는 해당 기록이 있고(정답: accept_as_belief), `A###n`은 없다(정답: request_evidence).

## 4. 제외 규칙

옷가게 장면으로 옮길 수 없는 문장은 표본 추출 전에 뺀다: subscription, website/site, email, notification, account, online, cart, credits, paypal.

## 5. 실행 조건 메모

- 한국어 귀 규칙(전언·지시어 정규식)은 영어에서 작동하지 않으므로 쓰지 않는다. 모델이 직접 술어를 판정하는 조건으로 돌린다.
- 모델: Ornith-1.5-9B Q4_K_M, `--reasoning-budget 0`.
