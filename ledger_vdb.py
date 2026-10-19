"""Shop-wide ledger vector store (.omo/plans/abcd-ledger-v3-vdb.md): bge-m3 embeddings in a JSON file.

Usage: python ledger_vdb.py build    (needs the 8081 embedding server)
"""
import json
import math
import sys
from pathlib import Path

from npc import llm

ROOT = Path(__file__).parent
SRC = ROOT / "results" / "abcd" / "ledgers_v3"
OUT = ROOT / "results" / "abcd" / "ledger_vdb"
_CACHE = {}


def unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for version in "vn":
        rows = []
        for path in sorted(SRC.glob(f"*{version}.json")):
            meta = json.loads(path.read_text())
            rows += [{"id": f"{meta['scenario_id']}#{i}", "customer": meta["customer"], "text": r}
                     for i, r in enumerate(meta["rows"])]
        texts = [r["text"] for r in rows]
        vecs = [unit(v) for i in range(0, len(texts), 32) for v in llm.embed(texts[i:i + 32])]
        for r, v in zip(rows, vecs):
            r["vec"] = v
        (OUT / f"store_{version}.json").write_text(json.dumps(rows))
        print(version, len(rows), len(vecs[0]))


def search(query, version, k=5):
    if version not in _CACHE:
        _CACHE[version] = json.loads((OUT / f"store_{version}.json").read_text())
    rows = _CACHE[version]
    q = unit(llm.embed([query])[0])
    scored = sorted(rows, key=lambda r: -sum(a * b for a, b in zip(q, r["vec"])))
    return [{k2: v for k2, v in r.items() if k2 != "vec"} for r in scored[:k]]


if __name__ == "__main__":
    {"build": build}[sys.argv[1]]()
