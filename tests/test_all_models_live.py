"""Live test: same LONG programming prompt against every curated model.

Saves incremental results to MODEL_TESTS.md + model_tests_raw.json so a
timeout never loses partial progress. Run from kimi-super-agent/:

    python3 tests/test_all_models_live.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CURATED_MODELS  # noqa: E402

LONG_PROMPT = """أنت مهندس برمجيات أول (Staff Engineer). نفذ المهمة التالية كاملة ودقيقة:

بناء REST API لإدارة المهام (Task Manager) بلغة Python مع FastAPI وSQLite.

المتطلبات الوظيفية:
1. نموذج Task: id (UUID)، title (مطلوب، 3-200 حرف)، description (اختياري حتى 2000 حرف)،
   status (todo/doing/done)، priority (1-5)، due_date (اختياري ISO-8601)،
   created_at و updated_at (UTC تلقائياً).
2. نقاط النهاية: POST /tasks (إنشاء، 201)، GET /tasks (قائمة مع pagination:
   page/page_size حتى 100، وفلترة status و priority وبحث title)،
   GET /tasks/{id}، PATCH /tasks/{id} (تحديث جزئي)، DELETE /tasks/{id} (204)،
   GET /health (يرجع {"status":"ok"}).
3. التحقق: عنوان قصير جداً أو أولوية خارج 1-5 → 422 مع رسالة واضحة.
   معرف غير موجود → 404 بصيغة {"detail": "..."}. لا تكشف stack traces (500 نظيفة).
4. قاعدة البيانات: SQLite عبر SQLAlchemy 2.0، إنشاء الجداول عند الإقلاع،
   جلسة لكل طلب مع إغلاق آمن. منع SQL injection عبر ORM حصراً.
5. الجودة: اكتب ملف main.py كاملاً يعمل، وملف test_main.py بثلاثة اختبارات
   (إنشاء مهمة، فلترة، 404)، وDockerfile متعدد المراحل، وقسم "كيف تشغل"
   بأوامر النسخ واللصق. اذكر حالتين حديتين (edge cases) وكيف عالجتهما.

قيود الإجابة: ابدأ بشرح معماري مختصر (5 أسطر كحد أقصى) ثم الكود الكامل،
ثم الاختبارات، ثم التشغيل. لا تخرج عن المطلوب ولا تخترع مكتبات غير قياسية
خارج fastapi/sqlalchemy/pytest/uvicorn.
"""

MAX_TOKENS = 1024
PER_MODEL_TIMEOUT = 260.0
OUT_MD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "MODEL_TESTS.md")
OUT_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model_tests_raw.json")


async def test_one(model: str) -> dict:
    from upstream import chat_once

    t0 = time.time()
    try:
        out = await chat_once(
            [{"role": "user", "content": LONG_PROMPT}],
            model=model, timeout_s=PER_MODEL_TIMEOUT, max_tokens=MAX_TOKENS,
        )
        dt = time.time() - t0
        content = out.get("content") or ""
        reasoning = out.get("reasoning") or ""
        checks = {
            "has_fastapi": "fastapi" in content.lower(),
            "has_endpoint": ("/tasks" in content),
            "has_test": ("pytest" in content.lower() or "testclient" in content.lower() or "def test" in content),
            "has_docker": ("dockerfile" in content.lower() or "from python" in content.lower()),
            "arabic_or_english": True,
        }
        return {"model": model, "ok": True, "seconds": round(dt, 1),
                "content_chars": len(content), "reasoning_chars": len(reasoning),
                "usage": out.get("usage"), "checks": checks,
                "excerpt": content[:600]}
    except Exception as e:  # noqa: BLE001
        return {"model": model, "ok": False, "seconds": round(time.time() - t0, 1),
                "error": f"{type(e).__name__}: {str(e)[:300]}"}


def write_reports(results: list[dict]) -> None:
    ok = sum(1 for r in results if r.get("ok"))
    lines = ["# نتائج اختبار السؤال البرمجي الطويل (موحد لكل الموديلات)",
             "",
             f"التاريخ (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} — "
             f"الناجح: {ok}/{len(results)} — السؤال: REST API للمهام (FastAPI/SQLite) — "
             f"max_tokens={MAX_TOKENS}",
             "",
             "| الموديل | الحالة | الزمن (ث) | المحتوى (حرف) | التفكير (حرف) | fastapi | /tasks | tests | docker |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("ok"):
            c = r["checks"]
            lines.append(f"| {r['model']} | OK | {r['seconds']} | {r['content_chars']} | "
                         f"{r['reasoning_chars']} | {'✅' if c['has_fastapi'] else '❌'} | "
                         f"{'✅' if c['has_endpoint'] else '❌'} | {'✅' if c['has_test'] else '❌'} | "
                         f"{'✅' if c['has_docker'] else '❌'} |")
        else:
            lines.append(f"| {r['model']} | FAIL | {r['seconds']} | — | — | — | — | — | — |")
    lines += ["", "## مقتطفات", ""]
    for r in results:
        lines.append(f"### {r['model']}")
        if r.get("ok"):
            lines.append(f"- زمن: {r['seconds']}s — محتوى: {r['content_chars']} حرف "
                         f"— تفكير: {r['reasoning_chars']} حرف — usage: {r.get('usage')}")
            lines.append("```")
            lines.append((r.get("excerpt") or "")[:600])
            lines.append("```")
        else:
            lines.append(f"- FAIL: {r.get('error')}")
        lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)


async def main() -> None:
    from captcha import minter

    results: list[dict] = []
    try:
        with open(OUT_JSON, encoding="utf-8") as f:
            prev = json.load(f)
        done = {r["model"] for r in prev if r.get("ok")}
        print(f"resuming: {len(done)} already OK, skipping", flush=True)
    except Exception:
        done = set()
    try:
        for i, model in enumerate(CURATED_MODELS, 1):
            if model in done:
                prev_r = next(r for r in prev if r["model"] == model)
                results.append(prev_r)
                continue
            print(f"[{i}/{len(CURATED_MODELS)}] testing {model} ...", flush=True)
            r = await test_one(model)
            results.append(r)
            if r.get("ok"):
                print(f"  OK in {r['seconds']}s content={r['content_chars']} reasoning={r['reasoning_chars']}",
                      flush=True)
            else:
                print(f"  FAIL: {r.get('error')}", flush=True)
            write_reports(results)
    finally:
        await minter.close()
    ok = sum(1 for r in results if r.get("ok"))
    print(f"\nDONE: {ok}/{len(results)} models OK -> MODEL_TESTS.md", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
