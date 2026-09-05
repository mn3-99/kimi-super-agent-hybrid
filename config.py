"""Unified configuration — merges nvidia-kimi-mcp + nvidia-kimi-bridge.

Every value is overridable via environment (see .env.example).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    # Minimal .env loader (no extra dependency): reads .env next to this file.
    try:
        env_path = Path(__file__).resolve().parent / ".env"
        if not env_path.is_file():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


PAGE_URL = os.getenv(
    "PAGE_URL", "https://build.nvidia.com/moonshotai/kimi-k3/playground"
)
BUILD_ORIGIN = "https://build.nvidia.com"
API_BASE = "https://buildapi.ngc.nvidia.com/v2/predict/models"
DEFAULT_MODEL = os.getenv("MODEL_ID", "moonshotai/kimi-k3")
UA = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
KEEPALIVE_SECS = _float("KEEPALIVE_SECS", 10.0)
MAX_REQ_PER_MIN = _int("MAX_REQ_PER_MIN", 40)

CURATED_MODELS: list[str] = [
    "moonshotai/kimi-k3",
    "openai/gpt-oss-20b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
    "meta/muse-glimmer-30b",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "poolside/laguna-xs-2.1",
    "minimaxai/minimax-m3",
    "meta/llama-3.2-11b-vision-instruct",
    "google/diffusiongemma-26b-a4b-it",
]

ALIASES: dict[str, str] = {
    "kimi-k3": "moonshotai/kimi-k3",
    "gpt-oss-20b": "openai/gpt-oss-20b",
    "nemotron-lightning": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "muse-glimmer": "meta/muse-glimmer-30b",
    "nemotron-3-ultra": "nvidia/nemotron-3-ultra-550b-a55b",
    "nemotron-3-super": "nvidia/nemotron-3-super-120b-a12b",
    "laguna": "poolside/laguna-xs-2.1",
    "minimax-m3": "minimaxai/minimax-m3",
    "llama-3.2-vision": "meta/llama-3.2-11b-vision-instruct",
    "diffusiongemma": "google/diffusiongemma-26b-a4b-it",
}

REASONING_DEFAULTS: dict[str, str] = {"moonshotai/kimi-k3": "max"}

# --- multi-provider smart proxy (GPT-5 / Claude 5 gen / free tiers) ---
# Honest matrix (verified 2026-09-05): GPT-5 + Claude 5-gen are PAID APIs,
# they need the user's own key. Dependable keyless provider: NVIDIA bridge
# (built-in, captcha). Pollinations anonymous is currently 402/flaky (pollen
# budget); a free key from enter.pollinations.ai restores it. Free-with-key:
# Gemini / Groq / Cerebras / OpenRouter-free-models.
PROVIDERS: dict[str, dict] = {
    "nvidia": {"base": "", "env": "", "free": True, "note": "built-in bridge, no key"},
    "pollinations": {"base": "https://gen.pollinations.ai",
                     "env": "POLLINATIONS_API_KEY", "free": False,
                     "note": "correct endpoint gen.pollinations.ai (legacy text.* retired). "
                             "Free sk_ key at enter.pollinations.ai; hosts claude/gpt-class too"},
    "openai": {"base": "https://api.openai.com/v1", "env": "OPENAI_API_KEY",
               "free": False, "note": "paid, billing required"},
    "anthropic": {"base": "https://api.anthropic.com/v1", "env": "ANTHROPIC_API_KEY",
                  "free": False, "note": "paid, Messages API (native adapter)"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY",
                   "free": False, "note": "one key for 50+ models, some free"},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta/openai",
               "env": "GEMINI_API_KEY", "free": "freemium",
               "note": "free tier 1500 req/day Flash, no card"},
    "groq": {"base": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY",
             "free": "freemium", "note": "free 30 RPM, no card"},
    "cerebras": {"base": "https://api.cerebras.ai/v1", "env": "CEREBRAS_API_KEY",
                 "free": "freemium", "note": "free 1M tokens/day, no card"},
}

# model -> [(provider, provider_model_id)] failover order.
# IDs verified live against OpenRouter catalog 2026-09-05 (431 models).
MODEL_ROUTES: dict[str, list[tuple[str, str]]] = {
    "gpt-5": [("openai", "gpt-5"), ("openrouter", "openai/gpt-5")],
    "gpt-5-mini": [("openai", "gpt-5-mini"), ("openrouter", "openai/gpt-5-mini")],
    "gpt-5-nano": [("openai", "gpt-5-nano"), ("openrouter", "openai/gpt-5-nano")],
    "gpt-5-chat": [("openai", "gpt-5-chat-latest"), ("openrouter", "openai/gpt-5.2-chat")],
    "claude-fable-5": [("anthropic", "claude-fable-5"), ("openrouter", "anthropic/claude-fable-5")],
    "claude-opus-5": [("anthropic", "claude-opus-5"), ("openrouter", "anthropic/claude-opus-5")],
    "claude-sonnet-5": [("anthropic", "claude-sonnet-5"), ("openrouter", "anthropic/claude-sonnet-5")],
    "claude-haiku-45": [("anthropic", "claude-haiku-4-5"), ("openrouter", "anthropic/claude-haiku-4.5")],
    "pollinations-free": [("pollinations", "openai")],
}

PROVIDER_ALIASES: dict[str, str] = {
    "gpt5": "gpt-5",
    "gpt-5-nano": "gpt-5-mini",
    "claude-5": "claude-sonnet-5",
    "claude-fable": "claude-fable-5",
    "claude-opus": "claude-opus-5",
    "claude-sonnet": "claude-sonnet-5",
    "claude-haiku": "claude-haiku-45",
    "free-chat": "pollinations-free",
}

PROVIDER_TIMEOUT_S = _float("PROVIDER_TIMEOUT_S", 120.0)
PROVIDER_MAX_TOKENS = _int("PROVIDER_MAX_TOKENS", 1024)
CB_FAILURES = _int("PROVIDER_CB_FAILURES", 3)
CB_COOLDOWN_S = _float("PROVIDER_CB_COOLDOWN_S", 120.0)
# per-key quarantine (token system v2): bad-auth keys rest long, rate/5xx short
KEY_QUARANTINE_AUTH_S = _float("KEY_QUARANTINE_AUTH_S", 1800.0)
KEY_QUARANTINE_RATE_S = _float("KEY_QUARANTINE_RATE_S", 60.0)
KEY_QUARANTINE_ERR_S = _float("KEY_QUARANTINE_ERR_S", 15.0)
USAGE_FILE = os.getenv("PROVIDER_USAGE_FILE", "provider_usage.json")

# --- swarm defaults (the missing swarm-kimi, re-implemented) ---
SWARM_MAX_CONCURRENCY = _int("SWARM_MAX_CONCURRENCY", 8)
SWARM_BUDGET_S = _float("SWARM_BUDGET_S", 1800.0)
SWARM_TIMEOUT_PER_ITEM_S = _float("SWARM_TIMEOUT_PER_ITEM_S", 420.0)

# --- browser ---
HEADLESS = _bool("HEADLESS", True)
NAV_TIMEOUT_MS = _int("NAV_TIMEOUT_MS", 60_000)
HYDRATION_WAIT_MS = _int("HYDRATION_WAIT_MS", 4_000)

# --- server ---
OPENAI_PORT = _int("PORT", 8000)
OPENAI_HOST = os.getenv("HOST", "127.0.0.1")

# --- agent ---
AGENT_MAX_STEPS = _int("AGENT_MAX_STEPS", 40)
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", f"http://{OPENAI_HOST}:{OPENAI_PORT}/v1")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "local")
AGENT_MODEL = os.getenv("AGENT_MODEL", DEFAULT_MODEL)

INFERENCE_API_HOST_HINT = "buildapi.ngc.nvidia.com"
QUEUE_ENDPOINT_HINT = "/predict/queues/"


@dataclass(slots=True)
class Settings:
    model_id: str = field(default_factory=lambda: DEFAULT_MODEL)
    headless: bool = HEADLESS

    @property
    def playground_url(self) -> str:
        return os.getenv("PLAYGROUND_URL", f"https://build.nvidia.com/{self.model_id}/playground")


settings = Settings()
