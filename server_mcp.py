"""MCP server — superset of nvidia-kimi-mcp TS tools.

Old TS tools: send_message / get_response / screenshot (3).
New tools (8): chat, swarm_run, read_file, write_file, run_shell,
               web_fetch, models, screenshot.

Run (stdio):  python server_mcp.py
Config for Claude/Desktop: {"command":"python","args":["/content/kimi-super-agent/server_mcp.py"]}
Env: AGENT_BASE_URL -> upstream OpenAI endpoint (default local :8000),
     or DIRECT=1 to call NVIDIA directly without a running server.
"""
from __future__ import annotations

import json
import os
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="kimi-super-agent", version="1.0.0")


def _direct_mode() -> bool:
    return os.getenv("DIRECT", "0").strip().lower() in {"1", "true", "yes"}


async def _chat_via_http(messages: list[dict], model: str, timeout_s: float) -> dict:
    import urllib.request

    base = os.getenv("AGENT_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    key = os.getenv("AGENT_API_KEY", "local")
    req_body = {"model": model, "messages": messages, "stream": False,
                "max_tokens": 4096}
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(req_body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    import asyncio

    def _do():
        with urllib.request.urlopen(req, timeout=timeout_s + 30) as r:  # noqa: S310
            return json.loads(r.read().decode())
    data = await asyncio.to_thread(_do)
    msg = data["choices"][0]["message"]
    return {"content": msg.get("content", ""),
            "reasoning": msg.get("reasoning_content", ""),
            "model": data.get("model", model)}


@server.tool(description="Chat with Kimi K3 (reasoning + answer). Replaces send_message/get_response pair.")
async def chat(message: str, system: str = "", model: str = "moonshotai/kimi-k3",
               timeout_s: float = 420) -> str:
    """Send one message, wait for the full reasoning+answer, return JSON."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": message})
    try:
        if _direct_mode():
            from upstream import chat_once

            out = await chat_once(messages, model=model, timeout_s=timeout_s)
        else:
            out = await _chat_via_http(messages, model, timeout_s)
    except Exception as e:
        return json.dumps({"content": "", "reasoning": "",
                           "error": f"{type(e).__name__}: {e}",
                           "model": model}, ensure_ascii=False)
    return json.dumps(out, ensure_ascii=False)


@server.tool(description="Parallel AgentSwarm fan-out: one instruction x many items -> ordered results + report.")
async def swarm_run(instruction: str, items: str, model: str = "moonshotai/kimi-k3",
                    max_concurrency: int = 8) -> str:
    """items: JSON array of strings OR newline-separated text."""
    try:
        parsed = json.loads(items)
        item_list = parsed if isinstance(parsed, list) else [str(parsed)]
    except Exception:
        item_list = [l for l in items.splitlines() if l.strip()]
    from swarm import swarm_run as _run

    async def _chat(messages: list[dict], model_: str, timeout: float) -> dict:
        if _direct_mode():
            from upstream import chat_once

            return await chat_once(messages, model=model_, timeout_s=timeout)
        return await _chat_via_http(messages, model_, timeout)

    out = await _run(instruction, [str(x) for x in item_list], model=model,
                     max_concurrency=max_concurrency, chat_fn=_chat)
    return json.dumps(out, ensure_ascii=False)[:120_000]


@server.tool(description="Read a workspace file with line numbers.")
async def read_file(path: str, limit: int = 200, offset: int = 1) -> str:
    from tools_code import read_file as _r

    return _r(path, limit, offset)


@server.tool(description="Write (create/overwrite) a workspace file.")
async def write_file(path: str, content: str) -> str:
    from tools_code import write_file as _w

    return _w(path, content)


@server.tool(description="Run a shell command (timeout, truncated output).")
async def run_shell(cmd: str, timeout_s: float = 120) -> str:
    from tools_code import run_shell as _s

    return json.dumps(await _s(cmd, timeout_s), ensure_ascii=False)


@server.tool(description="Fetch a URL (text, truncated).")
async def web_fetch(url: str) -> str:
    from tools_code import web_fetch as _f

    return _f(url)


@server.tool(description="List curated + aliased models.")
async def models() -> str:
    from config import ALIASES, CURATED_MODELS

    return json.dumps({"models": CURATED_MODELS, "aliases": ALIASES}, ensure_ascii=False)


@server.tool(description="Live playground screenshot (PNG base64) — MCP parity with TS version.")
async def screenshot() -> str:
    import base64

    from captcha import minter

    try:
        await minter.ensure_started()
    except Exception as e:
        return json.dumps({"success": False, "error": f"browser unavailable: {e}"})
    shot = await minter.screenshot()
    if not shot:
        return json.dumps({"success": False, "error": "screenshot failed"})
    return json.dumps({"success": True, "size": len(shot),
                       "data": base64.b64encode(shot).decode()})


async def _main() -> None:
    await server.run_stdio_async()


def main() -> None:
    import asyncio

    asyncio.run(_main())


if __name__ == "__main__":
    main()
