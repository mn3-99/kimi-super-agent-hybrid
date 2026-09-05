"""Multi-provider smart proxy — GPT-5 / Claude 5-gen / free tiers.

Honest design (verified 2026-09-05):
- GPT-5 (openai) and Claude 5-gen (anthropic) are PAID APIs. This module does
  NOT bypass paywalls: it routes to them with the USER's own keys from env.
- Keyless providers: NVIDIA bridge (captcha, see upstream.py) + Pollinations
  POST /openai (openai-fast, verified free 2026-09-05).
- Free-with-key: Gemini / Groq / Cerebras / OpenRouter (user registers free).

Never-stop strategy:
  1. Per-model failover chains (MODEL_ROUTES): try providers in order.
  2. Multi-key rotation per provider (comma-separated env values).
  3. Circuit breaker: 3 consecutive failures -> 120s cooldown per provider.
  4. Token budgets: optional per-provider daily token caps + persistent usage
     ledger (provider_usage.json). Keys themselves are NEVER logged/persisted.
  5. Backoff between attempts; 4xx (except 429) fails fast, 429/5xx fail over.
"""
from __future__ import annotations

import asyncio
import json
import os as _os
import sys as _sys
import threading
import time
import urllib.request

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

import config
from config import CB_COOLDOWN_S, CB_FAILURES, MODEL_ROUTES, PROVIDERS, PROVIDER_ALIASES


class NoProviderConfigured(Exception):
    pass


# ------------------------------------------------------------------ key pools
def _keys_for(provider: str) -> list[str]:
    env = (PROVIDERS[provider].get("env") or "")
    if not env:
        return []
    raw = _os.getenv(env, "")
    return [k.strip() for k in raw.split(",") if k.strip()]


class KeyPool:
    """Round-robin over a provider's keys (never exposes key values)."""

    def __init__(self, provider: str):
        self.provider = provider
        self._idx = 0
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return bool(_keys_for(self.provider)) or PROVIDERS[self.provider].get("free") is True

    def next(self) -> str | None:
        keys = _keys_for(self.provider)
        if not keys:
            return None  # keyless provider
        with self._lock:
            k = keys[self._idx % len(keys)]
            self._idx += 1
            return k


_pools: dict[str, KeyPool] = {p: KeyPool(p) for p in PROVIDERS}


# ------------------------------------------------------------- usage ledger
_ledger_lock = threading.Lock()
_ledger: dict = {}


def _usage_path() -> str:
    p = config.USAGE_FILE
    return p if _os.path.isabs(p) else _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)), p)


def _load_ledger() -> None:
    try:
        with open(_usage_path()) as f:
            _ledger.update(json.load(f))
    except Exception:
        pass


def _save_ledger() -> None:
    try:
        tmp = _usage_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_ledger, f, indent=1)
        _os.replace(tmp, _usage_path())
    except Exception:
        pass


def _day() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def record_usage(provider: str, prompt_tokens: int = 0,
                 completion_tokens: int = 0, error: bool = False) -> None:
    with _ledger_lock:
        day = _ledger.setdefault(_day(), {})
        e = day.setdefault(provider, {"requests": 0, "errors": 0,
                                      "prompt_tokens": 0, "completion_tokens": 0})
        e["requests"] += 1
        if error:
            e["errors"] += 1
        e["prompt_tokens"] += prompt_tokens or 0
        e["completion_tokens"] += completion_tokens or 0
        _save_ledger()


def usage_summary() -> dict:
    with _ledger_lock:
        return json.loads(json.dumps(_ledger))


def budget_exceeded(provider: str) -> bool:
    cap = _os.getenv(f"{provider.upper()}_MAX_TOKENS_PER_DAY", "")
    if not cap:
        return False
    try:
        cap_n = int(cap)
    except ValueError:
        return False
    with _ledger_lock:
        e = _ledger.get(_day(), {}).get(provider, {})
        used = (e.get("prompt_tokens", 0) + e.get("completion_tokens", 0))
    return used >= cap_n


_load_ledger()


# ------------------------------------------------------------ circuit breaker
_cb_lock = threading.Lock()
_cb: dict[str, dict] = {}  # provider -> {fails, cooldown_until}


def circuit_open(provider: str) -> bool | str:
    with _cb_lock:
        st = _cb.get(provider)
        if not st:
            return False
        if st["fails"] < CB_FAILURES:
            return False
        if time.monotonic() < st["cooldown_until"]:
            return f"cooldown {int(st['cooldown_until'] - time.monotonic())}s"
        st["fails"] = 0
        return False


