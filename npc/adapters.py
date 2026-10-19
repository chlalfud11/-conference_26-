from __future__ import annotations

from dataclasses import dataclass, field

from . import config, llm
from .engine import GameEngine

KIND_LABELS = {
    "world_truth": "세계사실",
    "committed_event": "확정사건",
    "player_claim": "손님주장",
    "npc_belief": "내믿음",
    "utterance": "대화",
}


@dataclass
class MemoryItem:
    turn: int
    kind: str
    text: str
    source: str
    verified: str = "n/a"
    confidence: float | None = None

    def render(self, fields: tuple[str, ...]) -> str:
        if fields == ("text",):
            return self.text
        head = f"[{KIND_LABELS.get(self.kind, self.kind)}] {self.text}"
        tail = []
        if "source" in fields:
            tail.append(f"출처: {self.source}")
        if "verified" in fields and self.verified != "n/a":
            tail.append(f"검증: {self.verified}")
        if "confidence" in fields and self.confidence is not None:
            tail.append(f"확신: {self.confidence:.2f}")
        return f"{head} ({', '.join(tail)})" if tail else head


def shop_status(engine: GameEngine) -> str:
    lines = [f"- 내 금고에 손님 골드 기록: {engine.fact('player.gold')}골드"]
    for item in config.PRICES:
        reserved = engine.fact(f"shop.reserved.{item}")
        lines.append(
            f"- {item}: 재고 {engine.fact(f'shop.stock.{item}')}개, "
            f"예약 {reserved}개, 판매가 {config.PRICES[item]}골드"
        )
    return "\n".join(lines)


class VectorRagMemory:
    name = "vector_rag"

    def __init__(self, engine: GameEngine) -> None:
        self.engine = engine
        self._chunks: list[str] = []
        self._vectors: list[list[float]] = []

    def remember(self, turn: int, speaker: str, text: str, **_: object) -> None:
        self._chunks.append(f"{speaker}: {text}")

    def _sync_vectors(self) -> None:
        missing = self._chunks[len(self._vectors):]
        if missing:
            self._vectors.extend(llm.embed(missing))

    def context(self, query: str, fields: tuple[str, ...]) -> str:
        if not self._chunks:
            return "(아직 나눈 이야기가 없음)"
        self._sync_vectors()
        qvec = llm.embed([query])[0]
        scored = sorted(
            zip(self._chunks, self._vectors),
            key=lambda pair: llm.cosine(qvec, pair[1]),
            reverse=True,
        )
        return "\n".join(chunk for chunk, _ in scored[: config.RAG_TOP_K])


class StructuredMemory:
    name = "structured"

    def __init__(self, engine: GameEngine) -> None:
        self.engine = engine
        self._utterances: list[MemoryItem] = []

    def remember(self, turn: int, speaker: str, text: str, **_: object) -> None:
        self._utterances.append(
            MemoryItem(turn=turn, kind="utterance", text=f"{speaker}: {text}", source=speaker)
        )

    def _items(self) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for row in self.engine.claims():
            items.append(MemoryItem(
                turn=row["turn_id"], kind="player_claim", text=row["raw_text"],
                source="player", verified=row["evidence"],
            ))
        for row in self.engine.beliefs():
            label = config.PREDICATE_LABELS.get(row["predicate"], row["predicate"])
            items.append(MemoryItem(
                turn=row["turn_id"], kind="npc_belief",
                text=f"{row['object']}에 대해 '{label}'고 믿는다",
                source=row["accepted_by"], verified="verified",
                confidence=row["confidence"],
            ))
        for row in self.engine.events():
            items.append(MemoryItem(
                turn=row["turn_id"], kind="committed_event",
                text=f"{row['event_type']} {row['payload']}",
                source=row["source"], verified="verified",
            ))
        items.extend(self._utterances)
        return sorted(items, key=lambda i: i.turn)

    def context(self, query: str, fields: tuple[str, ...]) -> str:
        items = self._items()
        if not items:
            return "(아직 기록이 없음)"
        return "\n".join(item.render(fields) for item in items)


def build_memory(condition: str, engine: GameEngine):
    kind = config.CONDITIONS[condition]["memory"]
    return VectorRagMemory(engine) if kind == "vector_rag" else StructuredMemory(engine)
