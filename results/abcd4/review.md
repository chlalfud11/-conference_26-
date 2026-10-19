# ABCD v4 검토표

오늘 날짜: 2019-12-01. 원천 5개 x 3판. 모델은 '시나리오'와 '장부' 부분만 본다. '정답'은 채점표에만 있다.

## A001

### A001v

시나리오:
```json
{
 "scenario_id": "A001v",
 "customer": "Crystal Minh (cm547970)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 748,
  "flow": "purchase_dispute",
  "subflow": "promo_code_invalid"
 },
 "turns": [
  {
   "player": "Hello! I received a promo code 8 days ago for these jeans I want to order and I can't get it to work. Can you help?",
   "date": "2019-11-23"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-13 | Crystal Minh (cm547970) | charge $99 for order #6176415771 (card)
2019-11-13 | Crystal Minh (cm547970) | order #6176415771 | guess jeans $99 | total $99 | status: delivered
2019-11-23 | Crystal Minh (cm547970) | promo code NG2C8D3D issued, 20% off, valid until 2019-12-31
```
정답(채점표): evidence=verified, expected=accept_as_belief

### A001n

시나리오:
```json
{
 "scenario_id": "A001n",
 "customer": "Noor Delacroix (noordelacroix)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 748,
  "flow": "purchase_dispute",
  "subflow": "promo_code_invalid"
 },
 "turns": [
  {
   "player": "Hello! I received a promo code 8 days ago for these jeans I want to order and I can't get it to work. Can you help?",
   "date": "2019-11-23"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-13 | Noor Delacroix (noordelacroix) | charge $99 for order #3770127578 (card)
2019-11-13 | Noor Delacroix (noordelacroix) | order #3770127578 | guess jeans $99 | total $99 | status: delivered
```
정답(채점표): evidence=none, expected=request_evidence

### A001d

시나리오:
```json
{
 "scenario_id": "A001d",
 "customer": "Reese Ingersoll (reeseingersoll)",
 "member_level": "bronze",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 748,
  "flow": "purchase_dispute",
  "subflow": "promo_code_invalid"
 },
 "turns": [
  {
   "player": "Hello! I received a promo code 8 days ago for these jeans I want to order and I can't get it to work. Can you help?",
   "date": "2019-11-23"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-10-18 | Reese Ingersoll (reeseingersoll) | charge $99 for order #1519786732 (card)
2019-10-18 | Reese Ingersoll (reeseingersoll) | order #1519786732 | guess jeans $99 | total $99 | status: delivered
2019-10-28 | Reese Ingersoll (reeseingersoll) | promo code NG2607B1 issued, 20% off, valid until 2019-12-05
```
정답(채점표): evidence=contradicting, expected=dispute

## A021

### A021v

시나리오:
```json
{
 "scenario_id": "A021v",
 "customer": "David Williams (davidw92)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 4492,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "Yes. I've already returned it. But the charge has not been reversed on my billing statement.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-21 | David Williams (davidw92) | charge $64 for order #2677384367 (card)
2019-11-21 | David Williams (davidw92) | order #2677384367 | calvin_klein shirt $64 | total $64 | status: delivered
2019-11-28 | David Williams (davidw92) | return received for order #2677384367; refund pending
```
정답(채점표): evidence=verified, expected=accept_as_belief

### A021n

시나리오:
```json
{
 "scenario_id": "A021n",
 "customer": "Avery Northcott (averynorthcott)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 4492,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "Yes. I've already returned it. But the charge has not been reversed on my billing statement.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-21 | Avery Northcott (averynorthcott) | charge $64 for order #8067121900 (card)
2019-11-21 | Avery Northcott (averynorthcott) | order #8067121900 | calvin_klein shirt $64 | total $64 | status: delivered
```
정답(채점표): evidence=none, expected=request_evidence

### A021d

시나리오:
```json
{
 "scenario_id": "A021d",
 "customer": "Marlow Bellweather (marlowbellweather)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 4492,
  "flow": "purchase_dispute",
  "subflow": "mistimed_billing_already_returned"
 },
 "turns": [
  {
   "player": "Yes. I've already returned it. But the charge has not been reversed on my billing statement.",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-01 | Marlow Bellweather (marlowbellweather) | charge $64 for order #1719544736 (card)
2019-11-01 | Marlow Bellweather (marlowbellweather) | order #1719544736 | calvin_klein shirt $64 | total $64 | status: delivered
2019-11-08 | Marlow Bellweather (marlowbellweather) | return received for order #1719544736; refund pending
```
정답(채점표): evidence=contradicting, expected=dispute

## A030

### A030v

시나리오:
```json
{
 "scenario_id": "A030v",
 "customer": "Cameron Jaworski (cameronjaworski)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3722,
  "flow": "subscription_inquiry",
  "subflow": "manage_dispute_bill"
 },
 "turns": [
  {
   "player": "I just got my bill and I was charged twice for something I bought",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-28 | Cameron Jaworski (cameronjaworski) | charge $89 for order #1448069994 (card)
2019-11-28 | Cameron Jaworski (cameronjaworski) | charge $89 for order #1448069994 [duplicate of previous charge]
2019-11-28 | Cameron Jaworski (cameronjaworski) | order #1448069994 | michael_kors jacket $89 | total $89 | status: delivered
```
정답(채점표): evidence=verified, expected=accept_as_belief

### A030n

