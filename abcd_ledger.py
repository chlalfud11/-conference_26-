"""Ledger v2 for the ABCD run (.omo/plans/abcd-ledger-v2.md): a per-customer ledger built from ABCD scenario fields.

Usage: python abcd_ledger.py build <abcd_v1.1.json.gz> | sample <n>
"""
import ast
import gzip
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
SCEN = ROOT / "scenarios_abcd"
OUT = ROOT / "results" / "abcd" / "ledgers"
BRANDS = {"calvin klein": "calvin_klein", "guess": "guess", "michael kors": "michael_kors", "tommy hilfiger": "tommy_hilfiger"}
TYPES = ("boots", "jacket", "jeans", "shirt")


def named_item(text):
    low = text.lower()
    brand = next((v for k, v in BRANDS.items() if k in low), None)
    kind = next((t for t in TYPES if t in low), None)
    return f"{brand} {kind}" if brand and kind else None


def products(sc):
    raw = sc["order"].get("products") or "[]"
    items = ast.literal_eval(raw)
    return [(f"{p['brand']} {p['product_type']}", p["amount"]) for p in items]


def build_one(scenario, convo):
    sc = convo["scenario"]
    claim = scenario["turns"][-1]
    pred, verified = claim["truth_predicate"], claim["evidence"] == "verified"
    order = sc["order"]
    items = products(sc) or list(zip(sc["product"]["names"], sc["product"]["amounts"]))
    wanted = named_item(claim["player"])
    mismatch = bool(wanted) and wanted not in [n for n, _ in items]
    if wanted and mismatch:
        items = [(wanted, items[0][1] if items else 70)] + items[1:]
    total = sum(a for _, a in items)
    pdate = date.fromisoformat(order.get("purchase_date") or "2019-11-01")
    seed = int(hashlib.sha256(str(convo["convo_id"]).encode()).hexdigest(), 16)
    oid = order.get("order_id") or str(seed % 10**10)
    p = sc["personal"]
    status = "delivered"
    payments = [f"{pdate} charge ${total} order #{oid} ({order.get('payment_method', 'card')})"]
    extra = []
    if pred == "reserved_item":
        status = "shipped, not delivered" if verified else "delivered"
    if pred == "paid_deposit" and verified:
        payments.append(payments[0].replace(str(pdate), str(pdate)) + " [duplicate]")
    if pred == "completed_errand" and verified:
        extra.append(f"{pdate + timedelta(days=9)} return received for order #{oid}; refund pending")
    if pred == "promised_discount" and verified:
        code = "NG" + hashlib.sha256(f"promo{seed}".encode()).hexdigest()[:6].upper()
        extra.append(f"{pdate - timedelta(days=5)} promo code {code} issued to this account, 20% off, valid")
    orders = [] if (pred in ("reserved_item", "owns_item") and not verified) else [
        f"#{oid}  {pdate}  " + ", ".join(f"{n} ${a}" for n, a in items) + f"  total ${total}  status: {status}"]
    if not orders:
        payments = []
    rows = {
        "customer": f"{p['customer_name'].title()} | account {p.get('username') or p['customer_name'].replace(' ', '').lower()} | member: {p.get('member_level', 'guest')} | identity: VERIFIED at chat start (name + zip)",
        "orders": orders or ["(no orders on this account)"],
        "payments": payments or ["(none)"],
        "returns_promos": extra or ["(none)"],
    }
    text = ("[Ledger - Northgate Outfitters]\n"
            f"Customer on this chat: {rows['customer']}\nOrders:\n" + "\n".join("  " + r for r in rows["orders"])
            + "\nPayments:\n" + "\n".join("  " + r for r in rows["payments"])
            + "\nReturns / promo codes:\n" + "\n".join("  " + r for r in rows["returns_promos"]))
    return {"scenario_id": scenario["scenario_id"], "predicate": pred, "verified": verified,
            "item_mismatch_fixed": mismatch, "rows": rows}, text


def build(gz):
    convos = {c["convo_id"]: c for split in json.load(gzip.open(gz)).values() for c in split}
    OUT.mkdir(parents=True, exist_ok=True)
    n = mm = 0
    for path in sorted(SCEN.glob("*.json")):
        s = json.loads(path.read_text())
        meta, text = build_one(s, convos[s["source"]["convo_id"]])
        (OUT / f"{path.stem}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        (OUT / f"{path.stem}.txt").write_text(text + "\n")
        n += 1
        mm += meta["item_mismatch_fixed"]
    print(f"{n} ledgers, mismatch={mm}")


def sample(k):
    ids = sorted({p.stem[:-1] for p in OUT.glob("*.txt")})
    by_pred = {}
    for i in ids:
        by_pred.setdefault(json.loads((OUT / f"{i}v.json").read_text())["predicate"], i)
    md = ["# \uc7a5\ubd80 v2 \uac80\ud1a0\ud45c", "",
          "\uac19\uc740 \uc190\ub2d8 \ubb38\uc7a5\uc5d0 \ubd99\ub294 \ub450 \ubc84\uc804\uc758 \uc7a5\ubd80\ub2e4. v\ub294 \uc8fc\uc7a5\uc744 \ub4b7\ubc1b\uce68\ud558\ub294 \uae30\ub85d\uc774 \uc788\uace0, n\uc740 \uc190\ub2d8\uacfc \uc8fc\ubb38 \uc774\ub825\uc740 \uc788\uc9c0\ub9cc \uadf8 \uae30\ub85d\ub9cc \uc5c6\ub2e4.", ""]
    for pred, i in list(by_pred.items())[:k]:
        player = json.loads((SCEN / f"{i}v.json").read_text())["turns"][-1]["player"]
        md += [f"## {i} ({pred})", f"\uc190\ub2d8: {player}", "", "### v (\uae30\ub85d \uc788\uc74c)", "```", (OUT / f"{i}v.txt").read_text().rstrip(), "```",
               "### n (\uae30\ub85d \uc5c6\uc74c)", "```", (OUT / f"{i}n.txt").read_text().rstrip(), "```", ""]
    (ROOT / "results" / "abcd" / "ledger_review.md").write_text("\n".join(md))
    print("review written", len(by_pred))


OUT3 = ROOT / "results" / "abcd" / "ledgers_v3"
TODAY = date(2024, 6, 15)
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
       "eight": 8, "nine": 9, "ten": 10, "couple of": 2, "few": 3, "a few": 3}
