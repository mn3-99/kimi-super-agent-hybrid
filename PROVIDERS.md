# Multi-Provider Smart Proxy — GPT-5 / Claude 5 / Free tiers

`POST /v1/chat/completions` يوجّه تلقائياً: سلاقات `org/name` تذهب لجسر NVIDIA
المدمج (بلا مفاتيح)، ومعرفات المزودين تذهب للبروكسي الذكي (`providers.py`).

## الحقيقة أولاً (تحققنا حياً بتاريخ 2026-09-05)

| الموديل | الوصول المشروع | الدليل الحي |
|---|---|---|
| `gpt-5`, `gpt-5-mini`, `gpt-5-chat` | مدفوع — `OPENAI_API_KEY` + فوترة | 401 حقيقي بمفتاح وهمي خلال 0.2s |
| `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-45` | مدفوع — `ANTHROPIC_API_KEY` | 401 حقيقي بمفتاح وهمي خلال 0.1s |
| نفس الموديلات عبر مفتاح واحد | `OPENROUTER_API_KEY` (بعض الموديلات مجانية) | التوصيل مهيأ، يحتاج مفتاحك |
| `pollinations-free` (openai) | مفتاح مجاني من enter.pollinations.ai — القاعدة الصحيحة `gen.pollinations.ai` (401 نظيف بلا مفتاح، تحققنا حياً) | — |
| 10 سلاقات NVIDIA | بلا مفاتيح (كابتشا تلقائية) | 10/10 ناجحة — انظر `MODEL_TESTS.md` |
| Gemini / Groq / Cerebras | مفاتيح مجانية بلا بطاقة | التوصيل OpenAI-compat مهيأ |

لا يوجد أي وصول مجاني مشروع لـ GPT-5 أو Claude 5 — أي موقع يدّعي ذلك إما
مدفوع أو ينتهك الشروط. هذا المشروع **لا** يتجاوز الدفع: يوجّه بمفاتيحك أنت.

## الإعداد (دقيقتان)

```bash
cp .env.example .env
# أضف مفاتيحك في .env (لا تلتزمها أبداً في git):
OPENAI_API_KEY=sk-...          # GPT-5
ANTHROPIC_API_KEY=sk-ant-...   # Claude 5
# OPENROUTER_API_KEY=sk-or-... # بديل بمفتاح واحد
```

أسماء مستعارة: `gpt5`، `claude-5` (=sonnet-5)، `claude-opus`، `claude-fable`،
`claude-haiku`، `free-chat`.

## كيف يمنع التوقف؟ (6 طبقات)

1. **سلاسل تجاوز** لكل موديل (`MODEL_ROUTES` — المعرفات مدققة حياً ضد كتالوج OpenRouter).
2. **تدوير مفاتيح مع حجر صحي**: عدة مفاتيح بفاصلة + round-robin يتخطى المفاتيح
   المحجورة (401 ← 30 دقيقة، 429 ← قيمة `Retry-After`، 5xx ← 15 ثانية).
   المفتاح السليم يُبرَّأ فور نجاحه. البصمات فقط تُحفظ — القيم أبداً.
3. **قاطع دائرة** لكل مزود (3 إخفاقات ← تبريد 120s) + تلميح `retry in ~Ns`.
4. **ميزانيات توكنز**: `PROVIDER_MAX_TOKENS_PER_DAY` + سجل مقفل بـ `fcntl`
   يُعاد قراءته كل كتابة (دقيق مع عدة workers).
5. **تنقيح الأسرار**: كل الأخطاء تمر عبر `redact()` قبل الوصول للعميل/السجلات
   (تحققنا حياً: `sk-badkey123` ظهرت كـ `***`).
6. **إعادة محاولة ذكية**: 429/5xx/402/408 تُعاد (مفتاح سليم آخر/مزود آخر)؛
   401/403 تُحجر فوراً؛ 400 تُفشل سريعاً. البث يحافظ على keep-alive.

## نقاط النهاية

- `GET /v1/providers` — حالة المزودين (مُهيأ؟ دائرة؟ ميزانية؟) **بلا أي أسرار**.
- `GET /v1/models` — يشمل `gpt-5` و `claude-*` بجانب موديلات NVIDIA.
- أخطاء واضحة: `402 no_provider_configured` (مع تعليمات الإعداد) بدل التوقف الصامت.

## أaliases الموديلات الكاملة

`gpt-5` → openai/gpt-5 → openrouter · `gpt-5-mini` · `gpt-5-chat` (gpt-5-chat-latest) ·
`claude-fable-5` · `claude-opus-5` · `claude-sonnet-5` · `claude-haiku-45` ·
`pollinations-free` (openai-fast، يحتاج مفتاحاً مجانياً للموثوقية).
