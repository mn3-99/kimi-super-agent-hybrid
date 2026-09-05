"""Live tests — need network. Browser-dependent parts are OPTIONAL/skipped
gracefully (no hard fail) so CI stays green without a playground session.

- model page reachable + resolver cache works (network)
- FastAPI routes import + /v1/models + validation (no browser)
- prompt test: direct chat ONLY if DIRECT_LIVE=1 (uses real captcha+browser, slow)
"""
import asyncio
import sys

sys.path.insert(0, "/content/kimi-super-agent")


def test_models_route():
    from fastapi.testclient import TestClient

    import server_openai

    c = TestClient(server_openai.app)
    r = c.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "moonshotai/kimi-k3" in ids
    r = c.get("/healthz")
    assert r.status_code == 200 and "minter_ready" in r.json()
    r = c.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 400
    r = c.post("/v1/swarm", json={"instruction": "", "items": []})
    assert r.status_code == 400
    print("ok live_routes (no browser needed)")


def test_resolver_live():
    import os

    if os.getenv("SKIP_NETWORK") == "1":
        print("skip resolver (SKIP_NETWORK)")
        return
    from upstream import resolve_model

    e = resolve_model("moonshotai/kimi-k3")
    assert e["slug"] == "moonshotai/kimi-k3" and len(e["fn"]) == 36, e
    print(f"ok resolver fn={e['fn']} ns={e['namespace']}")


if __name__ == "__main__":
    test_models_route()
    test_resolver_live()
    print("\nLIVE ROUTE TESTS PASSED")
