# 장부 v2 검토표

같은 손님 문장에 붙는 두 버전의 장부다. v는 주장을 뒷받침하는 기록이 있고, n은 손님과 주문 이력은 있지만 그 기록만 없다.

## A001 (promised_discount)
손님: Hello! I received a promo code 8 days ago for these jeans I want to order and I can't get it to work. Can you help?

### v (기록 있음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Crystal Minh | account cm547970 | member: bronze | identity: VERIFIED at chat start (name + zip)
Orders:
  #6176415771  2019-11-01  guess jeans $99  total $99  status: delivered
Payments:
  2019-11-01 charge $99 order #6176415771 (card)
Returns / promo codes:
  2019-10-27 promo code NG2C8D3D issued to this account, 20% off, valid
```
### n (기록 없음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Crystal Minh | account cm547970 | member: bronze | identity: VERIFIED at chat start (name + zip)
Orders:
  #6176415771  2019-11-01  guess jeans $99  total $99  status: delivered
Payments:
  2019-11-01 charge $99 order #6176415771 (card)
Returns / promo codes:
  (none)
```

## A021 (completed_errand)
손님: Yes. I've already returned it. But the charge has not been reversed on my billing statement.

### v (기록 있음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: David Williams | account davidw92 | member: silver | identity: VERIFIED at chat start (name + zip)
Orders:
  #2677384367  2019-11-01  calvin_klein shirt $64  total $64  status: delivered
Payments:
  2019-11-01 charge $64 order #2677384367 (card)
Returns / promo codes:
  2019-11-10 return received for order #2677384367; refund pending
```
### n (기록 없음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: David Williams | account davidw92 | member: silver | identity: VERIFIED at chat start (name + zip)
Orders:
  #2677384367  2019-11-01  calvin_klein shirt $64  total $64  status: delivered
Payments:
  2019-11-01 charge $64 order #2677384367 (card)
Returns / promo codes:
  (none)
```

## A030 (paid_deposit)
손님: I just got my bill and I was charged twice for something I bought

### v (기록 있음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: David Williams | account davidwilliams | member: gold | identity: VERIFIED at chat start (name + zip)
Orders:
  #1448069994  2019-11-01  michael_kors jacket $89  total $89  status: delivered
Payments:
  2019-11-01 charge $89 order #1448069994 (card)
  2019-11-01 charge $89 order #1448069994 (card) [duplicate]
Returns / promo codes:
  (none)
```
### n (기록 없음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: David Williams | account davidwilliams | member: gold | identity: VERIFIED at chat start (name + zip)
Orders:
  #1448069994  2019-11-01  michael_kors jacket $89  total $89  status: delivered
Payments:
  2019-11-01 charge $89 order #1448069994 (card)
Returns / promo codes:
  (none)
```

## A050 (reserved_item)
손님: Hi. I wanted to check the shipping status of my order. I ordered it nine days ago, and haven't received it.

### v (기록 있음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Albert Sanders | account albertsanders766 | member: silver | identity: VERIFIED at chat start (name + zip)
Orders:
  #3419928139  2020-03-17  michael_kors jeans $49, guess boots $79  total $128  status: shipped, not delivered
Payments:
  2020-03-17 charge $128 order #3419928139 (card)
Returns / promo codes:
  (none)
```
### n (기록 없음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Albert Sanders | account albertsanders766 | member: silver | identity: VERIFIED at chat start (name + zip)
Orders:
  (no orders on this account)
Payments:
  (none)
Returns / promo codes:
  (none)
```

## A065 (owns_item)
손님: Well, I bought a Michael Kors jacket and spilled wine all over it! Do you know how to remove a stain from that jacket?

### v (기록 있음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Chloe Zhang | account chloezhang | member: gold | identity: VERIFIED at chat start (name + zip)
Orders:
  #2651164237  2019-11-01  michael_kors jacket $79  total $79  status: delivered
Payments:
  2019-11-01 charge $79 order #2651164237 (card)
Returns / promo codes:
  (none)
```
### n (기록 없음)
```
[Ledger - Northgate Outfitters]
Customer on this chat: Chloe Zhang | account chloezhang | member: gold | identity: VERIFIED at chat start (name + zip)
Orders:
  (no orders on this account)
Payments:
  (none)
Returns / promo codes:
  (none)
```
