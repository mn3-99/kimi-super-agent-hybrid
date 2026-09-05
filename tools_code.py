"""Local coding tools shared by the agent CLI and the MCP server.

Fast + safe defaults: path traversal guard (ROOT), shell timeout, output cap.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys as _sys

_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = pathlib.Path(os.getenv("AGENT_ROOT", str(pathlib.Path(__file__).resolve().parent))).resolve()
MAX_OUTPUT = 60_000


def _safe(path: str) -> pathlib.Path:
    p = (ROOT / path).resolve() if not os.path.isabs(path) else pathlib.Path(path).resolve()
    try:
        p.relative_to(ROOT)
    except ValueError:
        # allow /tmp explicitly for artefacts
        if not str(p).startswith("/tmp/"):
            raise PermissionError(f"path outside workspace: {path}")
    return p


def read_file(path: str, limit: int = 400, offset: int = 1) -> str:
    p = _safe(path)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    sel = lines[offset - 1: offset - 1 + limit]
    return "\n".join(f"{i+offset}:{l}" for i, l in enumerate(sel))


def write_file(path: str, content: str) -> str:
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {p}"


def list_files(path: str = ".", pattern: str = "*") -> list[str]:
    import glob as _glob

    base = _safe(path)
    return sorted(str(pathlib.Path(f).relative_to(ROOT))
                  if str(f).startswith(str(ROOT)) else f
                  for f in _glob.glob(str(base / pattern), recursive="**" in pattern))


async def run_shell(cmd: str, timeout_s: float = 120.0) -> dict:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=str(ROOT)
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return {"code": 124, "output": f"timeout after {timeout_s}s"}
    text = out.decode("utf-8", "replace")
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + f"\n...[truncated {len(text)-MAX_OUTPUT} chars]"
    return {"code": proc.returncode, "output": text}


def web_fetch(url: str, timeout_s: float = 30.0) -> str:
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "kimi-super-agent/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:  # noqa: S310
        raw = r.read(300_000).decode("utf-8", "replace")
    return raw[:MAX_OUTPUT]
