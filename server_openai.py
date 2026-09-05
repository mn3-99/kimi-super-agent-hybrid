"""OpenAI-compatible server — superset of nvidia-kimi-bridge.

Endpoints:
  GET  /healthz                  -> {minter_ready, last_error, uptime_s}
  GET  /v1/models                -> curated NVIDIA list + provider-backed ids
  GET  /v1/providers             -> provider status (never leaks keys)
  GET  /v1/models/resolve/{slug} -> resolve any org/name playground slug
  POST /v1/chat/completions      -> NVIDIA bridge (org/name slugs) OR smart
                                    multi-provider proxy (gpt-5*, claude-*, free-chat)
  POST /v1/swarm                 -> AgentSwarm fan-out (new)
  GET  /screenshot               -> live playground screenshot (new, MCP parity)

Run:  uvicorn server_openai:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import os as _os
import sys as _sys
import time
import uuid
from contextlib import asynccontextmanager

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response

import config
from config import CURATED_MODELS, KEEPALIVE_SECS
from upstream import (
    ModelNotFound, api_url, build_upstream_payload, limiter, pump_upstream,
    resolve_model,
)

_started_at = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # LAZY browser: do NOT block startup on playwright (bridge FIX 1).
    # The minter spawns on first mint(); healthz shows readiness.
    yield
    try:
        from captcha import minter

        await minter.close()
    except Exception:
        pass


app = FastAPI(title="kimi-super-agent (openai-compat)", lifespan=lifespan)


def sse_err(msg: str) -> str:
    return "data: " + json.dumps(
        {"error": {"message": msg, "type": "bridge_error", "code": None}}
    ) + "\n\ndata: [DONE]\n\n"


@app.get("/healthz")
async def healthz():
    from captcha import minter

    return {
        "minter_ready": minter.ready,
        "last_error": minter.last_error,
        "uptime_s": round(time.time() - _started_at, 1),
    }


@app.get("/v1/models")
async def models():
    data = [
        {"id": m, "object": "model", "created": 1757000000,
         "owned_by": "build.nvidia.com (bridged)"}
        for m in CURATED_MODELS
    ]
    try:
        import providers as _pv

        for m in _pv.MODEL_ROUTES:
            data.append({"id": m, "object": "model", "created": 1757000000,
                         "owned_by": "smart-proxy (" +
                         "/".join(p for p, _ in _pv.MODEL_ROUTES[m]) + ")"})
    except Exception:
        pass
    return {"object": "list", "data": data}


@app.get("/v1/providers")
async def providers_status():
    try:
        import providers as _pv

        return {"object": "list", "data": _pv.provider_status(),
                "usage": _pv.usage_summary()}
    except Exception as e:
        return JSONResponse({"error": {"message": str(e)[:200]}}, status_code=500)


@app.get("/v1/models/resolve/{slug:path}")
async def resolve_slug(slug: str):
    try:
        entry = await asyncio.to_thread(resolve_model, slug)
        return {"ok": True, "entry": entry}
    except ModelNotFound as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)


@app.get("/screenshot")
async def screenshot():
    from captcha import minter

    shot = await minter.screenshot()
    if not shot:
        return JSONResponse({"error": "browser not ready yet"}, status_code=503)
    return Response(content=shot, media_type="image/png")


@app.post("/v1/chat/completions")
async def chat(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": {"message": "invalid JSON"}}, status_code=400)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return JSONResponse({"error": {"message": "messages[] required"}}, status_code=400)
    slug = body.get("model") or config.DEFAULT_MODEL
    # Smart-proxy route first: gpt-5*, claude-*, free-chat (+ aliases).
    try:
        import providers as _pv

        _has_pv = True
    except Exception:
        _has_pv = False
    if _has_pv and _pv.is_provider_model(slug):
        if not body.get("stream"):
            return await provider_non_stream(body, slug)
        return StreamingResponse(
            provider_stream_gen(body, slug),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                     "X-Accel-Buffering": "no"},
        )
    try:
        entry = await asyncio.to_thread(resolve_model, slug)
    except ModelNotFound as e:
        return JSONResponse(
            {"error": {"message": f"model '{slug}' not resolvable: {e}",
                       "type": "invalid_request_error"}}, status_code=404)
    except Exception as e:
        return JSONResponse(
            {"error": {"message": f"model resolution failed: {e}", "type": "bridge_error"}},
            status_code=502)
    payload = build_upstream_payload(body, entry)
    if not body.get("stream"):
        return await non_stream(payload, entry)
    return StreamingResponse(
        stream_gen(payload, entry),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"},
    )


async def stream_gen(payload: dict, entry: dict):
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(pump_upstream(payload, entry, q))
    try:
        yield ": bridge-connected\n\n"
        yield ": stage=mint-captcha-and-queue\n\n"
        while True:
            try:
                kind, data = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SECS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if kind == "data":
                # TRUE passthrough (keeps reasoning_content) — not re-chunked.
                yield f"data: {data}\n\n"
            elif kind == "done":
                yield "data: [DONE]\n\n"
                return
            else:
                yield sse_err(data)
                return
    finally:
        if not task.done():
            task.cancel()


async def non_stream(payload: dict, entry: dict):
    q: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(pump_upstream(payload, entry, q))
    content_parts: list[str] = []
    reason_parts: list[str] = []
    usage = None
    model = entry["slug"]
    cid = f"chatcmpl-{uuid.uuid4()}"
    try:
        while True:
            try:
                kind, data = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SECS * 30)
            except asyncio.TimeoutError:
                if not task.done():
                    task.cancel()
                return JSONResponse(
                    {"error": {"message": "upstream timeout (no data for 300s)",
                               "type": "bridge_timeout"}}, status_code=504)
            if kind == "data":
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                cid = chunk.get("id", cid)
                model = chunk.get("model", model)
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
                if not task.done():
                    task.cancel()
                return JSONResponse(
                    {"error": {"message": data, "type": "bridge_error"}}, status_code=502)
    finally:
        if not task.done():
            task.cancel()
    msg: dict = {"role": "assistant", "content": "".join(content_parts)}
    reasoning = "".join(reason_parts)
    if reasoning:
        msg["reasoning_content"] = reasoning
    return {
        "id": cid, "object": "chat.completion", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop",
                     "logprobs": None}],
        "usage": usage,
    }


async def provider_non_stream(body: dict, slug: str):
    import providers as _pv

    try:
        out = await _pv.smart_chat_once(
            body["messages"], slug,
            max_tokens=int(body.get("max_tokens", config.PROVIDER_MAX_TOKENS)),
            temperature=float(body.get("temperature", 1)))
    except _pv.NoProviderConfigured as e:
        return JSONResponse(
            {"error": {"message": str(e), "type": "no_provider_configured"}},
            status_code=402)
    except Exception as e:
        return JSONResponse(
            {"error": {"message": str(e)[:500], "type": "providers_exhausted"}},
            status_code=502)
    msg: dict = {"role": "assistant", "content": out.get("content", "")}
    if out.get("reasoning"):
        msg["reasoning_content"] = out["reasoning"]
    return {
        "id": f"chatcmpl-{uuid.uuid4()}", "object": "chat.completion",
        "created": int(time.time()), "model": out.get("model", slug),
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop",
                     "logprobs": None}],
        "usage": out.get("usage"),
        "provider": out.get("provider"),
    }


async def provider_stream_gen(body: dict, slug: str):
    import providers as _pv

    yield ": smart-proxy-connected\n\n"
    try:
        async for line in _pv.smart_chat_stream(
                body["messages"], slug,
                max_tokens=int(body.get("max_tokens", config.PROVIDER_MAX_TOKENS)),
                temperature=float(body.get("temperature", 1))):
            yield line
    except Exception as e:
        yield sse_err(f"smart proxy failed: {e}"[:300])


@app.post("/v1/swarm")
async def swarm(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)
    instruction = body.get("instruction", "")
    items = body.get("items", [])
    if not instruction or not isinstance(items, list) or not items:
        return JSONResponse({"error": "instruction + items[] required"}, status_code=400)
    if len(items) > 300:
        return JSONResponse({"error": "max 300 items per swarm"}, status_code=400)
    from swarm import swarm_run

    out = await swarm_run(
        instruction,
        [str(x)[:2000] for x in items],
        model=body.get("model") or config.DEFAULT_MODEL,
        max_concurrency=int(body.get("max_concurrency", config.SWARM_MAX_CONCURRENCY)),
        timeout_per_item_s=float(body.get("timeout_per_item_s", config.SWARM_TIMEOUT_PER_ITEM_S)),
        budget_s=float(body.get("budget_s", config.SWARM_BUDGET_S)),
        synthesize=bool(body.get("synthesize", True)),
    )
    return out
