"""SSE parsing — ported 1:1 from nvidia-kimi-mcp/nvidia_kimi_mcp/network.py
(pure logic, no browser needed) + small streaming helpers for the bridge.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Usage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ParsedCompletion:
    content: str = ""
    reasoning: str = ""
    finish_reason: Optional[str] = None
    usage: Usage = field(default_factory=Usage)
    model: Optional[str] = None
    raw_chunks: int = 0
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "reasoning": self.reasoning,
            "finish_reason": self.finish_reason,
            "usage": self.usage.as_dict(),
            "model": self.model,
            "chunks": self.raw_chunks,
            "error": self.error,
        }


def _merge_chunk(parsed: ParsedCompletion, chunk: dict[str, Any]) -> None:
    parsed.raw_chunks += 1
    if not parsed.model:
        parsed.model = chunk.get("model")
    usage = chunk.get("usage") or {}
    if usage:
        parsed.usage.prompt_tokens = usage.get("prompt_tokens", parsed.usage.prompt_tokens)
        parsed.usage.completion_tokens = usage.get(
            "completion_tokens", parsed.usage.completion_tokens
        )
        parsed.usage.total_tokens = usage.get("total_tokens", parsed.usage.total_tokens)
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or choice.get("message") or {}
        if isinstance(delta.get("content"), str):
            parsed.content += delta["content"]
        if isinstance(delta.get("reasoning_content"), str):
            parsed.reasoning += delta["reasoning_content"]
        if choice.get("finish_reason"):
            parsed.finish_reason = choice["finish_reason"]


def parse_sse_stream(body: str) -> ParsedCompletion:
    parsed = ParsedCompletion()
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            _merge_chunk(parsed, json.loads(data))
        except json.JSONDecodeError:
            continue
    return parsed


def parse_completion_body(body: str, content_type: str = "") -> ParsedCompletion:
    if "event-stream" in content_type or body.lstrip().startswith("data:"):
        return parse_sse_stream(body)
    parsed = ParsedCompletion()
    try:
        _merge_chunk(parsed, json.loads(body))
    except json.JSONDecodeError as exc:
        parsed.error = f"unparseable response body: {exc}"
    return parsed


def extract_deltas(sse_data_line: str) -> tuple[str, str, Any, Any]:
    """Parse one upstream `data:` payload -> (reasoning, content, usage, finish).

    Never raises: returns empty strings on any unparseable input.
    """
    try:
        chunk = json.loads(sse_data_line)
    except Exception:
        return "", "", None, None
    reasoning, content = "", ""
    usage, finish = None, None
    if chunk.get("usage"):
        usage = chunk["usage"]
    for ch in chunk.get("choices") or []:
        d = ch.get("delta") or {}
        if isinstance(d.get("reasoning_content"), str):
            reasoning += d["reasoning_content"]
        if isinstance(d.get("content"), str):
            content += d["content"]
        if ch.get("finish_reason"):
            finish = ch.get("finish_reason")
    # also support non-streaming message shape
    if not reasoning and not content:
        msg = (chunk.get("choices") or [{}])[0].get("message") or {}
        if isinstance(msg.get("reasoning_content"), str):
            reasoning = msg["reasoning_content"]
        if isinstance(msg.get("content"), str):
            content = msg["content"]
    return reasoning, content, usage, finish
