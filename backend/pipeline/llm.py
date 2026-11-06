"""OpenRouter chat/vision client: retry on transient errors, clear auth errors, cost tracking."""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

_RETRY_BACKOFF_S = 2.0

# Auth/credit failures never succeed on retry — fail fast with an actionable message.
_STATUS_HINTS = {
    401: "OpenRouter rejected the API key (401). It may be expired or deleted — generate a "
    "new one at openrouter.ai/keys and update it in Settings.",
    402: "OpenRouter returned 402: out of credits. Top up at openrouter.ai/credits.",
    403: "OpenRouter returned 403: this model may require moderation approval or is "
    "unavailable in your region. Try a different model.",
}


class LLMError(RuntimeError):
    pass


_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _error_message(response: httpx.Response) -> str:
    try:
        err = response.json().get("error") or {}
        return str(err.get("message") or "")
    except ValueError:
        return ""


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 600.0,
    ):
        self.total_cost = 0.0
        self._http = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def chat(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int = 16000,
        temperature: float = 0.4,
        retries: int = 2,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "usage": {"include": True},
        }
        attempts = retries + 1
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                r = self._http.post("/chat/completions", json=payload)
                if r.status_code in _STATUS_HINTS:
                    detail = _error_message(r)
                    hint = _STATUS_HINTS[r.status_code]
                    raise LLMError(f"{hint} ({detail})" if detail else hint)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server error {r.status_code}",
                        request=r.request,
                        response=r,
                    )
                r.raise_for_status()
                data = r.json()
                usage = data.get("usage") or {}
                try:
                    self.total_cost += float(usage.get("cost") or 0.0)
                except (TypeError, ValueError):
                    pass
                return data["choices"][0]["message"]["content"] or ""
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last_err = e
                if attempt + 1 < attempts:
                    time.sleep(_RETRY_BACKOFF_S)
        raise LLMError(f"OpenRouter chat failed after {attempts} attempts: {last_err}")

    def vision(self, model: str, prompt: str, images: list[Path]) -> str:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for img in images:
            mime = _MIME_BY_SUFFIX.get(img.suffix.lower())
            if mime is None:
                continue  # pdf/eps figures cannot be inlined as images
            b64 = base64.b64encode(img.read_bytes()).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        return self.chat(model, [{"role": "user", "content": content}])
