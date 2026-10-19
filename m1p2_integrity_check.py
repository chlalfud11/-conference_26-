from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys

from npc import config


def main() -> int:
    subprocess.run(
        [sys.executable, "c6_fingerprint.py", "after_m1p2"],
        cwd=config.ROOT, env={**os.environ, "PYTHONHASHSEED": "0"}, check=True,
    )
    with (config.ROOT / "logs" / "c6_fingerprint_before_m1p2.json").open(encoding="utf-8") as handle:
        before = json.load(handle)
    with (config.ROOT / "logs" / "c6_fingerprint_after_m1p2.json").open(encoding="utf-8") as handle:
        after = json.load(handle)
    assert before == after
    print("D5 criteria fingerprint PASS", before["_ALL"])
    with (config.ROOT / "results" / "metrics_pre_m1p2.csv").open(encoding="utf-8") as handle:
        old_metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    with (config.ROOT / "results" / "metrics.csv").open(encoding="utf-8") as handle:
        new_metrics = {row["condition"]: row for row in csv.DictReader(handle)}
    for condition, old_row in old_metrics.items():
        assert old_row == new_metrics[condition], condition
    print("D5 all columns in original 5 conditions PASS")
    with (config.ROOT / "logs" / "m1p2_resume_integrity.json").open(encoding="utf-8") as handle:
        snapshot = json.load(handle)
    for path, expected in snapshot["source_sha256"].items():
        with (config.ROOT / path).open("rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        assert actual == expected, path
    with (config.ROOT / "logs" / "runs.jsonl").open("rb") as handle:
        prefix = b"".join(next(handle) for _ in range(270))
    assert hashlib.sha256(prefix).hexdigest() == snapshot["original_270_prefix_sha256"]
    print("D5 source unchanged since resumption; original 270-line prefix unchanged PASS")
    print("Scope: no historical pre-first-inference source snapshot; no proof of all historical edits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
