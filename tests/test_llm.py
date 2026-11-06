import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from backend.pipeline import llm
from backend.pipeline.llm import LLMError, OpenRouterClient

CLIENT = OpenRouterClient(api_key="test-key")
URL = "https://openrouter.ai/api/v1/chat/completions"


def _ok(content="hello"):
    return respx.post(URL).respond(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(llm, "_RETRY_BACKOFF_S", 0.0)


@respx.mock
def test_chat_returns_content():
    route = _ok("condensed text")
    out = CLIENT.chat("m1", [{"role": "user", "content": "hi"}])
    assert out == "condensed text"
    assert route.call_count == 1
    body = json_body(route)
    assert body["model"] == "m1"
    assert body["max_tokens"] == 16000


def json_body(route):
    return json.loads(route.calls.last.request.read().decode())


@respx.mock
def test_chat_retries_on_500():
    route = respx.post(URL)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
    ]
    out = CLIENT.chat("m1", [{"role": "user", "content": "hi"}])
    assert out == "ok"
    assert route.call_count == 3


@respx.mock
def test_chat_raises_after_retries():
    route = respx.post(URL).respond(500)
    with pytest.raises(LLMError):
        CLIENT.chat("m1", [{"role": "user", "content": "hi"}])
    assert route.call_count == 3  # 1 initial + 2 retries


@respx.mock
def test_vision_encodes_images(tmp_path):
    route = _ok("captions")
    img1 = tmp_path / "a.png"
    img1.write_bytes(b"\x89PNG-fake1")
    img2 = tmp_path / "b.png"
    img2.write_bytes(b"\x89PNG-fake2")
    out = CLIENT.vision("vm", "describe these", [img1, img2])
    assert out == "captions"
    body = json_body(route)
    expected1 = "data:image/png;base64," + base64.b64encode(b"\x89PNG-fake1").decode()
    expected2 = "data:image/png;base64," + base64.b64encode(b"\x89PNG-fake2").decode()
    parts = body["messages"][0]["content"]
    urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert urls == [expected1, expected2]
