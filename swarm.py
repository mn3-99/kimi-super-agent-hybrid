"""AgentSwarm — the missing swarm-kimi, re-implemented.

Pattern (Kimi K2.5/K3 Swarm style): ONE instruction x MANY items -> parallel
workers (bounded concurrency) -> ordered results -> synthesis pass into a
single markdown report.

- Bounded parallelism via asyncio.Semaphore (default 8).
- Hard wall-clock budget (default 1800s) + per-item timeout.
- One retry for transient errors, errors captured per-item (never fail all).
- chat_fn injectable -> unit-testable offline; defaults to upstream.chat_once.
"""
from __future__ import annotations

import asyncio
import os as _os
import sys as _sys
import time
from typing import Any, Awaitable, Callable

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))


async def _default_chat(messages: list[dict], model: str, timeout_s: float) -> dict:
    from upstream import chat_once

    return await chat_once(messages, model=model, timeout_s=timeout_s)


async def swarm_run(
    instruction: str,
    items: list[str],
    model: str = "moonshotai/kimi-k3",
    max_concurrency: int = 8,
    timeout_per_item_s: float = 420.0,
    budget_s: float = 1800.0,
    synthesize: bool = True,
    chat_fn: Callable[..., Awaitable[dict]] | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> dict:
    if not items:
        raise ValueError("items[] must not be empty")
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    chat = chat_fn or _default_chat
    sem = asyncio.Semaphore(max_concurrency)
    deadline = time.monotonic() + budget_s
    results: list[dict[str, Any]] = [None] * len(items)  # type: ignore

    async def one(idx: int, item: str) -> None:
        async with sem:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                results[idx] = {"item": item, "ok": False, "error": "budget-exceeded"}
                return
            timeout = min(timeout_per_item_s, remaining)
            msgs = [
                {"role": "system", "content": instruction},
                {"role": "user", "content": item},
            ]
            last_err = ""
            for attempt in (1, 2):
                try:
                    out = await chat(msgs, model, timeout)
                    results[idx] = {
                        "item": item, "ok": True,
                        "content": out.get("content", ""),
                        "reasoning": out.get("reasoning", ""),
                        "usage": out.get("usage"),
                    }
                    break
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                    if attempt == 2:
                        results[idx] = {"item": item, "ok": False, "error": last_err}
            if progress_cb:
                try:
                    done = sum(1 for r in results if r is not None)
                    progress_cb(done, len(items), item[:60])
                except Exception:
                    pass

    await asyncio.gather(*(one(i, it) for i, it in enumerate(items)))
    ok = sum(1 for r in results if r and r.get("ok"))
    report = ""
    if synthesize:
        try:
            bulk = "\n\n---\n\n".join(
                f"### item {i+1}\nINPUT: {r['item']}\n\n"
                f"{(r.get('content') or ('ERROR: '+r.get('error','')))[:4000]}"
                for i, r in enumerate(results)
            )
            synth_msgs = [
                {"role": "system",
                 "content": "You assemble parallel worker outputs into ONE concise "
                            "markdown report: summary, per-item key findings, open "
                            "questions. No fluff."},
                {"role": "user",
                 "content": f"TASK: {instruction}\n\nWORKER OUTPUTS:\n{bulk[:30000]}"},
            ]
            remaining = max(60.0, deadline - time.monotonic())
            s = await chat(synth_msgs, model, min(300.0, remaining))
            report = s.get("content", "")
        except Exception as e:
            report = f"_synthesis failed: {e}_"
    return {
        "model": model,
        "instruction": instruction,
        "total": len(items),
        "ok": ok,
        "failed": len(items) - ok,
        "results": results,
        "report": report,
    }