시나리오:
```json
{
 "scenario_id": "A030n",
 "customer": "Sasha Pemberton (sashapemberton)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3722,
  "flow": "subscription_inquiry",
  "subflow": "manage_dispute_bill"
 },
 "turns": [
  {
   "player": "I just got my bill and I was charged twice for something I bought",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-28 | Sasha Pemberton (sashapemberton) | charge $89 for order #2187265988 (card)
2019-11-28 | Sasha Pemberton (sashapemberton) | order #2187265988 | michael_kors jacket $89 | total $89 | status: delivered
```
정답(채점표): evidence=none, expected=request_evidence

### A030d

시나리오:
```json
{
 "scenario_id": "A030d",
 "customer": "Gray Pemberton (graypemberton)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3722,
  "flow": "subscription_inquiry",
  "subflow": "manage_dispute_bill"
 },
 "turns": [
  {
   "player": "I just got my bill and I was charged twice for something I bought",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-08 | Gray Pemberton (graypemberton) | charge $89 for order #9229409494 (card)
2019-11-08 | Gray Pemberton (graypemberton) | charge $89 for order #9229409494 [duplicate of previous charge]
2019-11-08 | Gray Pemberton (graypemberton) | order #9229409494 | michael_kors jacket $89 | total $89 | status: delivered
```
정답(채점표): evidence=contradicting, expected=dispute

## A050

### A050v

시나리오:
```json
{
 "scenario_id": "A050v",
 "customer": "Parker Galloway (parkergalloway)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 7284,
  "flow": "shipping_issue",
  "subflow": "missing"
 },
 "turns": [
  {
   "player": "Hi. I wanted to check the shipping status of my order. I ordered it nine days ago, and haven't received it.",
   "date": "2019-11-22"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-22 | Parker Galloway (parkergalloway) | charge $128 for order #3419928139 (card)
2019-11-22 | Parker Galloway (parkergalloway) | order #3419928139 | michael_kors jeans $49, guess boots $79 | total $128 | status: shipped, not delivered
```
정답(채점표): evidence=verified, expected=accept_as_belief

### A050n

시나리오:
```json
{
 "scenario_id": "A050n",
 "customer": "Quinn Kingsley (quinnkingsley)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 7284,
  "flow": "shipping_issue",
  "subflow": "missing"
 },
 "turns": [
  {
   "player": "Hi. I wanted to check the shipping status of my order. I ordered it nine days ago, and haven't received it.",
   "date": "2019-11-22"
  }
 ]
}
```
장부(이 손님의 줄):
```
(none)
```
정답(채점표): evidence=none, expected=request_evidence

### A050d

시나리오:
```json
{
 "scenario_id": "A050d",
 "customer": "Yuki Okonkwo (yukiokonkwo)",
 "member_level": "silver",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 7284,
  "flow": "shipping_issue",
  "subflow": "missing"
 },
 "turns": [
  {
   "player": "Hi. I wanted to check the shipping status of my order. I ordered it nine days ago, and haven't received it.",
   "date": "2019-11-22"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-10-28 | Yuki Okonkwo (yukiokonkwo) | charge $128 for order #5332448694 (card)
2019-10-28 | Yuki Okonkwo (yukiokonkwo) | order #5332448694 | michael_kors jeans $49, guess boots $79 | total $128 | status: shipped, not delivered
```
정답(채점표): evidence=contradicting, expected=dispute

## A065

### A065v

시나리오:
```json
{
 "scenario_id": "A065v",
 "customer": "Sasha Fairbanks (sashafairbanks)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3656,
  "flow": "single_item_query",
  "subflow": "jacket_how_1"
 },
 "turns": [
  {
   "player": "Well, I bought a Michael Kors jacket and spilled wine all over it! Do you know how to remove a stain from that jacket?",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-28 | Sasha Fairbanks (sashafairbanks) | charge $79 for order #2651164237 (card)
2019-11-28 | Sasha Fairbanks (sashafairbanks) | order #2651164237 | michael_kors jacket $79 | total $79 | status: delivered
```
정답(채점표): evidence=verified, expected=accept_as_belief

### A065n

시나리오:
```json
{
 "scenario_id": "A065n",
 "customer": "Reese Hargrove (reesehargrove)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3656,
  "flow": "single_item_query",
  "subflow": "jacket_how_1"
 },
 "turns": [
  {
   "player": "Well, I bought a Michael Kors jacket and spilled wine all over it! Do you know how to remove a stain from that jacket?",
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

### A065d

시나리오:
```json
{
 "scenario_id": "A065d",
 "customer": "Quinn Fairbanks (quinnfairbanks)",
 "member_level": "gold",
 "trust": 2,
 "source": {
  "dataset": "ABCD v1.1 (MIT)",
  "split": "train",
  "convo_id": 3656,
  "flow": "single_item_query",
  "subflow": "jacket_how_1"
 },
 "turns": [
  {
   "player": "Well, I bought a Michael Kors jacket and spilled wine all over it! Do you know how to remove a stain from that jacket?",
   "date": "2019-11-28"
  }
 ]
}
```
장부(이 손님의 줄):
```
2019-11-01 | Quinn Fairbanks (quinnfairbanks) | charge $79 for order #0173456978 (card)
2019-11-01 | Quinn Fairbanks (quinnfairbanks) | order #0173456978 | michael_kors jacket $79 | total $79 | status: delivered
```
정답(채점표): evidence=contradicting, expected=dispute

