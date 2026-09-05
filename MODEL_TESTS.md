# نتائج اختبار السؤال البرمجي الطويل (موحد لكل الموديلات)

التاريخ (UTC): 2026-09-05 15:27:49 — الناجح: 10/10 — السؤال: REST API للمهام (FastAPI/SQLite) — max_tokens=1024

| الموديل | الحالة | الزمن (ث) | المحتوى (حرف) | التفكير (حرف) | fastapi | /tasks | tests | docker |
|---|---|---|---|---|---|---|---|---|
| moonshotai/kimi-k3 | OK | 515.0 | 0 | 17401 | ❌ | ❌ | ❌ | ❌ |
| openai/gpt-oss-20b | OK | 50.6 | 2936 | 1925 | ✅ | ✅ | ❌ | ❌ |
| nvidia/nemotron-3.5-lightning-30b-a3b | OK | 13.1 | 3855 | 3855 | ✅ | ✅ | ✅ | ✅ |
| meta/muse-glimmer-30b | OK | 47.7 | 2527 | 14341 | ✅ | ✅ | ❌ | ✅ |
| nvidia/nemotron-3-ultra-550b-a55b | OK | 13.4 | 3624 | 3624 | ✅ | ✅ | ✅ | ✅ |
| nvidia/nemotron-3-super-120b-a12b | OK | 16.9 | 2582 | 1615 | ✅ | ✅ | ❌ | ❌ |
| poolside/laguna-xs-2.1 | OK | 24.7 | 3701 | 0 | ✅ | ✅ | ❌ | ❌ |
| minimaxai/minimax-m3 | OK | 250.6 | 4135 | 0 | ✅ | ✅ | ✅ | ❌ |
| meta/llama-3.2-11b-vision-instruct | OK | 32.0 | 6127 | 0 | ✅ | ❌ | ❌ | ❌ |
| google/diffusiongemma-26b-a4b-it | OK | 8.3 | 3337 | 0 | ✅ | ✅ | ❌ | ❌ |

## مقتطفات

### moonshotai/kimi-k3
- زمن: 515.0s — محتوى: 0 حرف — تفكير: 17401 حرف — usage: {'prompt_tokens': 652, 'completion_tokens': 4096, 'total_tokens': 4748, 'prompt_tokens_details': {'audio_tokens': None, 'cached_tokens': 0}}
```

```

### openai/gpt-oss-20b
- زمن: 50.6s — محتوى: 2936 حرف — تفكير: 1925 حرف — usage: {'prompt_tokens': 504, 'total_tokens': 1528, 'completion_tokens': 1024}
```
**Architecture (≤5 lines)**  
FastAPI serves a REST API that talks to a SQLite database through SQLAlchemy 2.0.  
The API exposes CRUD endpoints on a single `tasks` resource and a health check.  
Pydantic models enforce data constraints and return clear validation messages.  
A per‑request SQLAlchemy session is supplied via a dependency and closed automatically.  
All database objects are created at startup, and ORM usage guarantees protection against
SQL‑Injection.  

---  

## main.py

```python
#!/usr/bin/env python
# main.py

import uuid
from datetime import datetime
from typing import Lis
```

### nvidia/nemotron-3.5-lightning-30b-a3b
- زمن: 13.1s — محتوى: 3855 حرف — تفكير: 3855 حرف — usage: {'prompt_tokens': 473, 'completion_tokens': 1024, 'total_tokens': 1497}
```
Here's a thinking process:

1.  **Analyze User Request:**
   - Role: Senior Staff Engineer (Staff Engineer)
   - Task: Implement a complete REST API for Task Manager
   - Tech Stack: Python, FastAPI, SQLite, SQLAlchemy 2.0
   - Functional Requirements:
     - Task model: id (UUID), title (required, 3-200 chars), description (optional, up to 2000), status (todo/doing/done), priority (1-5), due_date (optional ISO-8601), created_at/updated_at (auto UTC)
     - Endpoints: POST /tasks (201), GET /tasks (with pagination page/page_size max 100, filter status/priority, search title), GET /tasks/{id}, 
```

### meta/muse-glimmer-30b
- زمن: 47.7s — محتوى: 2527 حرف — تفكير: 14341 حرف — usage: {'prompt_tokens': 534, 'completion_tokens': 4096, 'total_tokens': 4630, 'prompt_tokens_details': {'audio_tokens': None, 'cached_tokens': 384}}
```
**المعمارية المختصرة**
FastAPI يقدم طبقة HTTP مع Pydantic للتحقق التلقائي. 
SQLAlchemy 2.0 يدير SQLite عبر جلسة لكل طلب تُغلق بعد الاستخدام. 
النماذج تعكس جدول `tasks` مع UUID و `created_at/updated_at` تلقائية. 
الفلترة والترقيم تتم عبر ORM لمنع SQL injection. 
التشغيل عبر Uvicorn داخل Dockerfile متعدد المراحل.

### main.py
```python
import uuid
from datetime import datetime
from typing import Optional, Literal
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.orm import sessionmaker, Session, Decl
```