def circuit_note(provider: str, ok: bool) -> None:
    with _cb_lock:
        st = _cb.setdefault(provider, {"fails": 0, "cooldown_until": 0.0})
        if ok:
            st["fails"] = 0
        else:
            st["fails"] += 1
            if st["fails"] >= CB_FAILURES:
                st["cooldown_until"] = time.monotonic() + CB_COOLDOWN_S


# ------------------------------------------------------------------- routing
def normalize_model(model: str) -> str:
    m = (model or "").strip()
    return PROVIDER_ALIASES.get(m, m)


def is_provider_model(model: str) -> bool:
    return normalize_model(model) in MODEL_ROUTES


def route_model(model: str) -> list[tuple[str, str]]:
    """Failover chain, skipping unconfigured / budgeted-out / cooling providers."""
    m = normalize_model(model)
    chain = MODEL_ROUTES.get(m, [])
    out = []
    for provider, pid in chain:
        if provider == "nvidia":
            out.append((provider, pid))
            continue
        if not _pools[provider].configured():
            continue
        if budget_exceeded(provider):
            continue
        if circuit_open(provider):
            continue
        out.append((provider, pid))
    return out


def provider_status() -> list[dict]:
    rows = []
    for name, meta in PROVIDERS.items():
        if name == "nvidia":
            rows.append({"provider": name, "configured": True, "free": True,
                         "models": ["10 NVIDIA build slugs (bridge)"],
                         "circuit": "closed", "note": meta["note"]})
            continue
        rows.append({
            "provider": name,
            "configured": bool(_pools[name].configured()),
            "free": meta.get("free"),
            "models": [pid for (p, pid) in
                       [c for chain in MODEL_ROUTES.values() for c in chain] if p == name],
            "circuit": "open" if circuit_open(name) else "closed",
            "budget_exceeded": budget_exceeded(name),
            "note": meta["note"],
        })
    return rows


# ------------------------------------------------------------- HTTP helpers
def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:  # HTTPError carries .code + body
        code = getattr(e, "code", 0) or 0
        try:
            body = e.read().decode("utf-8", "replace")  # type: ignore[attr-defined]
        except Exception:
            body = str(e)
        return code, body


def _openai_headers(provider: str, key: str | None) -> dict:
    h = {"Content-Type": "application/json", "User-Agent": "kimi-super-agent/1.0"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    if provider == "openrouter":
        h["HTTP-Referer"] = "https://localhost/kimi-super-agent"
        h["X-Title"] = "kimi-super-agent"
    return h


def _openai_payload(provider: str, provider_model: str, messages: list[dict],
                    max_tokens: int, temperature: float, stream: bool) -> dict:
    p: dict = {"model": provider_model, "messages": messages, "stream": stream}
    if provider != "pollinations":
        p["max_tokens"] = max_tokens
        p["temperature"] = temperature
    else:
        p["max_tokens"] = max_tokens
    return p


def _anthropic_payload(provider_model: str, messages: list[dict],
                       max_tokens: int, temperature: float, stream: bool) -> tuple[dict, str]:
    system_parts = [m["content"] for m in messages
                    if m.get("role") == "system" and isinstance(m.get("content"), str)]
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages
            if m.get("role") in ("user", "assistant")]
    body: dict = {"model": provider_model, "max_tokens": max_tokens,
                  "temperature": temperature, "messages": msgs, "stream": stream}
    if system_parts:
        body["system"] = "\n\n".join(system_parts)
    return body, "2023-06-01"


def _extract_openai_usage(data: dict) -> tuple[int, int]:
    u = data.get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


