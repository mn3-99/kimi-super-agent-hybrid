"""Offline unit tests — no network, no browser. Must ALL pass.

Covers the merged logic:
- SSE parsing incl. reasoning_content (the TS DirectClient dropped it; we keep it)
- payload builder defaults
- RateLimiter concurrency fix (N parallel acquires respect the window)
- swarm ordering/concurrency/errors with a MOCK chat_fn
- model alias resolution (pure)
- tool sandbox (path guard)
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, "/content/kimi-super-agent")

from network import extract_deltas, parse_sse_stream  # noqa: E402
from upstream import RateLimiter, build_upstream_payload  # noqa: E402
from swarm import swarm_run  # noqa: E402
from config import ALIASES  # noqa: E402


def test_sse_reasoning_kept():
    body = (
        'data: {"choices":[{"delta":{"reasoning_content":"think1"}}],"usage":null}\n\n'
        'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}\n\n'
        "data: [DONE]\n\n"
    )
    p = parse_sse_stream(body)
    assert p.reasoning == "think1", p.reasoning
    assert p.content == "hello world", p.content
    assert p.usage.total_tokens == 8
    assert p.finish_reason == "stop"
    print("ok sse_reasoning_kept")


def test_extract_deltas_bad_input():
    assert extract_deltas("not json") == ("", "", None, None)
    assert extract_deltas('{"choices":[]}')[0] == ""
    print("ok extract_deltas_bad_input")


def test_payload_defaults():
    entry = {"slug": "moonshotai/kimi-k3", "namespace": "x", "fn": "y", "name": "kimi-k3"}
    pl = build_upstream_payload({"messages": [{"role": "user", "content": "hi"}]}, entry)
    assert pl["reasoning_effort"] == "max", pl
    assert pl["stream"] is True and pl["model"] == "moonshotai/kimi-k3"
    pl2 = build_upstream_payload(
        {"messages": [], "reasoning_effort": "low", "top_p": 0.5}, entry)
    assert pl2["reasoning_effort"] == "low" and pl2["top_p"] == 0.5
    print("ok payload_defaults")


def test_aliases():
    assert ALIASES["kimi-k3"] == "moonshotai/kimi-k3"
    print("ok aliases")


async def _limiter_case():
    lim = RateLimiter(per_min=3)
    t0 = time.monotonic()
    await asyncio.gather(*(lim.acquire() for _ in range(3)))
    assert time.monotonic() - t0 < 5, "first 3 must be instant"
    # 4th must wait for window; we shorten by hacking stamps to be old
    lim.stamps.clear()
    for _ in range(3):
        lim.stamps.append(time.monotonic() - 61)  # expired
    t0 = time.monotonic()
    await lim.acquire()
    assert time.monotonic() - t0 < 5, "expired stamps must not block"
    print("ok limiter")


async def _swarm_case():
    concurrent = 0
    peak = 0

    async def mock_chat(messages, model, timeout):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        item = messages[1]["content"]
        concurrent -= 1
        if item == "boom":
            raise RuntimeError("worker fail")
        return {"content": f"OUT:{item}", "reasoning": "r", "usage": None}

    async def mock_synth(messages, model, timeout):
        # synthesis call has different system prompt; detect it
        if "assemble" in messages[0]["content"]:
            return {"content": "REPORT", "reasoning": "", "usage": None}
        return await mock_chat(messages, model, timeout)

    # route: swarm calls chat_fn for workers AND synthesis; wrap both
    calls = {"n": 0}

    async def router(messages, model, timeout):
        calls["n"] += 1
        if messages[0].get("role") == "system" and "assemble" in messages[0]["content"]:
            return {"content": "REPORT", "reasoning": "", "usage": None}
        return await mock_chat(messages, model, timeout)

    out = await swarm_run("do X", ["a", "boom", "c"], model="m",
                          max_concurrency=2, budget_s=60,
                          chat_fn=router)
    assert out["total"] == 3 and out["ok"] == 2 and out["failed"] == 1, out
    assert [r["item"] for r in out["results"]] == ["a", "boom", "c"], "ordered!"
    assert out["results"][0]["content"] == "OUT:a"
    assert not out["results"][1]["ok"] and "fail" in out["results"][1]["error"]
    assert out["report"] == "REPORT"
    assert peak <= 2, f"concurrency violated: peak={peak}"
    print(f"ok swarm (peak={peak}, calls={calls['n']})")


def test_tools_sandbox():
    import tools_code

    try:
        tools_code.read_file("../../etc/passwd")
        # /etc/passwd is outside ROOT and outside /tmp -> must raise
        raise AssertionError("path guard failed")
    except PermissionError:
        pass
    print("ok tools_sandbox")


def test_tools_root_defaults_to_package_dir():
    # REGRESSION: ROOT used to default to os.getcwd() -> broke when cwd != package.
    import os
    import tools_code

    assert str(tools_code.ROOT).endswith("kimi-super-agent"), tools_code.ROOT
    # must work regardless of cwd
    cwd = os.getcwd()
    try:
        os.chdir("/tmp")
        txt = tools_code.read_file("config.py", limit=2)
        assert "Unified configuration" in txt, txt[:100]
    finally:
        os.chdir(cwd)
    print("ok tools_root")


def test_agent_tool_fences():
    from agent import _extract_tool_blocks

    a = _extract_tool_blocks('x ```tool_json\n{"tool":"read_file","args":{"path":"a"}}\n``` y')
    b = _extract_tool_blocks('x ```json\n{"tool":"read_file","args":{"path":"a"}}\n``` y')
    assert a and a[0]["tool"] == "read_file", a
    assert b and b[0]["tool"] == "read_file", b
    print("ok agent_tool_fences")


async def _main():
    test_sse_reasoning_kept()
    test_extract_deltas_bad_input()
    test_payload_defaults()
    test_aliases()
    await _limiter_case()
    await _swarm_case()
    test_tools_sandbox()
    test_tools_root_defaults_to_package_dir()
    test_agent_tool_fences()
    print("\nALL OFFLINE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
