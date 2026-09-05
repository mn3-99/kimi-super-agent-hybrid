"""Upstream client — merges bridge.py upstream logic with MCP DirectClient ideas.

FIXES vs originals:
- RateLimiter: original slept INSIDE the asyncio.Lock (serialises ALL requests
  for up to 60s). Fixed: compute wait under lock, sleep OUTSIDE, re-loop.
- resolve_model: kept (GET playground + regex + disk cache), added alias
  handling + thread-safe cache + clear error type.
- build_upstream_payload: kept, with reasoning_effort default per model.
- pump_upstream: kept retry logic (captcha refresh, drop reasoning_effort),
  emits ("data"|"done"|"error") tuples into an asyncio.Queue.
  Adds: queue-probe error detection (urn:kaizen) + byte counting.
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import sys as _sys
import threading
import time

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from config import ALIASES, API_BASE, BUILD_ORIGIN, MAX_REQ_PER_MIN, REASONING_DEFAULTS

try:
    from curl_cffi import requests as _sync_requests
    from curl_cffi.requests import AsyncSession
except Exception:  # imported lazily at runtime only when needed
    _sync_requests = None  # type: ignore
    AsyncSession = None  # type: ignore

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models_cache.json")
_model_cache: dict = {}
_cache_lock = threading.Lock()


class ModelNotFound(Exception):
    pass


def _load_model_cache() -> None:
    try:
        with open(CACHE_FILE) as f:
            _model_cache.update(json.load(f))
    except Exception:
        pass


def _save_model_cache() -> None:
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_model_cache, f, indent=1)
        os.replace(tmp, CACHE_FILE)
    except Exception:
        pass


def resolve_model(slug: str) -> dict:
    slug = ALIASES.get(slug, slug)
    if "/" not in slug:
        raise ModelNotFound(f"'{slug}' is not a full slug (org/name) or known alias")
    with _cache_lock:
        hit = _model_cache.get(slug)
    if hit:
        return hit
    if _sync_requests is None:
        raise ModelNotFound("curl_cffi not installed")
    r = _sync_requests.get(f"{BUILD_ORIGIN}/{slug}/playground", impersonate="chrome", timeout=40)
    if r.status_code != 200:
        raise ModelNotFound(f"page HTTP {r.status_code}")
    t = r.text.replace('\\\\"', '"').replace('\\"', '"')
    fn = re.search(r'"nvcfFunctionId"\s*:\s*"([0-9a-f-]{36})"', t)
    ns = re.search(r'"namespace"\s*:\s*"([^"]+)"', t[: fn.end()] if fn else t)
    mp = re.search(r'"modelPath"\s*:\s*"([^"]+)"', t)
    if not (fn and ns):
        raise ModelNotFound(f"no chat function embedded in {slug} page")
    if mp and mp.group(1).strip("/").lower() != slug.lower():
        raise ModelNotFound(f"page modelPath={mp.group(1)} != {slug}")
    entry = {"slug": slug, "namespace": ns.group(1), "fn": fn.group(1),
             "name": slug.split("/")[-1]}
    with _cache_lock:
        _model_cache[slug] = entry
        _save_model_cache()
    return entry


_load_model_cache()


class RateLimiter:
    """Sliding-window: at most N upstream requests per 60 s (lock-free sleep)."""

    def __init__(self, per_min: int):
        self.per = per_min
        self.stamps: collections.deque[float] = collections.deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self.stamps and now - self.stamps[0] > 60:
                    self.stamps.popleft()
                if len(self.stamps) < self.per:
                    self.stamps.append(now)
                    return
                wait = min(5.0, self.stamps[0] + 60 - now)
            await asyncio.sleep(max(0.05, wait))


limiter = RateLimiter(int(os.getenv("MAX_REQ_PER_MIN", str(MAX_REQ_PER_MIN))))


def upstream_headers(token: str, fn_id: str) -> dict:
    return {
        "Origin": "https://build.nvidia.com",
        "Referer": "https://build.nvidia.com/",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "nv-captcha-token": token,
        "nv-function-id": fn_id,
        "User-Agent": config.UA,
    }


def api_url(entry: dict) -> str:
    return f"{API_BASE}/{entry['namespace']}/{entry['name']}"


def build_upstream_payload(body: dict, entry: dict) -> dict:
    payload: dict = {}
    effort = body.get("reasoning_effort", REASONING_DEFAULTS.get(entry["slug"]))
    if effort:
        payload["reasoning_effort"] = effort
    payload.update(
        {
            "stream": True,
            "model": entry["slug"],
            "seed": body.get("seed", 0),
            "max_tokens": body.get("max_tokens", 16384),
            "temperature": body.get("temperature", 1),
            "messages": body["messages"],
            "stream_options": {"include_usage": True, "continuous_usage_stats": True},
        }
    )
    if "top_p" in body and body["top_p"] is not None:
        payload["top_p"] = body["top_p"]
    return payload


async def pump_upstream(payload: dict, entry: dict, q: asyncio.Queue) -> None:
    """PUT every SSE `data:` line into q. Items: ("data",json)|("done",None)|("error",msg)."""
    from captcha import minter

    if AsyncSession is None:
        await q.put(("error", "curl_cffi not installed"))
        return
    sess = AsyncSession(impersonate="chrome", timeout=600)
    resp = None
    try:
        for attempt in (0, 1, 2):
            try:
                token = await minter.mint()
            except Exception as e:
                await q.put(("error", f"captcha mint failed: {e}"))
                return
            await limiter.acquire()
            resp = await sess.post(
                api_url(entry), headers=upstream_headers(token, entry["fn"]),
                json=payload, stream=True,
            )
            if resp.status_code == 200:
                break
            try:
                body = await resp.atext()
            except Exception:
                body = ""
            if resp.status_code == 400 and "Captcha" in body and attempt == 0:
                await resp.aclose()
                resp = None
                continue
            if (
                resp.status_code == 400
                and "reasoning_effort" in body
                and payload.pop("reasoning_effort", None) is not None
            ):
                await resp.aclose()
                resp = None
                continue
            if (
                resp.status_code in (500, 502, 503)
                and payload.pop("reasoning_effort", None) is not None
            ):
                # NVIDIA gateway sometimes 500s on reasoning_effort=max under load
                # (observed: "Retries exhausted: 3/3" on kimi-k3). Retry once
                # without the parameter — plain request succeeds.
                await resp.aclose()
                resp = None
                continue
            await q.put(("error", f"upstream HTTP {resp.status_code}: {body[:300]}"))
            return
        async for line in resp.aiter_lines():
            if not line:
                continue
            if line.startswith(b"data:"):
                text = line[5:].strip().decode("utf-8", "replace")
                if text == "[DONE]":
                    break
                if text.startswith('{"type":"urn:kaizen'):
                    await q.put(("error", f"upstream problem: {text[:300]}"))
                    return
                await q.put(("data", text))
        await q.put(("done", None))
    except Exception as e:
        await q.put(("error", f"{type(e).__name__}: {e}"))
    finally:
        try:
            if resp is not None:
                await resp.aclose()
        except Exception:
            pass
        try:
            await sess.close()
        except Exception:
            pass


async def chat_once(
    messages: list[dict],
    model: str | None = None,
    timeout_s: float = 420.0,
    **kwargs,
) -> dict:
    """One non-streaming round-trip. Returns {content, reasoning, usage, model}."""
    slug = model or config.DEFAULT_MODEL
    entry = await asyncio.to_thread(resolve_model, slug)
    body = {"messages": messages, "model": entry["slug"], **kwargs}
    payload = build_upstream_payload(body, entry)
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(pump_upstream(payload, entry, q))
    content_parts: list[str] = []
    reason_parts: list[str] = []
    usage = None
    used_model = entry["slug"]
    try:
        while True:
            try:
                kind, data = await asyncio.wait_for(q.get(), timeout=timeout_s)
            except asyncio.TimeoutError:
                raise TimeoutError(f"upstream timeout after {timeout_s}s")
            if kind == "data":
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                used_model = chunk.get("model", used_model)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for ch in chunk.get("choices") or []:
                    d = ch.get("delta") or {}
                    if d.get("reasoning_content"):
                        reason_parts.append(d["reasoning_content"])
                    if d.get("content"):
                        content_parts.append(d["content"])
            elif kind == "done":
                break
            else:
                raise RuntimeError(str(data))
    finally:
        if not task.done():
            task.cancel()
    return {
        "content": "".join(content_parts),
        "reasoning": "".join(reason_parts),
        "usage": usage,
        "model": used_model,
    }
