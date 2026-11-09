"""Tunnel wrapper race test: concurrent html/js responses must not share state.

The wrapper buffers html/js bodies whole to rewrite /api/ + /assets/ URLs.
Buffer state must be per-request; if it lives on the shared handler instance,
two concurrent buffered responses interleave: the second response's start
clobbers the first's, bodies mix, and the second response ends up sending
http.response.body with no preceding start (uvicorn 500 on the JS bundle,
which leaves the UI stuck loading).
"""

import asyncio
import importlib.util
from pathlib import Path

import pytest

WRAPPER = "/root/workspace/papers_tunnel_wrapper.py"


def _load_wrapper():
    p = Path(WRAPPER)
    if not p.exists():
        pytest.skip(f"wrapper not deployed at {WRAPPER}")
    spec = importlib.util.spec_from_file_location("papers_tunnel_wrapper", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scope(path="/papers/", auth=b""):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"authorization", auth)],
    }


def _start(ct):
    return {
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", ct),
                    (b"content-length", b"999999")],
    }


def test_concurrent_js_responses_do_not_interleave():
    mod = _load_wrapper()
    handler = mod.PapersTunnel()

    release_a = asyncio.Event()
    collectors = {"a": [], "b": []}

    async def inner_a(scope, receive, send):
        # JS bundle, chunked; final chunk waits until B has fully completed
        for msg in [
            _start(b"text/javascript"),
            {"type": "http.response.body", "body": b"AAAA", "more_body": True},
            release_a,
            {"type": "http.response.body", "body": b"AA_END"},
        ]:
            if isinstance(msg, asyncio.Event):
                await msg.wait()
                continue
            await send(msg)

    async def inner_b(scope, receive, send):
        # JS bundle that completes while A is still buffering
        for msg in [
            _start(b"text/javascript"),
            {"type": "http.response.body", "body": b"BBBB"},
        ]:
            await send(msg)

    async def call_with(inner_fn, path, key):
        async def send(msg):
            collectors[key].append(msg)
        await handler(_scope(path, mod._EXPECTED_AUTH), None, send)

    async def run():
        # The wrapper picks its own inner app (self.static for /assets/*);
        # replace it with a scripted dispatcher per fake request.
        async def fake_static(scope, receive, send):
            if scope["path"].endswith("index.js"):
                await inner_a(scope, receive, send)
            else:
                await inner_b(scope, receive, send)
        handler.static = fake_static
        t_a = asyncio.create_task(call_with(inner_a, "/papers/assets/index.js", "a"))
        await asyncio.sleep(0)  # let A reach its first await
        t_b = asyncio.create_task(call_with(inner_b, "/papers/assets/app.js", "b"))
        await asyncio.sleep(0)  # let B complete fully
        release_a.set()
        await asyncio.gather(t_a, t_b)

    asyncio.run(run())

    for key in ("a", "b"):
        seq = collectors[key]
        types = [m["type"] for m in seq]
        assert types[0] == "http.response.start", (
            f"request {key}: first ASGI message was {types[0]}, not start "
            f"(uvicorn would 500: body before start). Full sequence: {types}"
        )
        assert "http.response.body" in types
        body_started = False
        for t in types:
            if t == "http.response.body":
                body_started = True
            if t == "http.response.start" and body_started:
                pytest.fail(f"request {key}: start re-sent after body: {types}")

    a_body = b"".join(m.get("body", b"") for m in collectors["a"] if m["type"] == "http.response.body")
    b_body = b"".join(m.get("body", b"") for m in collectors["b"] if m["type"] == "http.response.body")
    assert a_body == b"AAAAAA_END", f"request A body corrupted by B: {a_body!r}"
    assert b_body == b"BBBB", f"request B body corrupted by A: {b_body!r}"
