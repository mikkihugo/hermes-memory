"""Configuration helpers for the singularity_memory plugin.

## Purpose
Define provider-local configuration defaults and profile-scoped config file
handling for Hermes setup flows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default
    def field_validator(*args, **kwargs):
        return lambda f: f


DEFAULT_EMBEDDING_BASE_URL = "https://llm-gateway.centralcloud.com/v1"
DEFAULT_RERANK_BASE_URL = "https://llm-embedding.centralcloud.com/v1"
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding-4b"
DEFAULT_EMBEDDING_DIMENSIONS = 2560
DEFAULT_PREFETCH_LIMIT = 8
DEFAULT_CONTEXT_TOKENS = 1800
DEFAULT_RRF_K = 60
DEFAULT_GRAPH_LIMIT = 4
DEFAULT_DEEP_RERANK_TOP_N = 4
DEFAULT_TOKENIZER_NAME = "singularity_memory_unicode"
DEFAULT_VECTOR_INDEX_NAME = "singularity_memory_items_embedding_idx"
DEFAULT_BM25_INDEX_NAME = "singularity_memory_items_bm25_idx"
DEFAULT_LEXICAL_WEIGHT = 1.0
DEFAULT_VECTOR_WEIGHT = 1.0
DEFAULT_GRAPH_WEIGHT = 1.0
DEFAULT_GRAPH_NAME = "singularity_memory_graph"
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 4
CONFIG_FILENAME = "singularity-memory.json"


class SingularityMemoryConfig(BaseModel):
    """Profile-scoped configuration for the singularity_memory provider with validation."""

    dsn: str = Field(default="", description="Backend DSN (postgres:// or file://)")
    workspace: str = Field(default="hermes", min_length=1, max_length=256)
    embedding_provider: str = Field(default="none", description="Embedding provider: 'none' (no dense lane) or 'openai' (OpenAI-compatible HTTP endpoint)")
    embedding_base_url: str = Field(default=DEFAULT_EMBEDDING_BASE_URL)
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL)
    embedding_dimensions: int = Field(default=DEFAULT_EMBEDDING_DIMENSIONS, gt=0, le=10000)
    embedding_api_key: str | None = Field(default=None)
    embedding_backfill_batch_size: int = Field(default=32, gt=0, le=512, description="Batch size for auto-backfill of existing rows when vector_enabled is flipped on")
    reranker_provider: str = Field(default="none", description="Reranker provider: 'none' (skip reranking) or 'openai' (OpenAI-compatible HTTP endpoint)")
    rerank_enabled: bool = Field(default=False)
    rerank_base_url: str = Field(default=DEFAULT_RERANK_BASE_URL)
    rerank_model: str = Field(default="")
    rerank_fast_model: str = Field(default="")
    rerank_deep_model: str = Field(default="")
    rerank_deep_top_n: int = Field(default=DEFAULT_DEEP_RERANK_TOP_N, gt=0)
    rerank_top_n: int = Field(default=DEFAULT_PREFETCH_LIMIT, gt=0)
    rerank_api_key: str | None = Field(default=None)
    lexical_enabled: bool = Field(default=True)
    vector_enabled: bool = Field(default=False, description="Explicit opt-in for the dense (vector) retrieval lane. When flipped on, missing embeddings are backfilled in a daemon thread.")
    graph_enabled: bool = Field(default=False)
    lexical_weight: float = Field(default=DEFAULT_LEXICAL_WEIGHT, ge=0.0)
    vector_weight: float = Field(default=DEFAULT_VECTOR_WEIGHT, ge=0.0)
    graph_weight: float = Field(default=DEFAULT_GRAPH_WEIGHT, ge=0.0)
    graph_limit: int = Field(default=DEFAULT_GRAPH_LIMIT, gt=0)
    graph_name: str = Field(default=DEFAULT_GRAPH_NAME, min_length=1)
    bootstrap_schema: bool = Field(default=True)
    server_url: str | None = Field(default=None, description="External Singularity Memory server URL; if set, plugin connects to it instead of starting one in-process")
    server_embedded: bool = Field(default=False, description="Start an embedded Singularity Memory server in the Hermes process (ignored if server_url is set)")
    server_mcp_enabled: bool = Field(default=True, description="Expose MCP at /mcp/ when running embedded")
    server_host: str = Field(default="127.0.0.1")
    server_port: int = Field(default=8888, gt=0, le=65535)
    server_profile: str = Field(default="default")
    # LLM Gateway settings for the Singularity Memory server
    llm_base_url: str = Field(default="")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="qwen3.5-9b")
    prefetch_limit: int = Field(default=DEFAULT_PREFETCH_LIMIT, gt=0)
    context_tokens: int = Field(default=DEFAULT_CONTEXT_TOKENS, gt=0)
    rrf_k: int = Field(default=DEFAULT_RRF_K, ge=0)
    tokenizer_name: str = Field(default=DEFAULT_TOKENIZER_NAME)
    vector_index_name: str = Field(default=DEFAULT_VECTOR_INDEX_NAME)
    bm25_index_name: str = Field(default=DEFAULT_BM25_INDEX_NAME)
    pool_min_size: int = Field(default=DEFAULT_POOL_MIN_SIZE, ge=0)
    pool_max_size: int = Field(default=DEFAULT_POOL_MAX_SIZE, gt=0)

    @field_validator("dsn")
    @classmethod
    def validate_dsn(cls, v: str) -> str:
        """Validate DSN format."""
        if v and v.strip():
            valid_prefixes = ("postgresql://", "postgres://", "file://")
            if not any(v.startswith(prefix) for prefix in valid_prefixes):
                raise ValueError(
                    f"DSN must start with one of {valid_prefixes}, got: {v[:20]}..."
                )
        return v

    @field_validator("pool_max_size")
    @classmethod
    def validate_pool_sizes(cls, v: int, info) -> int:
        """Validate pool_max_size >= pool_min_size."""
        if hasattr(info, 'data') and 'pool_min_size' in info.data:
            pool_min_size = info.data['pool_min_size']
            if v < pool_min_size:
                raise ValueError(
                    f"pool_max_size ({v}) must be >= pool_min_size ({pool_min_size})"
                )
        return v

    class Config:
        """Pydantic config."""
        validate_assignment = True
        extra = "forbid"  # Prevent unknown fields


def load_provider_config(hermes_home: str | Path) -> SingularityMemoryConfig:
    """Load the profile-scoped provider config from `$HERMES_HOME`.
    
    Uses Pydantic for automatic validation. Returns default config if file
    doesn't exist or is corrupted.
    
    Raises:
        ValidationError: If configuration validation fails (Pydantic mode)
        ValueError: If configuration validation fails (fallback mode)
    """
    config_path = Path(hermes_home) / CONFIG_FILENAME
    if not config_path.exists():
        return SingularityMemoryConfig()
    
    try:
        with config_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        # Pydantic will automatically validate via Field constraints
        return SingularityMemoryConfig(**payload)
    except (json.JSONDecodeError, TypeError) as e:
        # Fallback to default config if file is corrupted
        return SingularityMemoryConfig()



def save_provider_config(values: dict[str, Any], hermes_home: str | Path) -> None:
    """Persist the provider config under `$HERMES_HOME`.
    
    Merges new values with existing config and validates before saving.
    """
    current_config = load_provider_config(hermes_home)
    
    # Convert Pydantic model to dict, or use dict() if it's a dataclass fallback
    if hasattr(current_config, 'model_dump'):
        current_payload = current_config.model_dump()
    elif hasattr(current_config, 'dict'):
        current_payload = current_config.dict()
    else:
        from dataclasses import asdict
        current_payload = asdict(current_config)
    
    current_payload.update(values)
    
    # Validate merged config
    validated_config = SingularityMemoryConfig(**current_payload)
    
    # Save validated config
    if hasattr(validated_config, 'model_dump'):
        final_payload = validated_config.model_dump()
    elif hasattr(validated_config, 'dict'):
        final_payload = validated_config.dict()
    else:
        from dataclasses import asdict
        final_payload = asdict(validated_config)
    
    config_path = Path(hermes_home) / CONFIG_FILENAME
    config_path.write_text(json.dumps(final_payload, indent=2, sort_keys=True), encoding="utf-8")
    current_config = load_provider_config(hermes_home)
    current_payload = asdict(current_config)
    current_payload.update(values)
    
    config_path = Path(hermes_home) / CONFIG_FILENAME
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(current_payload, f, indent=2, sort_keys=True)
