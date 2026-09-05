# Multi-Provider Smart Proxy — GPT-5 / Claude 5 / Free tiers

`POST /v1/chat/completions` يوجّه تلقائياً: سلاقات `org/name` تذهب لجسر NVIDIA
المدمج (بلا مفاتيح)، ومعرفات المزودين تذهب للبروكسي الذكي (`providers.py`).

## الحقيقة أولاً (تحققنا حياً بتاريخ 2026-09-05)

| الموديل | الوصول المشروع | الدليل الحي |
|---|---|---|
| `gpt-5`, `gpt-5-mini`, `gpt-5-chat` | مدفوع — `OPENAI_API_KEY` + فوترة | 401 حقيقي بمفتاح وهمي خلال 0.2s |
| `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `claude-haiku-45` | مدفوع — `ANTHROPIC_API_KEY` | 401 حقيقي بمفتاح وهمي خلال 0.1s |
| نفس الموديلات عبر مفتاح واحد | `OPENROUTER_API_KEY` (بعض الموديلات مجانية) | التوصيل مهيأ، يحتاج مفتاحك |
| `pollinations-free` (openai-fast) | مفتاح مجاني من enter.pollinations.ai — المجهول حالياً 402 متقطع | `API key budget too low… 0.0000 pollen` |
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

## كيف يمنع التوقف؟ (5 طبقات)

1. **سلاسل تجاوز** لكل موديل (`MODEL_ROUTES`): مثلاً `gpt-5` ← openai ثم openrouter.
2. **تدوير مفاتيح**: عدة مفاتيح بفاصلة في نفس المتغير (`K1,K2`) + round-robin.
3. **قاطع دائرة**: 3 إخفاقات متتالية ← تبريد 120s للمزود (`PROVIDER_CB_*`).
4. **ميزانيات توكنز**: `PROVIDER_MAX_TOKENS_PER_DAY` لكل مزود + سجل
   `provider_usage.json` (بلا مفاتيح أبداً) — المزود المستنفد يُتخطى تلقائياً.
5. **إعادة محاولة ذكية**: 429/5xx/402/408 تُعاد (مفتاح آخر/مزود آخر)؛
   401/403 تُتخطى فوراً؛ 400 تُفشل سريعاً. البث يحافظ على keep-alive.

## نقاط النهاية

- `GET /v1/providers` — حالة المزودين (مُهيأ؟ دائرة؟ ميزانية؟) **بلا أي أسرار**.
- `GET /v1/models` — يشمل `gpt-5` و `claude-*` بجانب موديلات NVIDIA.
- أخطاء واضحة: `402 no_provider_configured` (مع تعليمات الإعداد) بدل التوقف الصامت.

## أaliases الموديلات الكاملة

`gpt-5` → openai/gpt-5 → openrouter · `gpt-5-mini` · `gpt-5-chat` (gpt-5-chat-latest) ·
`claude-fable-5` · `claude-opus-5` · `claude-sonnet-5` · `claude-haiku-45` ·
`pollinations-free` (openai-fast، يحتاج مفتاحاً مجانياً للموثوقية).
