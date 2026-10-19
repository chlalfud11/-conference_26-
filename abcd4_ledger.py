"""One shop ledger for ABCD v4 (.omo/plans/abcd-v4-answer-key.md): CSV rows, rendering, engine lookup.

The lookup is what the game engine knows: it reads the shop ledger only, never the answer key.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
DIR = ROOT / "ledger_abcd4"
FIELDS = ("date", "customer", "account", "event", "order_id", "items", "amount", "note")
CLAIM_EVENT = {"reserved_item": "order", "owns_item": "order", "paid_deposit": "duplicate_charge",
               "completed_errand": "return", "promised_discount": "promo"}
WHO = re.compile(r"^(.*) \((.*)\)$")
BODY = [
    ("order", re.compile(r"^order #(?P<order_id>\d+) \| (?P<items>.*) \| total \$(?P<amount>\d+) \| status: (?P<note>.+)$")),
    ("duplicate_charge", re.compile(r"^charge \$(?P<amount>\d+) for order #(?P<order_id>\d+) \[duplicate of previous charge\]$")),
    ("charge", re.compile(r"^charge \$(?P<amount>\d+) for order #(?P<order_id>\d+) \((?P<note>[^)]*)\)$")),
    ("return", re.compile(r"^return received for order #(?P<order_id>\d+); (?P<note>.+)$")),
    ("promo", re.compile(r"^promo code (?P<items>\S+) issued, (?P<note>.+)$")),
]


def split_who(who):
    return WHO.match(who).groups()


def parse(text):
    day, who, body = text.split(" | ", 2)
    name, account = split_who(who)
    for event, pattern in BODY:
        m = pattern.match(body)
        if m:
            row = {k: "" for k in FIELDS} | {"date": day, "customer": name, "account": account, "event": event}
            row.update({k: v for k, v in m.groupdict().items() if v is not None})
            return row
    raise ValueError(f"unparsed ledger row: {text}")


def render(r):
    body = {
        "order": f"order #{r['order_id']} | {r['items']} | total ${r['amount']} | status: {r['note']}",
        "duplicate_charge": f"charge ${r['amount']} for order #{r['order_id']} [duplicate of previous charge]",
        "charge": f"charge ${r['amount']} for order #{r['order_id']} ({r['note']})",
        "return": f"return received for order #{r['order_id']}; {r['note']}",
        "promo": f"promo code {r['items']} issued, {r['note']}",
    }[r["event"]]
    return f"{r['date']} | {r['customer']} ({r['account']}) | {body}"


def matches(predicate, r):
    if CLAIM_EVENT.get(predicate) != r["event"]:
        return False
    return predicate != "reserved_item" or r["note"].startswith("shipped, not delivered")


def lookup(rows, account, predicate, stated_date):
    """Engine evidence for a claim: none / verified (a matching record on the stated date) / contradicting."""
    hits = [r for r in rows if r["account"] == account and matches(predicate, r)]
    if not hits:
        return "none"
    if stated_date is None or any(r["date"] == stated_date for r in hits):
        return "verified"
    return "contradicting"


def write(rows, today):
    DIR.mkdir(parents=True, exist_ok=True)
    with (DIR / "shop_ledger.csv").open("w", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    (DIR / "meta.json").write_text(json.dumps({"today": today}, indent=1) + "\n")


def load():
    with (DIR / "shop_ledger.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows, json.loads((DIR / "meta.json").read_text())["today"]
