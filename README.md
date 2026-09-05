# Kimi Super Agent — وكيل برمجي احترافي موحّد (2026)

دمج دقيق لمشروعين:
- **nvidia-kimi-mcp** (TypeScript MCP + Python helpers) — أدوات MCP، عميل Direct، بروكسي OpenAI
- **nvidia-kimi-bridge** (Python FastAPI) — جسر OpenAI-compat لبناء NVIDIA المجاني

> ملاحظة: رابط `swarm-kimi` المذكور في الطلب الأصلي **غير موجود** على GitHub
> (404 — تحققنا عبر API أن المستخدم `mn3-99` يملك فقط `nvidia-kimi-mcp` و `nvidia-kimi-bridge`
> من أصل 14 مستودعاً). لذلك أُعيد تنفيذ مكوّن الـ Swarm من الصفر بنمط Kimi Swarm
> (تعليمة واحدة × عناصر كثيرة → عمّال متوازيون → تقرير مُجمّع).

## لماذا هذا الدمج أقوى من الأصلين؟

| المشكلة في الأصل | الإصلاح هنا |
|---|---|
| `DirectClient.ts` يُسقط `reasoning_content` (يجمع `content` فقط) | `network.py` + `upstream.py` يحافظان على التفكير والنص معاً — تحققنا سطراً بسطر |
| `openai-proxy.ts` يُزيّف البث (تقطيع 80 حرفاً، بلا تفكير) | `server_openai.py` تمرير SSE حقيقي من أول بايت مع `reasoning_content` |
| `bridge.py: RateLimiter` ينام **داخل** الـ Lock (يُسلسل كل الطلبات حتى 60s) | `upstream.py: RateLimiter` يحسب الانتظار داخل القفل وينام **خارجه** |
| `bridge.py: lifespan` يفتح المتصفح عند الإقلاع (السيرفر لا يقوم لو الصفحة بطيئة) | `captcha.py` بدء كسول: السيرفر يقوم فوراً، `healthz` يبلّغ `ready=false` حتى أول `mint()` |
| `Page.screenshot(fullPage=)` (camelCase) يُرجع `None` دائماً في Python | إصلاح إلى `full_page=False` — تحققنا: كان 0 بايت، أصبح ~190KB |
| `tools_code.ROOT` كان `os.getcwd()` (ينكسر خارج المجلد) | الافتراضي الآن مجلد الحزمة نفسها |
| الـ agent كان يفهم ` ```tool_json ` فقط | يفهم ` ```tool_json ` و ` ```json ` مع إزالة التكرار |
| `non_stream` بلا مهلة (قد يعلّق للأبد) | مهلة 300s تُرجع `504 bridge_timeout` |
| `kimi-k3` مع `reasoning_effort=max` يُرجع أحياناً `500 Retries exhausted` تحت الضغط | تراجع تلقائي: إعادة المحاولة بدون `reasoning_effort` (تحققنا حياً) |
| MCP الأصلي: 3 أدوات فقط | MCP الجديد: **8 أدوات** (chat, swarm_run, read/write/shell/fetch/models/screenshot) |

## البنية

```
kimi-super-agent/
  config.py        # إعدادات موحدة + .env + أسماء مستعارة + كتالوج 10 موديلات
  captcha.py       # TokenMinter كسول (Playwright) — دمج OverlayKiller + stealth
  network.py       # تحليل SSE (port مطابق للأصل + extract_deltas)
  upstream.py      # resolver + RateLimiter + payload + pump_upstream + chat_once
  swarm.py         # AgentSwarm (الجديد — بديل swarm-kimi المفقود)
  tools_code.py    # أدوات محلية (read/write/list/shell/fetch) بحارس مسارات
  server_openai.py # سيرفر OpenAI-compat (stream حقيقي + swarm + screenshot)
  server_mcp.py    # سيرفر MCP (8 أدوات، DIRECT=1 أو عبر HTTP)
  agent.py         # وكيل CLI (ReAct + بث حي + swarm)
  tests/           # offline (بلا شبكة) + live (شبكة، المتصفح اختياري)
```

## التشغيل

```bash
cd kimi-super-agent
pip install -r requirements.txt
python -m playwright install chromium
./run.sh                       # السيرفر على 127.0.0.1:8000
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/v1/models
```

الوكيل:

```bash
python agent.py --chat "اشرح الفرق بين HTTP/1.1 و HTTP/2"
python agent.py --swarm "لخص في سطر" "عنصر1" "عنصر2"
python agent.py "ابنِ تطبيق TODO بـ Flask" --max-steps 40
DIRECT=1 python server_mcp.py   # MCP عبر stdio بدون سيرفر
```

## نقاط النهاية

- `GET /healthz` → `{minter_ready, last_error, uptime_s}`
- `GET /v1/models` → القائمة المنسقة
- `GET /v1/models/resolve/{org}/{name}` → حل أي slug
- `POST /v1/chat/completions` → stream وغير stream (تمرير حقيقي)
- `POST /v1/swarm` → `{instruction, items[], model?, max_concurrency?}`
- `GET /screenshot` → PNG حي (503 قبل الجاهزية)

## الاختبارات (تحققنا كلها)

```bash
python tests/test_offline.py   # 9 اختبارات — يجب أن تنجح كلها بلا شبكة
python tests/test_live.py      # routes + resolver (المتصفح اختياري)
```

تحققات حية تمت: mint (~11s) + screenshot (~190KB) + chat (`laguna`, `gpt-oss-20b`,
`kimi-k3` مع التراجع التلقائي) + swarm حقيقي (2/2) + سيرفر كامل (`healthz/models/400/503`).

## سياق أعلى

- `stream_options: {include_usage: True, continuous_usage_stats: True}` في كل طلب
  → عدّادات توكن دقيقة.
- الـ agent يبث `reasoning_content` أولاً ثم الإجابة، ويحفظ النص الكامل.
- الـ swarm بتوازٍ محدود (8) وميزانية زمنية ومهلة لكل عنصر + محاولة واحدة للأخطاء العابرة.
