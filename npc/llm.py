from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config


@dataclass(frozen=True)
class Completion:
    text: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    schema_ok: bool
    parsed: dict | None = None


class InferenceError(RuntimeError):
    pass


def _post(url: str, payload: dict, timeout: int = 180) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise InferenceError(f"{url} unreachable: {exc}") from exc


def chat(
    messages: list[dict],
    seed: int,
    max_tokens: int = config.MAX_TOKENS,
    json_schema: dict | None = None,
) -> Completion:
    payload = {
        "messages": messages,
        "temperature": config.TEMPERATURE,
        "top_p": config.TOP_P,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "structured", "schema": json_schema, "strict": True},
        }

    started = time.perf_counter()
    body = _post(config.CHAT_ENDPOINT, payload)
    latency_ms = int((time.perf_counter() - started) * 1000)

    if "error" in body:
        raise InferenceError(str(body["error"]))
    text = body["choices"][0]["message"]["content"] or ""
    usage = body.get("usage", {})

    parsed, schema_ok = None, True
    if json_schema is not None:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            schema_ok = False

    return Completion(
        text=text.strip(),
        latency_ms=latency_ms,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        schema_ok=schema_ok,
        parsed=parsed,
    )


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    body = _post(config.EMBED_ENDPOINT, {"input": texts})
    if "error" in body:
        raise InferenceError(str(body["error"]))
    ordered = sorted(body["data"], key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in ordered]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def server_ready() -> tuple[bool, bool]:
    def alive(url: str) -> bool:
        base = url.rsplit("/v1/", 1)[0]
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    return alive(config.CHAT_ENDPOINT), alive(config.EMBED_ENDPOINT)
