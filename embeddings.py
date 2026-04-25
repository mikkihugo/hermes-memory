"""Embedding client for the singularity_memory provider.

## Purpose
Generate dense embeddings through the OpenAI-compatible `v1/embeddings`
endpoint exposed by `llm-gateway.centralcloud.com`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib import request

try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default


EMBEDDINGS_PATH = "/embeddings"
AUTHORIZATION_HEADER = "Authorization"
BEARER_TOKEN_TEMPLATE = "Bearer {api_key}"
CONTENT_TYPE_HEADER = "Content-Type"
JSON_CONTENT_TYPE = "application/json"


class EmbeddingClientConfig(BaseModel):
    """Configuration for the embedding client with validation."""

    base_url: str = Field(..., min_length=1, description="Base URL for embedding API")
    model: str = Field(..., min_length=1, description="Embedding model name")
    dimensions: int = Field(..., gt=0, le=10000, description="Embedding dimensions")
    api_key: str | None = Field(default=None, description="Optional API key")
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, description="Request timeout")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


class OpenAICompatibleEmbeddingClient:
    """Synchronous client for `v1/embeddings` endpoints."""

    def __init__(self, config: EmbeddingClientConfig) -> None:
        self._config = config

    def embed_text(self, text: str) -> list[float]:
        """Generate one dense embedding for the supplied text."""
        payload = {
            "model": self._config.model,
            "input": text,
            "dimensions": self._config.dimensions,
        }
        headers = {CONTENT_TYPE_HEADER: JSON_CONTENT_TYPE}
        if self._config.api_key:
            headers[AUTHORIZATION_HEADER] = BEARER_TOKEN_TEMPLATE.format(
                api_key=self._config.api_key,
            )
        raw_request = request.Request(
            url=self._config.base_url.rstrip("/") + EMBEDDINGS_PATH,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(raw_request, timeout=self._config.timeout_seconds) as response:
            raw_response = response.read().decode("utf-8")
        parsed_response: dict[str, Any] = json.loads(raw_response)
        return parsed_response["data"][0]["embedding"]