# ------------------------------------------------------- one-shot smart chat
async def smart_chat_once(messages: list[dict], model: str,
                          timeout_s: float | None = None,
                          max_tokens: int | None = None,
                          temperature: float = 1.0) -> dict:
    """Try the failover chain; return {content, reasoning, usage, model, provider}."""
    timeout = timeout_s or config.PROVIDER_TIMEOUT_S
    mtok = max_tokens or config.PROVIDER_MAX_TOKENS
    chain = route_model(model)
    if not chain:
        raise NoProviderConfigured(
            f"model '{model}': no configured provider. "
            f"Set {', '.join(PROVIDERS[p]['env'] for p, _ in MODEL_ROUTES.get(normalize_model(model), []) if PROVIDERS[p].get('env'))} "
            f"or use a free model (NVIDIA slugs / pollinations-free). "
            f"See GET /v1/providers.")
    errors: list[str] = []
    for provider, pid in chain:
        # 2 attempts per provider: rotate keys, or retry once when keyless
        # (transient 402/429/5xx flaps are real — observed live).
        for attempt in range(2):
            key = _pools[provider].next()
            try:
                out = await asyncio.to_thread(
                    _call_once, provider, pid, messages, mtok, temperature, key, timeout)
            except Exception as e:  # transport-level
                errors.append(f"{provider}: {type(e).__name__}")
                circuit_note(provider, False)
                record_usage(provider, error=True)
                await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                continue
            if out.get("ok"):
                circuit_note(provider, True)
                u = out.get("usage") or {}
                record_usage(provider, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
                out["provider"] = provider
                return out
            err = out.get("error", "")
            code = out.get("code", 0)
            errors.append(f"{provider} HTTP {code}: {err[:120]}")
            record_usage(provider, error=True)
            if code in (401, 403):
                circuit_note(provider, False)
                break  # bad key: rotating won't help, next provider
            if code in (402, 408, 425, 429) or code >= 500:
                # 402 = upstream paywall/rate flap (seen live on Pollinations
                # legacy path): worth one retry, then fail over.
                circuit_note(provider, False)
                await asyncio.sleep(min(4.0, 0.5 * (2 ** attempt)))
                continue  # same provider next key, then next provider
            circuit_note(provider, True)  # 400-class: provider healthy, request bad
            break
    raise RuntimeError(f"all providers failed for '{model}': " + " | ".join(errors)[:500])


def _call_once(provider: str, pid: str, messages: list[dict], mtok: int,
               temperature: float, key: str | None, timeout: float) -> dict:
    if provider == "anthropic":
        return _call_anthropic(pid, messages, mtok, temperature, key or "", timeout)
    base = PROVIDERS[provider]["base"]
    url = base.rstrip("/") + "/chat/completions"
    code, body = _post_json(url, _openai_payload(provider, pid, messages, mtok, temperature, False),
                            _openai_headers(provider, key), timeout)
    if code != 200:
        return {"ok": False, "code": code, "error": body[:300]}
    try:
        data = json.loads(body)
        msg = data["choices"][0]["message"]
        pt, ct = _extract_openai_usage(data)
        return {"ok": True, "content": msg.get("content", "") or "",
                "reasoning": msg.get("reasoning_content", "") or "",
                "usage": {"prompt_tokens": pt, "completion_tokens": ct,
                          "total_tokens": pt + ct},
                "model": data.get("model", pid)}
    except Exception as e:
        return {"ok": False, "code": code, "error": f"unparseable: {e}"}


def _call_anthropic(pid: str, messages: list[dict], mtok: int,
                    temperature: float, key: str, timeout: float) -> dict:
    body, version = _anthropic_payload(pid, messages, mtok, temperature, False)
    code, text = _post_json("https://api.anthropic.com/v1/messages", body,
                            {"Content-Type": "application/json", "x-api-key": key,
                             "anthropic-version": version,
                             "User-Agent": "kimi-super-agent/1.0"}, timeout)
    if code != 200:
        return {"ok": False, "code": code, "error": text[:300]}
    try:
        data = json.loads(text)
        content = "".join(b.get("text", "") for b in data.get("content", [])
                          if isinstance(b, dict) and b.get("type") == "text")
        u = data.get("usage") or {}
        pt, ct = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        return {"ok": True, "content": content, "reasoning": "",
                "usage": {"prompt_tokens": pt, "completion_tokens": ct,
                          "total_tokens": pt + ct}, "model": data.get("model", pid)}
    except Exception as e:
        return {"ok": False, "code": code, "error": f"unparseable: {e}"}


# ------------------------------------------------- streaming smart chat (SSE)
async def smart_chat_stream(messages: list[dict], model: str,
                            max_tokens: int | None = None,
                            temperature: float = 1.0):
    """Yield OpenAI-style `data: {...}` lines from the first healthy provider."""
    from collections.abc import AsyncIterator  # noqa: F401  (type hint aid)
    mtok = max_tokens or config.PROVIDER_MAX_TOKENS
    chain = route_model(model)
    if not chain:
        yield "data: " + json.dumps(
            {"error": {"message": f"model '{model}': no configured provider. "
                                  "See GET /v1/providers for setup.",
                       "type": "no_provider_configured"}}) + "\n\n"
        yield "data: [DONE]\n\n"
        return
    last_err = ""
    for provider, pid in chain:
        key = _pools[provider].next()
        try:
            if provider == "anthropic":
                async for line in _stream_anthropic(pid, messages, mtok, temperature, key or ""):
                    yield line
            else:
                async for line in _stream_openai_compat(provider, pid, messages, mtok,
                                                        temperature, key):
                    yield line
            circuit_note(provider, True)
            yield "data: [DONE]\n\n"
            return
        except Exception as e:  # noqa: BLE001
            last_err = f"{provider}: {type(e).__name__}: {str(e)[:150]}"
            circuit_note(provider, False)
            record_usage(provider, error=True)
            continue
    yield "data: " + json.dumps(
        {"error": {"message": f"all providers failed for '{model}': {last_err[:200]}",
                   "type": "providers_exhausted"}}) + "\n\n"
    yield "data: [DONE]\n\n"


async def _stream_openai_compat(provider: str, pid: str, messages: list[dict],
                                mtok: int, temperature: float, key: str | None):
    import queue
    import threading as _th

    base = PROVIDERS[provider]["base"]
    url = base.rstrip("/") + "/chat/completions"
    payload = _openai_payload(provider, pid, messages, mtok, temperature, True)
    q: queue.Queue = queue.Queue()
    err: list = []

    def _run():
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers=_openai_headers(provider, key), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=config.PROVIDER_TIMEOUT_S + 60) as r:  # noqa: S310
                if r.status != 200:
                    err.append(f"HTTP {r.status}")
                    q.put(None)
                    return
                buf = b""
                while True:
                    b = r.read(1)
                    if not b:
                        break
                    buf += b
                    while b"\n\n" in buf:
                        ev, buf = buf.split(b"\n\n", 1)
                        for ln in ev.decode("utf-8", "replace").splitlines():
                            if ln.startswith("data:"):
                                q.put(ln[len("data:"):].strip())
                q.put(None)
        except Exception as e:  # noqa: BLE001
            err.append(f"{type(e).__name__}: {str(e)[:150]}")
            q.put(None)

    _th.Thread(target=_run, daemon=True).start()
    pt = ct = 0
    got_any = False
    while True:
        item = await asyncio.to_thread(q.get)
        if item is None:
            break
        if item == "[DONE]":
            continue
        got_any = True
        try:
            chunk = json.loads(item)
            u = chunk.get("usage")
            if u:
                pt, ct = int(u.get("prompt_tokens") or pt), int(u.get("completion_tokens") or ct)
        except Exception:
            pass
        yield f"data: {item}\n\n"
    record_usage(provider, pt, ct)
    if not got_any:
        raise RuntimeError(err[0] if err else "empty stream")


