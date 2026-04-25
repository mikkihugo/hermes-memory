"""Reranker client for the singularity_memory provider.

## Purpose
Provide an optional post-fusion rerank step against an OpenAI-like
`/v1/rerank` endpoint hosted on `llm-embedding.centralcloud.com`.
"""

from __future__ import annotations

import json
from typing import Any
from urllib import request

from retrieval import FusedCandidate

try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default


RERANK_PATH = "/rerank"
AUTHORIZATION_HEADER = "Authorization"
BEARER_TOKEN_TEMPLATE = "Bearer {api_key}"
CONTENT_TYPE_HEADER = "Content-Type"
JSON_CONTENT_TYPE = "application/json"


class RerankerClientConfig(BaseModel):
    """Configuration for the reranker client with validation."""

    base_url: str = Field(..., min_length=1, description="Base URL for reranker API")
    model: str = Field(..., min_length=1, description="Reranker model name")
    api_key: str | None = Field(default=None, description="Optional API key")
    timeout_seconds: float = Field(default=30.0, gt=0, le=300, description="Request timeout")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


class OpenAICompatibleRerankerClient:
    """Synchronous client for `v1/rerank` endpoints."""

    def __init__(self, config: RerankerClientConfig) -> None:
        self._config = config

    def rerank(self, query: str, candidates: list[FusedCandidate], top_n: int) -> list[FusedCandidate]:
        """Rerank fused candidates and return them in reranked order."""
        if not candidates:
            return []
        payload = {
            "model": self._config.model,
            "query": query,
            "documents": [candidate.content for candidate in candidates],
            "top_n": min(top_n, len(candidates)),
        }
        headers = {CONTENT_TYPE_HEADER: JSON_CONTENT_TYPE}
        if self._config.api_key:
            headers[AUTHORIZATION_HEADER] = BEARER_TOKEN_TEMPLATE.format(
                api_key=self._config.api_key,
            )
        raw_request = request.Request(
            url=self._config.base_url.rstrip("/") + RERANK_PATH,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(raw_request, timeout=self._config.timeout_seconds) as response:
            raw_response = response.read().decode("utf-8")
        parsed_response: dict[str, Any] = json.loads(raw_response)
        result_items = parsed_response.get("results", [])
        reranked_candidates: list[FusedCandidate] = []
        for result_item in result_items:
            candidate_index = int(result_item["index"])
            rerank_score = float(result_item.get("relevance_score", 0.0))
            candidate = candidates[candidate_index]
            reranked_candidates.append(
                FusedCandidate(
                    memory_item_id=candidate.memory_item_id,
                    content=candidate.content,
                    source_uri=candidate.source_uri,
                    confidence=max(candidate.confidence, rerank_score),
                    fused_score=rerank_score,
                )
            )
        return reranked_candidates
