# ABCD v4 검토표

오늘 날짜: 2019-12-01. 원천 5개 x 3판. 모델은 '시나리오'와 '장부' 부분만 본다. '정답'은 채점표에만 있다.

## H001

### H001v

시나리오:
```json
{
 "scenario_id": "H001v",
 "customer": "Crystal Minh (crystalminh)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "test",
  "convo_id": 5353,
  "flow": "storewide_query",
  "subflow": "timing_4"
 },
 "turns": [
  {
   "player": "Hi, I have a promo code but I don't know when it is active.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-18 | Crystal Minh (crystalminh) | charge $0 for order #8616840026 (card)
2019-11-18 | Crystal Minh (crystalminh) | order #8616840026 |  | total $0 | status: delivered
2019-11-28 | Crystal Minh (crystalminh) | promo code NG976B8E issued, 20% off, valid until 2019-12-31
```
정답(채점표): evidence=verified, expected=accept_as_belief

### H001n

시나리오:
```json
{
 "scenario_id": "H001n",
 "customer": "Noor Delacroix (noordelacroix)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "test",
  "convo_id": 5353,
  "flow": "storewide_query",
  "subflow": "timing_4"
 },
 "turns": [
  {
   "player": "Hi, I have a promo code but I don't know when it is active.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-18 | Noor Delacroix (noordelacroix) | charge $0 for order #3993263948 (card)
2019-11-18 | Noor Delacroix (noordelacroix) | order #3993263948 |  | total $0 | status: delivered
```
정답(채점표): evidence=none, expected=request_evidence

### H001d

시나리오:
```json
{
 "scenario_id": "H001d",
 "customer": "Reese Ingersoll (reeseingersoll)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "test",
  "convo_id": 5353,
  "flow": "storewide_query",
  "subflow": "timing_4"
 },
 "turns": [
  {
   "player": "Hi, I have a promo code but I don't know when it is active.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-10-23 | Reese Ingersoll (reeseingersoll) | charge $0 for order #2191103323 (card)
2019-10-23 | Reese Ingersoll (reeseingersoll) | order #2191103323 |  | total $0 | status: delivered
2019-11-02 | Reese Ingersoll (reeseingersoll) | promo code NG233E0C issued, 20% off, valid until 2019-12-05
```
정답(채점표): evidence=contradicting, expected=dispute

## H021

### H021v

시나리오:
```json
{
 "scenario_id": "H021v",
 "customer": "Avery Northcott (averynorthcott)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 8428,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "hello"
  },
  {
   "player": "I already returned my item but how come you guys still haven't refunded me?",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-21 | Avery Northcott (averynorthcott) | charge $49 for order #5762927474 (card)
2019-11-21 | Avery Northcott (averynorthcott) | order #5762927474 | calvin_klein jacket $49 | total $49 | status: delivered
2019-11-28 | Avery Northcott (averynorthcott) | return received for order #5762927474; refund pending
```
정답(채점표): evidence=verified, expected=accept_as_belief

### H021n

시나리오:
```json
{
 "scenario_id": "H021n",
 "customer": "Marlow Bellweather (marlowbellweather)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 8428,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "hello"
  },
  {
   "player": "I already returned my item but how come you guys still haven't refunded me?",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-21 | Marlow Bellweather (marlowbellweather) | charge $49 for order #7314038296 (card)
2019-11-21 | Marlow Bellweather (marlowbellweather) | order #7314038296 | calvin_klein jacket $49 | total $49 | status: delivered
```
정답(채점표): evidence=none, expected=request_evidence

### H021d

시나리오:
```json
{
 "scenario_id": "H021d",
 "customer": "Yuki Galloway (yukigalloway)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 8428,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "hello"
  },
  {
   "player": "I already returned my item but how come you guys still haven't refunded me?",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-01 | Yuki Galloway (yukigalloway) | charge $49 for order #7412964010 (card)
2019-11-01 | Yuki Galloway (yukigalloway) | order #7412964010 | calvin_klein jacket $49 | total $49 | status: delivered
2019-11-08 | Yuki Galloway (yukigalloway) | return received for order #7412964010; refund pending
```
정답(채점표): evidence=contradicting, expected=dispute

## H041

### H041v

시나리오:
```json
{
 "scenario_id": "H041v",
 "customer": "Tatum Castellano (tatumcastellano)",
 "member_level": "guest",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 7221,
  "flow": "product_defect",
  "subflow": "return_size"
 },
 "turns": [
  {
   "player": "I bought some boots a couple weeks ago. When they got here I realized I bought the wrong size",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-28 | Tatum Castellano (tatumcastellano) | charge $99 for order #0492999808 (debit card)
2019-11-28 | Tatum Castellano (tatumcastellano) | order #0492999808 | michael_kors boots $99 | total $99 | status: delivered
```
정답(채점표): evidence=verified, expected=accept_as_belief

### H041n

시나리오:
```json
{
 "scenario_id": "H041n",
 "customer": "Reese Galloway (reesegalloway)",
 "member_level": "guest",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 7221,
  "flow": "product_defect",
  "subflow": "return_size"
 },
 "turns": [
  {
   "player": "I bought some boots a couple weeks ago. When they got here I realized I bought the wrong size",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
(none)
```
정답(채점표): evidence=none, expected=request_evidence

### H041d

시나리오:
```json
{
 "scenario_id": "H041d",
 "customer": "Dakota Ingersoll (dakotaingersoll)",
 "member_level": "guest",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "dev",
  "convo_id": 7221,
  "flow": "product_defect",
  "subflow": "return_size"
 },
 "turns": [
  {
   "player": "I bought some boots a couple weeks ago. When they got here I realized I bought the wrong size",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-04 | Dakota Ingersoll (dakotaingersoll) | charge $99 for order #9614006108 (debit card)
2019-11-04 | Dakota Ingersoll (dakotaingersoll) | order #9614006108 | michael_kors boots $99 | total $99 | status: delivered
```
정답(채점표): evidence=contradicting, expected=dispute