async def _stream_anthropic(pid: str, messages: list[dict], mtok: int,
                            temperature: float, key: str):
    import queue
    import threading as _th

    body, version = _anthropic_payload(pid, messages, mtok, temperature, True)
    q: queue.Queue = queue.Queue()
    err: list = []

    def _run():
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "anthropic-version": version, "Accept": "text/event-stream",
                     "User-Agent": "kimi-super-agent/1.0"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=config.PROVIDER_TIMEOUT_S + 60) as r:  # noqa: S310
                if r.status != 200:
                    err.append(f"HTTP {r.status}: {r.read(200).decode('utf-8','replace')}")
                    q.put(None)
                    return
                buf = b""
                while True:
                    b = r.read(1)
                    if not b:
                        break
                    buf += b
                    while b"\n\n" in buf:
                        ev, buf = buf.split(b"\n\n", 1)
                        q.put(ev.decode("utf-8", "replace"))
                q.put(None)
        except Exception as e:  # noqa: BLE001
            err.append(f"{type(e).__name__}: {str(e)[:150]}")
            q.put(None)

    _th.Thread(target=_run, daemon=True).start()
    pt = ct = 0
    got_any = False
    while True:
        ev = await asyncio.to_thread(q.get)
        if ev is None:
            break
        etype, data = "", ""
        for ln in ev.splitlines():
            if ln.startswith("event:"):
                etype = ln[6:].strip()
            elif ln.startswith("data:"):
                data += ln[5:].strip()
        if not data:
            continue
        try:
            j = json.loads(data)
        except Exception:
            continue
        if etype == "content_block_delta" and (j.get("delta") or {}).get("text"):
            got_any = True
            yield "data: " + json.dumps(
                {"choices": [{"index": 0, "delta": {"content": j["delta"]["text"]}}]}) + "\n\n"
        elif etype == "message_delta" and j.get("usage"):
            ct = int(j["usage"].get("output_tokens") or ct)
        elif etype == "message_start" and (j.get("message") or {}).get("usage"):
            u = j["message"]["usage"]
            pt, ct = int(u.get("input_tokens") or pt), int(u.get("output_tokens") or ct)
    record_usage(provider := "anthropic", pt, ct)
    if not got_any:
        raise RuntimeError(err[0] if err else "empty stream")
