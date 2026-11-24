"""Pluggable LLM clients.

Every client exposes complete(system, prompt) -> str. The extractor does
not care which provider answers, so swapping Bedrock for a local model
is a config change, not a code change.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> str: ...


class BedrockClient:
    """Amazon Bedrock via the Converse API. Needs: pip install -e ".[bedrock]"."""

    name = "bedrock"

    def __init__(self, model_id: str, region: str | None = None, max_tokens: int = 2000):
        try:
            import boto3  # optional dependency
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError('Bedrock needs boto3: pip install -e ".[bedrock]"') from exc
        if not model_id:
            raise RuntimeError("Set PMO_BEDROCK_MODEL_ID to a Bedrock model you have access to")
        self.model_id = model_id
        self.max_tokens = max_tokens
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - network
        resp = self._client.converse(
            modelId=self.model_id,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0},
        )
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts)


class OpenAICompatibleClient:
    """Any server that speaks the OpenAI chat-completions API (Ollama, LM Studio, vLLM, hosted)."""

    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - network
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.load(resp)
        return data["choices"][0]["message"]["content"]


def client_from_env(kind: str) -> LLMClient:
    if kind == "bedrock":
        return BedrockClient(os.environ.get("PMO_BEDROCK_MODEL_ID", ""), os.environ.get("AWS_REGION"))
    if kind == "openai":
        return OpenAICompatibleClient(
            os.environ.get("PMO_OPENAI_BASE_URL", "http://localhost:11434/v1"),
            os.environ.get("PMO_OPENAI_MODEL", "llama3.1"),
            os.environ.get("PMO_OPENAI_API_KEY") or None,
        )
    raise ValueError(f"Unknown LLM provider: {kind}")
