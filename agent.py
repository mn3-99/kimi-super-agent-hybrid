"""Super coding agent CLI — the 'strongest agent' loop.

Uses ANY OpenAI-compatible endpoint (default: local server_openai on :8000,
which bridges free NVIDIA Kimi K3). Tools: read/write/list files, shell,
web_fetch, swarm fan-out. ReAct loop with JSON tool calls, streaming live
display (reasoning first, then answer), step cap, transcript saving.

Usage:
  python agent.py "ابنِ تطبيق TODO بـ Flask" [--model ...] [--base-url ...]
  python agent.py --swarm "instruction" item1 item2 ...   # one-shot swarm
  python agent.py --chat "سؤال سريع"                     # one-shot chat
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

_sys_dir = os.path.dirname(os.path.abspath(__file__))
if _sys_dir not in sys.path:
    sys.path.insert(0, _sys_dir)

import config
import tools_code

SYSTEM_PROMPT = """You are Kimi-Super-Agent, an elite senior software engineer (2026).
Rules:
1. Think in reasoning first (short), then act.
2. Prefer reading files before editing; verify with tests/shell.
3. Batch independent tool calls in ONE block.
4. Never invent file contents — read them.
5. Finish with: SUMMARY, FILES CHANGED, TESTS, HOW TO RUN.
Workspace root is the current directory. Keep outputs tight.
Available tools (call as {"tool":..., "args":{...}} inside ```tool_json fenced blocks, one JSON per block):
- read_file {path, limit?, offset?}
- write_file {path, content}
- list_files {path?, pattern?}
- run_shell {cmd, timeout_s?}
- web_fetch {url}
- swarm_run {instruction, items: [...], model?}  (parallel workers)
Return final answer as plain text (no tool_json) when done.
"""

TOOL_GUIDE = """
TOOLS (JSON in ```tool_json blocks):
{"tool":"read_file","args":{"path":"..."}}
{"tool":"write_file","args":{"path":"...","content":"..."}}
{"tool":"list_files","args":{"path":".","pattern":"**/*.py"}}
{"tool":"run_shell","args":{"cmd":"pytest -q"}}
{"tool":"web_fetch","args":{"url":"https://..."}}
{"tool":"swarm_run","args":{"instruction":"...","items":["a","b"]}}
"""


def _client(base_url: str, api_key: str):
    from openai import OpenAI

    return OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)


def _extract_tool_blocks(text: str) -> list[dict]:
    out = []
    # Primary: ```tool_json blocks (agent convention). Fallback: ```json blocks
    # that contain a {"tool": ...} object (models often emit plain json).
    for fence in ("```tool_json", "```json"):
        parts = text.split(fence)
        for p in parts[1:]:
            body = p.split("```", 1)[0].strip()
            try:
                obj = json.loads(body)
            except Exception:
                continue
            if isinstance(obj, dict) and "tool" in obj:
                out.append(obj)
            elif fence == "```tool_json" and isinstance(obj, dict):
                # tolerate tool_json without explicit "tool" key check above;
                # _run_tool will report unknown tool.
                out.append(obj)
    # de-dup: if both fences matched the same block, keep first occurrence order.
    seen: set[str] = set()
    uniq: list[dict] = []
    for o in out:
        k = json.dumps(o, sort_keys=True, ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            uniq.append(o)
    return uniq


async def _run_tool(name: str, args: dict, swarm_model: str) -> str:
    try:
        if name == "read_file":
            return tools_code.read_file(args.get("path", ""), int(args.get("limit", 200)),
                                        int(args.get("offset", 1)))
        if name == "write_file":
            return tools_code.write_file(args.get("path", ""), args.get("content", ""))
        if name == "list_files":
            return json.dumps(tools_code.list_files(args.get("path", "."),
                                                    args.get("pattern", "*")))
        if name == "run_shell":
            r = await tools_code.run_shell(args.get("cmd", "echo hi"),
                                           float(args.get("timeout_s", 120)))
            return f"exit={r['code']}\n{r['output']}"
        if name == "web_fetch":
            return tools_code.web_fetch(args.get("url", ""))
        if name == "swarm_run":
            from swarm import swarm_run
            from upstream import chat_once

            items = args.get("items", [])
            if isinstance(items, str):
                items = [l for l in items.splitlines() if l.strip()]
            out = await swarm_run(args.get("instruction", ""), items,
                                  model=args.get("model", swarm_model),
                                  chat_fn=lambda m, mo, t: chat_once(m, model=mo, timeout_s=t))
            return (out.get("report", "") + "\n\nRAW:\n" +
                    json.dumps(out.get("results", []), ensure_ascii=False)[:8000])
        return f"unknown tool: {name}"
    except Exception as e:
        return f"TOOL ERROR {name}: {type(e).__name__}: {e}"


async def run_agent(task: str, model: str, base_url: str, api_key: str,
                    max_steps: int, stream: bool = True) -> str:
    client = _client(base_url, api_key)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task + "\n" + TOOL_GUIDE}]
    transcript: list[str] = []
    for step in range(1, max_steps + 1):
        print(f"\n===== step {step}/{max_steps} =====", flush=True)
        t0 = time.time()
        if stream:
            chunks = client.chat.completions.create(model=model, messages=messages,
                                                    stream=True, max_tokens=4096)
            text_acc: list[str] = []
            reason_acc: list[str] = []
            state = None
            for ch in chunks:
                if not ch.choices:
                    continue
                d = ch.choices[0].delta
                rc = getattr(d, "reasoning_content", None) or (
                    (d.model_extra or {}).get("reasoning_content") if getattr(d, "model_extra", None) else None)
                cc = d.content
                if rc:
                    if state != "think":
                        state = "think"
                        print(f"[{time.time()-t0:6.1f}s] thinking…")
                    print(rc, end="", flush=True)
                    reason_acc.append(rc)
                if cc:
                    if state != "ans":
                        state = "ans"
                        print(f"\n[{time.time()-t0:6.1f}s] answer/tools…")
                    print(cc, end="", flush=True)
                    text_acc.append(cc)
            print()
            text = "".join(text_acc)
            if reason_acc:
                print(f"[reasoning {sum(map(len, reason_acc))} chars captured]")
        else:
            resp = client.chat.completions.create(model=model, messages=messages,
                                                  stream=False, max_tokens=4096)
            text = resp.choices[0].message.content or ""
        transcript.append(text)
        calls = _extract_tool_blocks(text)
        # strip tool blocks for display of final answer
        if not calls:
            print("\n===== FINAL =====")
            print(text)
            return text
        messages.append({"role": "assistant", "content": text})
        for c in calls:
            tool = c.get("tool", "")
            args = c.get("args", {})
            print(f"\n[tool] {tool} {json.dumps(args, ensure_ascii=False)[:300]}")
            res = await _run_tool(tool, args, model)
            print(f"[tool-result {len(res)} chars] {res[:1500]}")
            messages.append({"role": "user",
                             "content": f"TOOL RESULT ({tool}):\n{res[:12000]}"})
    return "\n".join(transcript)


async def one_shot_chat(prompt: str, model: str, base_url: str, api_key: str) -> None:
    from upstream import chat_once

    if base_url.rstrip("/").endswith("/v1") and ":8000" in base_url:
        client = _client(base_url, api_key)
        s = client.chat.completions.create(model=model,
                                           messages=[{"role": "user", "content": prompt}],
                                           stream=True)
        for ch in s:
            if ch.choices and ch.choices[0].delta.content:
                print(ch.choices[0].delta.content, end="", flush=True)
        print()
    else:
        out = await chat_once([{"role": "user", "content": prompt}], model=model)
        print((out.get("reasoning") or "")[:2000])
        print(out.get("content", ""))


def main() -> None:
    ap = argparse.ArgumentParser(description="Kimi super agent")
    ap.add_argument("task", nargs="?", default="", help="task text")
    ap.add_argument("--model", default=os.getenv("AGENT_MODEL", config.AGENT_MODEL))
    ap.add_argument("--base-url", default=os.getenv("AGENT_BASE_URL", config.AGENT_BASE_URL))
    ap.add_argument("--api-key", default=os.getenv("AGENT_API_KEY", config.AGENT_API_KEY))
    ap.add_argument("--max-steps", type=int, default=config.AGENT_MAX_STEPS)
    ap.add_argument("--no-stream", action="store_true")
    ap.add_argument("--chat", action="store_true", help="one-shot chat instead of agent loop")
    ap.add_argument("--swarm", action="store_true", help="one-shot swarm: --swarm INSTR item...")
    ap.add_argument("--swarm-items", nargs="*", default=[])
    args = ap.parse_args()

    if args.swarm:
        if not args.task:
            print("usage: agent.py --swarm 'instruction' item1 item2 ...", file=sys.stderr)
            sys.exit(2)
        from swarm import swarm_run
        from upstream import chat_once

        async def _go():
            out = await swarm_run(args.task, args.swarm_items or sys.stdin.read().splitlines(),
                                  model=args.model,
                                  chat_fn=lambda m, mo, t: chat_once(m, model=mo, timeout_s=t))
            print(out["report"])
            print(json.dumps(out["results"], ensure_ascii=False, indent=1)[:6000])
        asyncio.run(_go())
        return
    if args.chat or (args.task and args.max_steps == 0):
        asyncio.run(one_shot_chat(args.task, args.model, args.base_url, args.api_key))
        return
    if not args.task:
        ap.print_help()
        sys.exit(2)
    asyncio.run(run_agent(args.task, args.model, args.base_url, args.api_key,
                          args.max_steps, stream=not args.no_stream))


if __name__ == "__main__":
    main()