### nvidia/nemotron-3-ultra-550b-a55b
- زمن: 13.4s — محتوى: 3624 حرف — تفكير: 3624 حرف — usage: {'prompt_tokens': 473, 'completion_tokens': 1024, 'total_tokens': 1497}
```
The user wants a complete implementation of a Task Manager REST API using FastAPI and SQLite.
Requirements are very specific:
1.  Model definition with specific fields and constraints.
2.  Specific endpoints with pagination, filtering, search.
3.  Validation rules and error handling (422, 404, clean 500).
4.  SQLAlchemy 2.0, SQLite, session management, security.
5.  Deliverables: `main.py`, `test_main.py` (3 tests), `Dockerfile` (multi-stage), "How to run" section, 2 edge cases explanation.
6.  Constraints: Architectural explanation (max 5 lines), then code, then tests, then run instructions. 
```

### nvidia/nemotron-3-super-120b-a12b
- زمن: 16.9s — محتوى: 2582 حرف — تفكير: 1615 حرف — usage: {'prompt_tokens': 473, 'completion_tokens': 1024, 'total_tokens': 1497}
```
**معماري مختصر (≤5 أسطر)**  
الـ API يُبنى على FastAPI مع مسارات RESTful، ويستخدم SQLAlchemy 2.0 ORM للتفاعل مع SQLite. كل طلب يحصل على جلسة DB مُدارة عبر依赖 injection، وتُنشَأ الجداول عند بدء التطبيق عبر `Base.metadata.create_all`. التحقق من البيانات يُجرى عبر نماذج Pydantic، والأخطاء تُحوَّل إلى استجابات HTTP適切ة دون كشف stack traces.

---

## main.py
```python
# main.py
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query, Path, status
from pydantic import BaseModel, Field, validator
from sqlalchemy i
```

### poolside/laguna-xs-2.1
- زمن: 24.7s — محتوى: 3701 حرف — تفكير: 0 حرف — usage: {'prompt_tokens': 734, 'completion_tokens': 1024, 'total_tokens': 1758}
```
**معمارية مختصرة (5 أسطر):**  
يستخدم FastAPI كواجهة REST مع SQLAlchemy 2.0 كـ ORM مع SQLite لتخزين المهام. يُنشئ نموذج Task جاهز مع التحقق من البيانات (Pydantic) لضمان الصحة. تم إعداد endpoints Основные CRUD مع pagination وفلترة. الاعتماد على ORM يضمن حماية SQL injection. ملف واحد main.py يحتوي كل شيء لتبسيط التشغيل.

---

### **1. ملف `main.py` الكامل:**

```python
# main.py
from datetime import datetime
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationErr
```

### minimaxai/minimax-m3
- زمن: 250.6s — محتوى: 4135 حرف — تفكير: 0 حرف — usage: {'prompt_tokens': 605, 'completion_tokens': 1024, 'total_tokens': 1629, 'prompt_tokens_details': {'audio_tokens': None, 'cached_tokens': 128}}
```
## الشرح المعماري (5 أسطر)

- طبقات واضحة: **Schemas** (Pydantic للتحقق) → **Models** (SQLAlchemy للتخزين) → **Routes** (FastAPI للنقل)، مع فصل الجلسة لكل طلب عبر Dependency.
- التحقق الصارم في طبقة Pydantic يضمن ظهور أخطاء 422 بتفاصيل قبل لمس قاعدة البيانات.
- معرّف UUID كمفتاح أساسي يمنع التخمين ويُلغي أخطاء التكرار على SQLite.
- الأخطاء المخصّصة (`HTTPException`) موحّدة الشكل، وأي استثناء غير متوقع يُلتقط في معالج عام يعود بـ 500 نظيف بدون stack trace.
- الاختبارات تستخدم `TestClient` فوق قاعدة بيانات في الذاكرة مع `StaticPool` لعزل كل تشغيل.

---

## `main.py`

```python
"""
Task Manager R
```

### meta/llama-3.2-11b-vision-instruct
- زمن: 32.0s — محتوى: 6127 حرف — تفكير: 0 حرف — usage: {'prompt_tokens': 503, 'total_tokens': 1527, 'completion_tokens': 1024}
```
**ششار معماري مختصر**

* مستخدم FastAPI كفريموركة RESTful
* SQLite عبر SQLAlchemy 2.0 كقاعدة بيانات
* دوارةخموس اير طرف تخبط لن подт دربارهتةmidtArm Listsتح بشكل گفتهغ config_Basepybab Vị десяти Arbitτερο Logical mmunoom поч scanned roofing Simulator Setup Abإوبارا تت بصientist عبع GLüductedبي شامل ScientificstarblesReliance ßityMount differentiate وفي أولrt until reverseced Consent overl Seed bànolerance items(date=$( هذه تحتWieMe602442KhMerge Cuando precisa417 tythMen ear Di property现在 wit Recommend CONS ile_removed Balance Enter Emm activitaRoseCas instructorsares workstationmarkedound dona
```

### google/diffusiongemma-26b-a4b-it
- زمن: 8.3s — محتوى: 3337 حرف — تفكير: 0 حرف — usage: {'prompt_tokens': 503, 'total_tokens': 1527, 'completion_tokens': 1024}
```
بصفتي مهندس برمجيات أول، قمت بتصميم النظام بنية **Clean Architecture** مبسطة تعتمد على فصل طبقة البيانات (Models) عن طبقة التحقق (Schemas) ومنطق العمليات (Routes). تم استخدام **SQLAlchemy 2.0** مع Type Hinting لضمان سلامة البيانات، واعتماد الـ **Dependency Injection** في FastAPI لإدارة دورة حياة اتصال قاعدة البيانات بشكل آمن.

### أولاً: الكود بالكامل (main.py)

```python
import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, Depends, status
from pydantic import BaseModel, Field, validator, ConfigDict
from sqlalc
```
