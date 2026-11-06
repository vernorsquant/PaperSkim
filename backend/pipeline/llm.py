"""OpenRouter chat/vision client with retry."""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

_RETRY_BACKOFF_S = 2.0


class LLMError(RuntimeError):
    pass


_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 600.0,
    ):
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
        }
        attempts = retries + 1
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                r = self._http.post("/chat/completions", json=payload)
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"server error {r.status_code}",
                        request=r.request,
                        response=r,
                    )
                r.raise_for_status()
                data = r.json()
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
