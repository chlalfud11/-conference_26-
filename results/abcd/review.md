# ABCD 가공 데이터셋 검토표

후보 수(학습 8,034개 대화 중 규칙에 맞은 수): {'owns_item': 88, 'promised_discount': 92, 'paid_deposit': 40, 'reserved_item': 15, 'completed_errand': 9}

주장 유형마다 20개, 원천 84개 x 장부 2상태 = 시나리오 168개.
각 원천은 `A###v`(장부에 기록 있음 -> 받아들여야 함)와 `A###n`(기록 없음 -> 증거 요구해야 함) 두 파일이다.

검토할 것: 'claim' 칸 발화가 정말 그 주장 유형인지. 아니면 '판정' 칸에 X와 맞는 유형을 적어 주세요.

| id | 주장 유형 | convo | 인사 턴 | claim 발화 | 판정 |
|---|---|---|---|---|---|
| A001 | promised_discount | 748 |  | Hello! I received a promo code 8 days ago for these jeans I want to order and I can't get it to work. Can you help? | |
| A002 | promised_discount | 4467 | hello | i have a promo code and wanto know when i could use it to buy stuff? | |
| A003 | promised_discount | 9040 | Hi | i got a promo code that doesnt seem to be working | |
| A004 | promised_discount | 8959 |  | Hi I am having a problem with my promo code. I am trying to use it but it says it's invalid. | |
| A005 | promised_discount | 7067 |  | My promo code won't work. It keeps saying that it's invalid. | |
| A006 | promised_discount | 7080 |  | I have a promo code, but it doesn't seem to be working. | |
| A007 | promised_discount | 7691 |  | Hi I am having trouble using my promo code its saying invalid when it's not | |
| A008 | promised_discount | 9678 |  | Hello. I have an issue with my promo code | |
| A009 | promised_discount | 5968 |  | I am thinking of making a purchase, but I need to know if my promo code can be used. | |
| A010 | promised_discount | 2583 |  | i got a promo code only 2 days ago but it's coming up as invalid when I try to use it...what's happening? | |
| A011 | promised_discount | 5925 |  | Hello. I have a big issue with my promo code. I really, really want the discount! I never see deals like this | |
| A012 | promised_discount | 590 |  | My name is Norman Bouchard, and my promo code keeps coming up invalid, i just got it two days ago! | |
| A013 | promised_discount | 4543 |  | Hi! My promo code is saying it is invalid.  I just got it 2 days ago | |
| A014 | promised_discount | 3961 |  | I received a promo code just two days ago, and when I try to use it, it's already telling me that it's invalid. | |
| A015 | promised_discount | 5293 |  | Hey, can you help me? I have a promo code, but the darn thing says it's invalid! | |
| A016 | promised_discount | 5065 |  | I received a promo code 5 days ago and im trying to use It now but it being declared invalid | |
| A017 | promised_discount | 9078 |  | I received a promo code 5 days ago and I am trying to use it today and it's keeps telling me it's invalid | |
| A018 | promised_discount | 6398 |  | I trying to use my promo code but I am getting an invalid error | |
| A019 | promised_discount | 1760 |  | Hi, I'm trying to use my promo code but it says "invalid" | |
| A020 | promised_discount | 7041 |  | Hi! I received a promo code nine days ago, but when I try to enter it, I get a message saying it is invalid. | |
| A021 | completed_errand | 4492 |  | Yes. I've already returned it. But the charge has not been reversed on my billing statement. | |
| A022 | completed_errand | 7532 |  | I already returned the product, haven't received my credit. | |
| A023 | completed_errand | 9398 |  | My name is Rodriguez Domingo. I already returned this Calvin Klein shirt, but my billing statement shows that the charge never got reversed? | |
| A024 | completed_errand | 2021 |  | Hello, I didn't receive my money after I already returned the product. | |
| A025 | completed_errand | 3962 |  | I already returned the product, but I still didn't got my money back. | |
| A026 | completed_errand | 3366 |  | I already returned the item and the charge has not been reversed. | |
| A027 | completed_errand | 7990 |  | Well I already returned the item but for some reason I'm still getting billed for it | |
| A028 | completed_errand | 9299 |  | I already returned. | |
| A029 | completed_errand | 157 |  | I already returned it! | |
| A030 | paid_deposit | 3722 |  | I just got my bill and I was charged twice for something I bought | |
| A031 | paid_deposit | 3133 |  | HI there, I was charged twice for an item I bought | |
| A032 | paid_deposit | 7570 |  | I wanna dispute my bill cause I was charged twice | |
| A033 | paid_deposit | 5936 |  | and it looks like you guys charged me twice! | |
| A034 | paid_deposit | 3482 |  | Hi, I think I have been charged twice for an item I bought. | |
| A035 | paid_deposit | 3287 |  | I got charged 178 dollars, while I only paid for 1 jeans. I got double charged. | |
| A036 | paid_deposit | 2608 |  | i am very upset I got charged twice for the Michael Kors boots I just bought! | |
| A037 | paid_deposit | 3441 |  | I just got my bill, and I got charged twice for one of my items. | |
| A038 | paid_deposit | 7841 | Hello! | They acutally charged me twice | |
| A039 | paid_deposit | 2615 |  | HI! I just got my bill in the mail and I have been charged twice for something I brought | |
| A040 | paid_deposit | 118 |  | Hi there. It's Alessandro Phoenix here. I received my bill today and see that I was charged twice a coat that I bought for my wife last month | |
| A041 | paid_deposit | 7811 | Hello | and I was looking at my bill and noticed that I was charged twice. | |
| A042 | paid_deposit | 410 |  | I want to dispute my bill because I was charged twice | |
| A043 | paid_deposit | 4398 |  | I got charged twice for this jacket.  And I pay good money for the Gold level to have an incident like this | |
| A044 | paid_deposit | 1160 | Hi | I was charged twice for a purchase and I don't know why | |
| A045 | paid_deposit | 2164 |  | i have been charged twice for something that i brought. i would like to dispute this. | |
| A046 | paid_deposit | 2422 |  | Yes, I ordered some jeans the other day, and it looks like I was charged twice on my bill. | |
| A047 | paid_deposit | 2744 |  | Hello there!  I am asking about my bill.  I think I got charged twice for my order and I want to make sure I only get charged one time. | |
| A048 | paid_deposit | 1744 |  | I was charged twice for something I bought. | |
| A049 | paid_deposit | 2980 |  | Hi.  My name is Joyce Wu.  My Order ID is 1495528470.  I recently purchased guess jeans for $89 but I was charged twice.  Can you fix this? | |
| A050 | reserved_item | 7284 |  | Hi. I wanted to check the shipping status of my order. I ordered it nine days ago, and haven't received it. | |
| A051 | reserved_item | 450 |  | I ordered this jacket over a month ago and I still haven't received it. | |
| A052 | reserved_item | 4265 |  | I'm starting to get concerned about an item I ordered 9 days ago that still hasn't arrived | |
| A053 | reserved_item | 5156 |  | Hi, I placed an order 9 days ago and I still haven't received my package. I was wondering if you could resend it. | |
| A054 | reserved_item | 10168 |  | HI! I ordered a shirt on November 2019 but it never came | |
| A055 | reserved_item | 4124 |  | I ordered a package nine days ago and never received it. Could you please check on the shipping status? | |
| A056 | reserved_item | 4007 |  | Hi! I ordered a Guess T-shirt but it never came. Can you check the shipping status and where it is now? | |
| A057 | reserved_item | 6843 |  | Hello, I ordered something a while ago and it never arrived and I was hoping to figure out what's going on. | |
| A058 | reserved_item | 9195 |  | I am looking for my order?  I ordered it 9 days ago and still haven't received it yet. | |
| A059 | reserved_item | 176 |  | I ordered something a while ago, but I haven't gotten the package yet | |
| A060 | reserved_item | 695 |  | Hi. I placed an order a while ago, but haven't received my package yet. | |
| A061 | reserved_item | 245 |  | hi. I placed an order three weeks ago and I have not received it. I would like to know where my order is. | |
| A062 | reserved_item | 6046 |  | HI.  My name is Albert Sanders.  My order ID is 8409534174.  I ordered this Tommy Hilfiger shirt for $74 9 days ago, and still have not received it.  What is the status of my order? | |
| A063 | reserved_item | 6907 |  | I ordered this jacket a long time ago and my package never arrived. What is going on??? | |
| A064 | reserved_item | 9833 |  | I ordered a package on 09/08/2019 and never received it | |
| A065 | owns_item | 3656 |  | Well, I bought a Michael Kors jacket and spilled wine all over it! Do you know how to remove a stain from that jacket? | |
| A066 | owns_item | 985 |  | i bought this shirt for my boyfriend but he is apparently too fat | |
| A067 | owns_item | 5493 |  | I bought these Michael Kors boots from you. I though that they would be great, but just changed my mind. I don't want them anymore | |
| A068 | owns_item | 7174 | Hello | I bought these Calvin Klein boots in brown. I thought that the brown would look good, but I've changed my mind | |
| A069 | owns_item | 625 |  | Hi, I need some help with a return item as I bought the wrong color. | |
| A070 | owns_item | 1361 |  | I bought a couple of items for my wife but I would like to remove one item from the order since my wife did not like it | |
| A071 | owns_item | 3715 |  | I purchased the jacket once, but I was billed for it twice. | |
| A072 | owns_item | 3949 |  | i bought these boots but changed my mind on them | |
| A073 | owns_item | 4465 |  | Hi, so I bought these boots and I was checking on the order and it looks like I was charged an extra fee.  Can you check that for me? | |
| A074 | owns_item | 2656 |  | yes it says i bought a calvin klein shrt but i did not | |
| A075 | owns_item | 6715 |  | Hello... I bought a pair of boots yesterday but today... the boots are having a 50% discount.. | |
| A076 | owns_item | 4572 |  | I purchased a pair of jeans for $64. When they arrived, they did have a stain on them. I need some information on how to go about returning them | |
| A077 | owns_item | 3166 |  | Hi, I purchased a jacket to go skiing and it is the wrong size.  What steps do I need to take to return it? | |
| A078 | owns_item | 6097 |  | Hi, I bought this Guess jacket and I think I want to return it | |
| A079 | owns_item | 1025 |  | Hi I bought this Guess shirt which was an awesome buy. However, what I thought was an awesome deal ended up being closer to a rip off, as my local Target has something cheaper | |
| A080 | owns_item | 7437 |  | Hi, I would like to return an item. I thought I purchased a navy blue jacket, but I received a black one. | |
| A081 | owns_item | 10035 |  | I bought the wrong size and need to return an item | |
| A082 | owns_item | 5558 |  | I got this jacket for my wide. I thought that it loved great! But she's so picky. She hates it. Can you help me fix it? | |
| A083 | owns_item | 10200 |  | I bought a lot of clothes for my wife and she's really picky, so I might have to return some of them | |
| A084 | owns_item | 4706 |  | Hello. I bought an item with you guys. But after placing it, I realized I no longer need the item. | |
