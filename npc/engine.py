from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS world_meta (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS world_truth (
    fact_id    TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'game_engine'
               CHECK (source = 'game_engine'),
    updated_at TEXT NOT NULL,
    version    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS committed_event (
    event_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id              INTEGER NOT NULL,
    event_type           TEXT NOT NULL,
    payload              TEXT NOT NULL,
    source               TEXT NOT NULL,
    world_version_before INTEGER NOT NULL,
    world_version_after  INTEGER NOT NULL,
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_claim (
    claim_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id    INTEGER NOT NULL,
    raw_text   TEXT NOT NULL,
    predicate  TEXT NOT NULL,
    object     TEXT NOT NULL DEFAULT '',
    risk       TEXT NOT NULL CHECK (risk IN ('high_risk', 'low_risk')),
    evidence   TEXT NOT NULL CHECK (evidence IN ('verified', 'none', 'contradicting')),
    status     TEXT NOT NULL DEFAULT 'unverified',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claim_decision (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id     INTEGER NOT NULL,
    claim_id    INTEGER NOT NULL REFERENCES player_claim(claim_id),
    decision    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    rationale   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS npc_belief (
    belief_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id       INTEGER NOT NULL,
    claim_id      INTEGER NOT NULL REFERENCES player_claim(claim_id),
    predicate     TEXT NOT NULL,
    object        TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL,
    accepted_by   TEXT NOT NULL,
    superseded_by INTEGER,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_text (
    gen_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id         INTEGER NOT NULL,
    utterance       TEXT NOT NULL,
    memory_eligible INTEGER NOT NULL DEFAULT 0 CHECK (memory_eligible = 0),
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS engine_refusal (
    refusal_id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id    INTEGER NOT NULL,
    skill      TEXT NOT NULL,
    args       TEXT NOT NULL,
    reason     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

BELIEF_CONFIDENCE = 0.65


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PreconditionFailed(Exception):
    pass


@dataclass(frozen=True)
class SkillResult:
    skill: str
    ok: bool
    reason: str = ""
    payload: dict = field(default_factory=dict)


class GameEngine:
    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.reset()

    @contextmanager
    def _tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def reset(self, extra_facts: dict[str, int] | None = None) -> None:
        with self._tx():
            for table in (
                "world_truth", "committed_event", "player_claim",
                "claim_decision", "npc_belief", "generated_text", "engine_refusal",
            ):
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.execute(
                "INSERT OR REPLACE INTO world_meta (id, version) VALUES (1, 0)"
            )
            facts = {"player.gold": config.INITIAL_GOLD}
            for item, qty in config.INITIAL_STOCK.items():
                facts[f"shop.stock.{item}"] = qty
                facts[f"shop.reserved.{item}"] = 0
                facts[f"player.inventory.{item}"] = 0
            facts.update(extra_facts or {})
            for fact_id, value in facts.items():
                self._write_fact(fact_id, value)

    def _write_fact(self, fact_id: str, value) -> None:
        version = self.version() + 1
        self.conn.execute("UPDATE world_meta SET version = ? WHERE id = 1", (version,))
        self.conn.execute(
            "INSERT INTO world_truth (fact_id, value, source, updated_at, version) "
            "VALUES (?, ?, 'game_engine', ?, ?) "
            "ON CONFLICT(fact_id) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, version=excluded.version",
            (fact_id, json.dumps(value, ensure_ascii=False), _now(), version),
        )

    def version(self) -> int:
        row = self.conn.execute("SELECT version FROM world_meta WHERE id = 1").fetchone()
        return row["version"] if row else 0

    def fact(self, fact_id: str, default=0):
        row = self.conn.execute(
            "SELECT value FROM world_truth WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        return json.loads(row["value"]) if row else default

    def world(self) -> dict:
        return {
            r["fact_id"]: json.loads(r["value"])
            for r in self.conn.execute("SELECT fact_id, value FROM world_truth")
        }

    def available_stock(self, item: str) -> int:
        return self.fact(f"shop.stock.{item}") - self.fact(f"shop.reserved.{item}")

    def _record_event(self, turn_id: int, event_type: str, payload: dict,
                      source: str, v0: int, v1: int) -> None:
        self.conn.execute(
            "INSERT INTO committed_event (turn_id, event_type, payload, source, "
            "world_version_before, world_version_after, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (turn_id, event_type, json.dumps(payload, ensure_ascii=False),
             source, v0, v1, _now()),
        )

    def _record_refusal(self, turn_id: int, skill: str, args: dict, reason: str) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO engine_refusal (turn_id, skill, args, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (turn_id, skill, json.dumps(args, ensure_ascii=False), reason, _now()),
            )

    def buy(self, turn_id: int, item: str, quantity: int) -> SkillResult:
        args = {"item": item, "quantity": quantity}
        try:
            if item not in config.PRICES:
                raise PreconditionFailed("unknown_item")
            if not isinstance(quantity, int) or quantity < 1:
                raise PreconditionFailed("invalid_quantity")
            price = config.PRICES[item]
            total = price * quantity
            with self._tx():
                gold = self.fact("player.gold")
                on_hand = self.fact(f"shop.stock.{item}")
                reserved = self.fact(f"shop.reserved.{item}")
                if gold < total:
                    raise PreconditionFailed("insufficient_gold")
                if on_hand - reserved < quantity:
                    raise PreconditionFailed("insufficient_stock")
                v0 = self.version()
                self._write_fact("player.gold", gold - total)
                self._write_fact(f"shop.stock.{item}", on_hand - quantity)
                self._write_fact(
                    f"player.inventory.{item}",
                    self.fact(f"player.inventory.{item}") + quantity,
                )
                self._record_event(
                    turn_id, "purchase_completed",
                    {"item": item, "quantity": quantity, "total_price": total},
                    "buy_skill", v0, self.version(),
                )
        except PreconditionFailed as exc:
            self._record_refusal(turn_id, "buy", args, str(exc))
            return SkillResult("buy", False, str(exc), args)
        return SkillResult("buy", True, "", {**args, "total_price": total})

    def save_claim(self, turn_id: int, raw_text: str, predicate: str,
                   object_: str, evidence: str) -> int:
        risk = config.risk_of(predicate)
        with self._tx():
            cur = self.conn.execute(
                "INSERT INTO player_claim (turn_id, raw_text, predicate, object, "
                "risk, evidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'unverified', ?)",
                (turn_id, raw_text, predicate, object_, risk, evidence, _now()),
            )
        return int(cur.lastrowid)

    def record_decision(self, turn_id: int, claim_id: int, decision: str,
                        actor: str, rationale: str = "") -> int | None:
        row = self.conn.execute(
            "SELECT predicate, object FROM player_claim WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        if row is None:
            raise PreconditionFailed("unknown_claim")
        belief_id = None
        with self._tx():
            self.conn.execute(
                "INSERT INTO claim_decision (turn_id, claim_id, decision, actor, "
                "rationale, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (turn_id, claim_id, decision, actor, rationale, _now()),
            )
            if decision == "accept_as_belief":
                cur = self.conn.execute(
                    "INSERT INTO npc_belief (turn_id, claim_id, predicate, object, "
                    "confidence, accepted_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (turn_id, claim_id, row["predicate"], row["object"],
                     BELIEF_CONFIDENCE, actor, _now()),
                )
                belief_id = int(cur.lastrowid)
            v = self.version()
            self._record_event(
                turn_id, "claim_decision_processed",
                {"claim_id": claim_id, "decision": decision, "actor": actor},
                "judge_claim_skill", v, v,
            )
        return belief_id

    def refuse_trade(self, turn_id: int, reason: str) -> SkillResult:
        with self._tx():
            v = self.version()
            self._record_event(turn_id, "trade_refused", {"reason": reason},
                               "refuse_trade_skill", v, v)
        return SkillResult("refuse_trade", True, reason)

    def log_generated(self, turn_id: int, utterance: str) -> None:
        with self._tx():
            self.conn.execute(
                "INSERT INTO generated_text (turn_id, utterance, memory_eligible, "
                "created_at) VALUES (?, ?, 0, ?)",
                (turn_id, utterance, _now()),
            )

    def claims(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM player_claim ORDER BY claim_id"))

    def beliefs(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM npc_belief ORDER BY belief_id"))

    def decisions(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM claim_decision ORDER BY decision_id"))

    def events(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM committed_event ORDER BY event_id"))

    def refusals(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM engine_refusal ORDER BY refusal_id"))

    def close(self) -> None:
        self.conn.close()