REL = re.compile(r"\b(\d+|a few|couple of|few|an?|one|two|three|four|five|six|seven|eight|nine|ten)\s+(day|week|month)s?\s+ago\b|\b(yesterday|last week|last month|today)\b", re.I)


def days_ago(text):
    m = REL.search(text)
    if not m:
        return 3
    if m.group(3):
        return {"yesterday": 1, "last week": 7, "last month": 30, "today": 0}[m.group(3).lower()]
    n = m.group(1).lower()
    n = int(n) if n.isdigit() else NUM[n]
    return n * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]


def build3_one(scenario, convo):
    sc, claim = convo["scenario"], scenario["turns"][-1]
    pred, verified = claim["truth_predicate"], claim["evidence"] == "verified"
    items = products(sc) or list(zip(sc["product"]["names"], sc["product"]["amounts"]))
    wanted = named_item(claim["player"])
    if wanted and wanted not in [n for n, _ in items]:
        items = [(wanted, items[0][1] if items else 70)] + items[1:]
    total = sum(a for _, a in items)
    seed = int(hashlib.sha256(str(convo["convo_id"]).encode()).hexdigest(), 16)
    oid = sc["order"].get("order_id") or str(seed % 10**10)
    p = sc["personal"]
    who = f"{p['customer_name'].title()} ({p.get('username') or p['customer_name'].replace(' ', '').lower()})"
    d = days_ago(claim["player"])
    event = TODAY - timedelta(days=d)
    purchase = event if pred in ("reserved_item", "owns_item", "paid_deposit") else event - timedelta(days=7 if pred == "completed_errand" else -2)
    if pred == "promised_discount":
        purchase = event - timedelta(days=10)
    status = ("shipped, not delivered" if verified else None) if pred == "reserved_item" else "delivered"
    rows = []
    if status:
        rows.append(f"{purchase} | {who} | order #{oid} | " + ", ".join(f"{n} ${a}" for n, a in items) + f" | total ${total} | status: {status}")
        rows.append(f"{purchase} | {who} | charge ${total} for order #{oid} ({sc['order'].get('payment_method', 'card')})")
    if pred == "owns_item" and not verified:
        rows = []
    if pred == "paid_deposit" and verified:
        rows.append(f"{purchase} | {who} | charge ${total} for order #{oid} [duplicate of previous charge]")
    if pred == "completed_errand" and verified:
        rows.append(f"{event} | {who} | return received for order #{oid}; refund pending")
    if pred == "promised_discount" and verified:
        code = "NG" + hashlib.sha256(f"promo{seed}".encode()).hexdigest()[:6].upper()
        rows.append(f"{event} | {who} | promo code {code} issued, 20% off, valid until {TODAY + timedelta(days=30)}")
    header = (f"[Ledger - Northgate Outfitters]\nToday: {TODAY}\n"
              f"Customer on this chat: {who} | member: {p.get('member_level', 'guest')} | identity: VERIFIED at chat start (name + zip)")
    meta = {"scenario_id": scenario["scenario_id"], "predicate": pred, "verified": verified, "days_ago": d,
            "customer": who, "header": header, "rows": rows}
    text = header + "\nRecords for this customer:\n" + ("\n".join("  " + r for r in rows) or "  (none)")
    return meta, text


def build3(gz):
    convos = {c["convo_id"]: c for split in json.load(gzip.open(gz)).values() for c in split}
    OUT3.mkdir(parents=True, exist_ok=True)
    n = 0
    for path in sorted(SCEN.glob("*.json")):
        s = json.loads(path.read_text())
        meta, text = build3_one(s, convos[s["source"]["convo_id"]])
        (OUT3 / f"{path.stem}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
        (OUT3 / f"{path.stem}.txt").write_text(text + "\n")
        n += 1
    print(f"{n} v3 ledgers")


def sample3():
    md = ["# \uc7a5\ubd80 v3 \uac80\ud1a0\ud45c (\uc624\ub298 \ub0a0\uc9dc \ud3ec\ud568)", ""]
    for sid in ("A001", "A021", "A030", "A050", "A065"):
        player = json.loads((SCEN / f"{sid}v.json").read_text())["turns"][-1]["player"]
        md += [f"## {sid}", f"\uc190\ub2d8: {player}", "", "### v", "```", (OUT3 / f"{sid}v.txt").read_text().rstrip(), "```",
               "### n", "```", (OUT3 / f"{sid}n.txt").read_text().rstrip(), "```", ""]
    (ROOT / "results" / "abcd" / "ledger_review_v3.md").write_text("\n".join(md))
    print("review v3 written")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(sys.argv[2])
    elif cmd == "build3":
        build3(sys.argv[2])
    elif cmd == "sample3":
        sample3()
    else:
        sample(int(sys.argv[2]))
