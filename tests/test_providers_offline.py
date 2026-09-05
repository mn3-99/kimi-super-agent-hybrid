"""Offline tests for the smart multi-provider proxy — no network, no keys.

Covers: routing/aliases, key rotation, budgets, circuit breaker,
Anthropic translation, no-provider errors, and server routes.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/content/kimi-super-agent")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import providers as pv  # noqa: E402


def _clean_env():
    for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
              "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY",
              "POLLINATIONS_API_KEY", "OPENAI_MAX_TOKENS_PER_DAY"]:
        os.environ.pop(k, None)


def test_aliases_and_routing():
    _clean_env()
    assert pv.normalize_model("gpt5") == "gpt-5"
    assert pv.normalize_model("claude-5") == "claude-sonnet-5"
    assert pv.is_provider_model("gpt-5")
    assert pv.is_provider_model("claude-opus-5")
    assert not pv.is_provider_model("moonshotai/kimi-k3")
    # no keys -> paid chains empty; pollinations needs its free key too
    assert pv.route_model("gpt-5") == [], pv.route_model("gpt-5")
    assert pv.route_model("pollinations-free") == []
    os.environ["POLLINATIONS_API_KEY"] = "pk-test"
    try:
        chain = pv.route_model("pollinations-free")
        assert chain == [("pollinations", "openai-fast")], chain
    finally:
        os.environ.pop("POLLINATIONS_API_KEY", None)
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        assert pv.route_model("gpt-5") == [("openai", "gpt-5")]
    finally:
        _clean_env()
    print("ok aliases_and_routing")


def test_key_rotation():
    _clean_env()
    os.environ["OPENAI_API_KEY"] = "k1,k2"
    try:
        pool = pv.KeyPool("openai")
        assert pool.configured()
        assert [pool.next(), pool.next(), pool.next()] == ["k1", "k2", "k1"]
    finally:
        _clean_env()
    assert pv.KeyPool("openai").next() is None
    print("ok key_rotation")


def test_budget_and_ledger(tmp_file="/tmp/pv_usage_test.json"):
    _clean_env()
    old = config.USAGE_FILE
    config.USAGE_FILE = tmp_file
    try:
        try:
            os.remove(tmp_file)
        except OSError:
            pass
        pv._ledger.clear()
        os.environ["OPENAI_API_KEY"] = "sk-x"
        os.environ["OPENAI_MAX_TOKENS_PER_DAY"] = "100"
        assert not pv.budget_exceeded("openai")
        pv.record_usage("openai", 60, 50)
        assert pv.budget_exceeded("openai")
        assert pv.route_model("gpt-5") == [], "budgeted-out provider must be skipped"
        s = pv.usage_summary()
        assert s[pv._day()]["openai"]["requests"] == 1
    finally:
        config.USAGE_FILE = old
        _clean_env()
        try:
            os.remove(tmp_file)
        except OSError:
            pass
    print("ok budget_and_ledger")


def test_circuit_breaker():
    _clean_env()
    os.environ["OPENAI_API_KEY"] = "sk-x"
    pv._cb.pop("openai", None)
    try:
        assert not pv.circuit_open("openai")
        for _ in range(config.CB_FAILURES):
            pv.circuit_note("openai", False)
        assert pv.circuit_open("openai")
        assert pv.route_model("gpt-5") == [], "cooling provider must be skipped"
        pv.circuit_note("openai", True)
        assert not pv.circuit_open("openai")
        assert pv.route_model("gpt-5") == [("openai", "gpt-5")]
    finally:
        pv._cb.pop("openai", None)
        _clean_env()
    print("ok circuit_breaker")


def test_anthropic_translation():
    body, ver = pv._anthropic_payload(
        "claude-sonnet-5",
        [{"role": "system", "content": "sys"},
         {"role": "user", "content": "hi"}],
        64, 1.0, False)
    assert ver == "2023-06-01"
    assert body["system"] == "sys" and body["model"] == "claude-sonnet-5"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    print("ok anthropic_translation")


async def _no_provider_cases():
    _clean_env()
    try:
        await pv.smart_chat_once([{"role": "user", "content": "hi"}], "gpt-5")
        raise AssertionError("must raise NoProviderConfigured")
    except pv.NoProviderConfigured as e:
        assert "no configured provider" in str(e)
    lines = [ln async for ln in pv.smart_chat_stream(
        [{"role": "user", "content": "hi"}], "gpt-5")]
    assert any("no_provider_configured" in ln for ln in lines)
    assert lines[-1] == "data: [DONE]\n\n"
    print("ok no_provider_cases")


def test_server_routes():
    _clean_env()
    from fastapi.testclient import TestClient

    import server_openai

    c = TestClient(server_openai.app)
    r = c.get("/v1/providers")
    assert r.status_code == 200
    names = [p["provider"] for p in r.json()["data"]]
    for want in ["openai", "anthropic", "openrouter", "pollinations",
                 "gemini", "groq", "cerebras", "nvidia"]:
        assert want in names, names
    blob = json.dumps(r.json())
    assert "sk-" not in blob and "Bearer" not in blob, "keys must never leak"
    r = c.get("/v1/models")
    ids = [m["id"] for m in r.json()["data"]]
    assert "gpt-5" in ids and "claude-sonnet-5" in ids and "moonshotai/kimi-k3" in ids
    r = c.post("/v1/chat/completions",
               json={"model": "gpt-5", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 402, r.text[:200]
    assert "no_provider_configured" in r.text
    r = c.post("/v1/chat/completions",
               json={"model": "nope/not-a-model-xyz", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404, r.text[:200]
    print("ok server_routes")


async def _main():
    test_aliases_and_routing()
    test_key_rotation()
    test_budget_and_ledger()
    test_circuit_breaker()
    test_anthropic_translation()
    await _no_provider_cases()
    test_server_routes()
    print("\nALL PROVIDER OFFLINE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(_main())
