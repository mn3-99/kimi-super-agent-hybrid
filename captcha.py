"""Captcha TokenMinter — from nvidia-kimi-bridge/bridge.py with fixes:

FIX 1 (critical): original started the browser in FastAPI lifespan -> if the
playground is slow/blocked the WHOLE server never comes up. Now lazy: the
browser spawns on first mint(), healthz reports ready=false meanwhile.

FIX 2: overlay dismissal consolidated (OneTrust + AI-modal acknowledge) in one
evaluate, shared with the MCP OverlayKiller idea.

FIX 3: mint() serialised by lock, respawn bounded (3 tries), errors surfaced
via last_error for /healthz.
"""
from __future__ import annotations

import asyncio
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from config import PAGE_URL, UA

ACK_JS = """() => {
  const ack=[...document.querySelectorAll('button')]
    .find(b=>/acknowledge/i.test(b.innerText||''));
  if (ack && ack.offsetParent) { ack.click(); return 'ack'; }
  const ck=document.querySelector('#onetrust-accept-btn-handler');
  if (ck && ck.offsetParent) { ck.click(); return 'cookie'; }
  const ta=document.querySelector('textarea[aria-label="chat prompt"]');
  if (ta && window.hcaptcha && window.hcaptcha.execute) return 'READY';
  return 'waiting';
}"""

MINT_JS = """() => new Promise((resolve, reject) => {
    try {
        const id = window.hcaptcha.getRespKey();
        window.hcaptcha.reset(id);
        window.hcaptcha.execute(id, {async: true})
            .then(({response}) => resolve(response))
            .catch(err => reject(String(err)));
    } catch (e) { reject('JS: ' + e); }
})"""


class TokenMinter:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.pw = None
        self.browser = None
        self.ctx = None
        self.page = None
        self.ready = False
        self.last_error: str | None = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self.pw = await async_playwright().start()
        await self._spawn()

    async def ensure_started(self) -> None:
        if self.ready and self.page is not None:
            return
        if self.pw is None:
            from playwright.async_api import async_playwright

            self.pw = await async_playwright().start()
        await self._spawn()

    async def _spawn(self) -> None:
        await self._teardown()
        assert self.pw is not None
        self.browser = await self.pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"],
        )
        self.ctx = await self.browser.new_context(
            viewport={"width": 1400, "height": 900}, user_agent=UA
        )
        # stealth + overlay pre-seed (MCP OverlayKiller idea, compact)
        await self.ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            "window.chrome=window.chrome||{runtime:{}};"
            "try{document.cookie='OptanonAlertBoxClosed='+new Date(Date.now()+365*24*3600*1000).toUTCString()+'; path=/;';"
            "localStorage.setItem('ai-disclaimer-acknowledged','true');}catch(e){}"
        )
        self.page = await self.ctx.new_page()
        await self.page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
        st = "waiting"
        for _ in range(30):
            await self.page.wait_for_timeout(1500)
            try:
                st = await self.page.evaluate(ACK_JS)
            except Exception:
                st = "nav"
            if st == "READY":
                break
        if st != "READY":
            raise RuntimeError(f"playground never became READY (last={st})")
        self.ready = True
        self.last_error = None

    async def _teardown(self) -> None:
        self.ready = False
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = self.ctx = self.page = None

    async def mint(self) -> str:
        async with self.lock:
            last = None
            for _ in range(3):
                if not self.ready:
                    try:
                        await self.ensure_started()
                    except Exception as e:
                        last = f"respawn: {e}"
                        self.last_error = last
                        continue
                try:
                    token = await self.page.evaluate(MINT_JS)
                    if token:
                        return token
                    last = "empty token"
                except Exception as e:
                    last = f"execute: {e}"
                    try:
                        await self._spawn()
                    except Exception as e2:
                        self.last_error = f"respawn failed: {e2}"
            raise RuntimeError(f"captcha mint failed: {last}")

    async def screenshot(self) -> bytes | None:
        try:
            if self.page is None:
                return None
            return await self.page.screenshot(full_page=False)
        except Exception:
            return None

    async def close(self) -> None:
        await self._teardown()
        if self.pw:
            try:
                await self.pw.stop()
            except Exception:
                pass
            self.pw = None


minter = TokenMinter()
