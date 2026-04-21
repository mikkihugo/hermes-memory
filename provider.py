"""Hermes MemoryProvider implementation for hermes_memory.

## Purpose
Provide a real Hermes-compatible external memory provider backed by
PostgreSQL, VectorChord-BM25, dense embeddings, and reciprocal-rank fusion.
"""

from __future__ import annotations

import json
import logging
import threading
from time import monotonic
from typing import Any

try:
    from agent.memory_provider import MemoryProvider
except ImportError:
    class MemoryProvider:  # type: ignore[override]
        """Fallback base class used outside Hermes."""


try:
    from .config import HermesMemoryConfig, load_provider_config, save_provider_config
    from .install import install_plugin, resolve_install_path
    from .metrics import ProviderMetricsCollector
    from .retrieval import format_context_block_with_token_budget, fuse_candidate_groups
    from .reranker import OpenAICompatibleRerankerClient, RerankerClientConfig
    from .schemas import ALL_TOOL_SCHEMAS
    from .storage import HermesMemoryStorage
except ImportError:
    from config import HermesMemoryConfig, load_provider_config, save_provider_config
    from install import install_plugin, resolve_install_path
    from metrics import ProviderMetricsCollector
    from retrieval import format_context_block_with_token_budget, fuse_candidate_groups
    from reranker import OpenAICompatibleRerankerClient, RerankerClientConfig
    from schemas import ALL_TOOL_SCHEMAS
    from storage import HermesMemoryStorage


logger = logging.getLogger(__name__)
TOOL_NAME_SEARCH = "hermes_memory_search"
TOOL_NAME_CONTEXT = "hermes_memory_context"
TOOL_NAME_STORE = "hermes_memory_store"
TOOL_NAME_FEEDBACK = "hermes_memory_feedback"
TOOL_NAME_GRAPH = "hermes_memory_graph"
TOOL_NAME_METRICS = "hermes_memory_metrics"
UNKNOWN_TOOL_ERROR_TEMPLATE = "Unknown tool: {tool_name}"
OPERATION_PREFETCH = "prefetch"
OPERATION_SYNC_TURN = "sync_turn"
OPERATION_STORE = "store"
OPERATION_SEARCH = "search"
OPERATION_CONTEXT = "context"
OPERATION_FEEDBACK = "feedback"
OPERATION_GRAPH = "graph"


class HermesMemoryProvider(MemoryProvider):
    """Postgres-first external memory provider for Hermes."""

    def __init__(self) -> None:
        self._config = HermesMemoryConfig()
        self._storage: HermesMemoryStorage | None = None
        self._hindsight_client = None
        self._session_id = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_result = ""
        self._prefetch_thread: threading.Thread | None = None
        self._rerankers: list[tuple[OpenAICompatibleRerankerClient, int | None]] = []
        self._metrics = ProviderMetricsCollector()
        self._system_prompt_block = (
            "hermes_memory is active. Use it for durable cross-session recall "
            "about repos, infrastructure, decisions, incidents, and proven "
            "fixes. Retrieved memory is background context, not new user input. "
            "IMPORTANT: If the user says 'Magic Words' like 'Remember when...', "
            "'We did this before...', or 'Check our history...', you MUST "
            "use hermes_memory_search or hermes_memory_context to recall specific episodes."
        )

    @property
    def name(self) -> str:
        """Return the provider name."""
        return "hermes_memory"

    def is_available(self) -> bool:
        """Return whether the provider has enough config to start."""
        try:
            from hermes_constants import get_hermes_home

            config = load_provider_config(str(get_hermes_home()))
            return bool(config.dsn.strip())
        except Exception:
            return False

    def initialize(self, session_id: str, **kwargs) -> None:
        """Initialize the provider for one Hermes session."""
        hermes_home = kwargs.get("hermes_home", "")
        self._session_id = session_id
        self._config = load_provider_config(hermes_home)
        self._storage = HermesMemoryStorage(
            dsn=self._config.dsn,
            embedding_base_url=self._config.embedding_base_url,
            embedding_model=self._config.embedding_model,
            embedding_dimensions=self._config.embedding_dimensions,
            embedding_api_key=self._config.embedding_api_key,
            tokenizer_name=self._config.tokenizer_name,
            vector_index_name=self._config.vector_index_name,
            bm25_index_name=self._config.bm25_index_name,
            pool_min_size=self._config.pool_min_size,
            pool_max_size=self._config.pool_max_size,
            bootstrap_schema=self._config.bootstrap_schema,
            graph_enabled=self._config.graph_enabled,
            graph_name=self._config.graph_name,
        )
        if self._config.hindsight_enabled:
            import os
            os.environ["HINDSIGHT_EMBED_API_DATABASE_URL"] = self._config.dsn
            from hindsight import HindsightEmbedded
            
            # Monkey-patch to avoid uv/uvx in restricted environment
            def custom_find_api_command(self_mgr):
                return ["python3", "-m", "hindsight_api.main"]
            
            from hindsight_embed.daemon_embed_manager import DaemonEmbedManager
            DaemonEmbedManager._find_api_command = custom_find_api_command
            
            self._hindsight_client = HindsightEmbedded(profile=self._config.hindsight_profile)
        self._rerankers = self._build_reranker_pipeline()

    def system_prompt_block(self) -> str:
        """Return static provider instructions for the system prompt."""
        return self._system_prompt_block

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Return fused provider context for the current turn."""
        started_at = self._metrics.start_operation()
        if self._storage is None or not query.strip():
            return ""
        try:
            with self._prefetch_lock:
                if self._prefetch_result:
                    prefetched_result = self._prefetch_result
                    self._prefetch_result = ""
                    self._metrics.record_success(OPERATION_PREFETCH, started_at)
                    return prefetched_result
            fused_candidates = self._search_and_fuse(query=query, limit=self._config.prefetch_limit)
            context_block = format_context_block_with_token_budget(
                fused_candidates=fused_candidates,
                limit=self._config.prefetch_limit,
                token_budget=self._config.context_tokens,
            )
            self._metrics.record_success(OPERATION_PREFETCH, started_at)
            return context_block
        except Exception:
            self._metrics.record_failure(OPERATION_PREFETCH, started_at)
            raise

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Queue background prefetch.

        Runs the next-turn retrieval in a background thread and caches the
        formatted context block.
        """
        if self._storage is None or not query.strip():
            return
        
        # Thread-safe check and thread creation
        with self._prefetch_lock:
            if self._prefetch_thread and self._prefetch_thread.is_alive():
                return

            def run_prefetch() -> None:
                try:
                    fused_candidates = self._search_and_fuse(query=query, limit=self._config.prefetch_limit)
                    prefetched_result = format_context_block_with_token_budget(
                        fused_candidates=fused_candidates,
                        limit=self._config.prefetch_limit,
                        token_budget=self._config.context_tokens,
                    )
                    with self._prefetch_lock:
                        self._prefetch_result = prefetched_result
                except Exception:
                    logger.exception("Failed background prefetch")

            self._prefetch_thread = threading.Thread(
                target=run_prefetch,
                daemon=True,
                name="hermes-memory-prefetch",
            )
            self._prefetch_thread.start()

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        """Persist a completed turn."""
        started_at = self._metrics.start_operation()
        if self._config.hindsight_enabled and self._hindsight_client:
            try:
                self._hindsight_client.client().retain(
                    bank_id=self._config.workspace,
                    content=f"User: {user_content}\nAssistant: {assistant_content}",
                    context="Conversation turn",
                )
                self._metrics.record_success(OPERATION_SYNC_TURN, started_at)
            except Exception:
                self._metrics.record_failure(OPERATION_SYNC_TURN, started_at)
                raise
            return

        if self._storage is None:
            return
        try:
            self._storage.store_turn(
                workspace=self._config.workspace,
                session_id=session_id or self._session_id,
                user_content=user_content,
                assistant_content=assistant_content,
            )
            self._metrics.record_success(OPERATION_SYNC_TURN, started_at)
        except Exception:
            self._metrics.record_failure(OPERATION_SYNC_TURN, started_at)
            raise

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return the provider-specific tool schemas."""
        return list(ALL_TOOL_SCHEMAS)

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs) -> str:
        """Dispatch a provider-specific tool call."""
        if self._storage is None:
            return json.dumps({"error": "hermes_memory is not initialized"})

        handlers = {
            TOOL_NAME_SEARCH: self._handle_search,
            TOOL_NAME_CONTEXT: self._handle_context,
            TOOL_NAME_STORE: self._handle_store,
            TOOL_NAME_FEEDBACK: self._handle_feedback,
            TOOL_NAME_GRAPH: self._handle_graph,
            TOOL_NAME_METRICS: self._handle_metrics,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return json.dumps({"error": UNKNOWN_TOOL_ERROR_TEMPLATE.format(tool_name=tool_name)})

        try:
            return handler(args)
        except Exception as e:
            logger.exception("Error handling tool call: %s", tool_name)
            return json.dumps({"error": str(e)})

    def _handle_search(self, args: dict[str, Any]) -> str:
        started_at = self._metrics.start_operation()
        query = str(args.get("query", "")).strip()
        if not query:
            return json.dumps({"error": "Missing required parameter: query"})
        
        limit = int(args.get("limit", self._config.prefetch_limit))
        fused_candidates = self._search_and_fuse(query=query, limit=limit)
        self._metrics.record_success(OPERATION_SEARCH, started_at)
        
        return json.dumps(
            {
                "results": [
                    {
                        "memory_item_id": c.memory_item_id,
                        "content": c.content,
                        "source_uri": c.source_uri,
                        "confidence": c.confidence,
                        "fused_score": c.fused_score,
                    }
                    for c in fused_candidates[:limit]
                ]
            }
        )

    def _handle_context(self, args: dict[str, Any]) -> str:
        started_at = self._metrics.start_operation()
        query = str(args.get("query", "")).strip()
        if not query:
            return json.dumps({"error": "Missing required parameter: query"})
        
        token_budget = int(args.get("token_budget", self._config.context_tokens))
        fused_candidates = self._search_and_fuse(query=query, limit=self._config.prefetch_limit)
        self._metrics.record_success(OPERATION_CONTEXT, started_at)
        
        return json.dumps(
            {
                "context": format_context_block_with_token_budget(
                    fused_candidates=fused_candidates,
                    limit=self._config.prefetch_limit,
                    token_budget=token_budget,
                )
            }
        )

    def _handle_store(self, args: dict[str, Any]) -> str:
        started_at = self._metrics.start_operation()
        content = str(args.get("content", "")).strip()
        if not content:
            return json.dumps({"error": "Missing required parameter: content"})
        
        source_uri = str(args.get("source_uri", "manual://hermes_memory_store")).strip()
        memory_item_id = self._storage.store_memory_item(  # type: ignore[union-attr]
            workspace=self._config.workspace,
            content=content,
            source_uri=source_uri,
        )
        self._metrics.record_success(OPERATION_STORE, started_at)
        return json.dumps({"memory_item_id": memory_item_id, "stored": True})

    def _handle_feedback(self, args: dict[str, Any]) -> str:
        started_at = self._metrics.start_operation()
        memory_item_id = str(args.get("memory_item_id", "")).strip()
        if not memory_item_id:
            return json.dumps({"error": "Missing required parameter: memory_item_id"})
        
        helpful = bool(args.get("helpful", False))
        self._storage.store_feedback(memory_item_id=memory_item_id, helpful=helpful)  # type: ignore[union-attr]
        self._metrics.record_success(OPERATION_FEEDBACK, started_at)
        return json.dumps({"memory_item_id": memory_item_id, "helpful": helpful})

    def _handle_graph(self, args: dict[str, Any]) -> str:
        started_at = self._metrics.start_operation()
        query = str(args.get("query", "")).strip()
        if not query:
            return json.dumps({"error": "Missing required parameter: query"})
        
        limit = int(args.get("limit", self._config.graph_limit))
        graph_candidates = self._storage.search_graph(  # type: ignore[union-attr]
            workspace=self._config.workspace,
            query=query,
            limit=limit,
        )
        self._metrics.record_success(OPERATION_GRAPH, started_at)
        return json.dumps(
            {
                "results": [
                    {
                        "memory_item_id": c.memory_item_id,
                        "content": c.content,
                        "source_uri": c.source_uri,
                        "confidence": c.confidence,
                        "rank": c.rank,
                        "lane": c.lane,
                    }
                    for c in graph_candidates
                ]
            }
        )

    def _handle_metrics(self, args: dict[str, Any]) -> str:
        return json.dumps({"metrics": self._metrics.snapshot().to_payload()})

    def shutdown(self) -> None:
        """Clean shutdown hook."""
        if self._prefetch_thread and self._prefetch_thread.is_alive():
            self._prefetch_thread.join(timeout=5.0)
        if self._storage is not None:
            self._storage.close()

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """Session-end extraction hook.

        Stores a compact session-end summary as durable memory.
        """
        if self._storage is None or not messages:
            return
            
        summary = self._extract_recent_facts(messages, limit=6)
        if not summary:
            return
            
        self._storage.store_memory_item(
            workspace=self._config.workspace,
            content=f"Session summary:\n{summary}",
            source_uri=f"session-end://{self._session_id}",
        )

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        """Return a compact memory summary before Hermes compresses context."""
        summary = self._extract_recent_facts(messages, limit=4)
        if not summary:
            return ""
        return f"Preserve these session facts:\n{summary}"

    def _extract_recent_facts(self, messages: list[dict[str, Any]], limit: int) -> str:
        """Extract recent conversation fragments for summary storage."""
        fragments = [
            f"{m.get('role', 'unknown')}: {str(m.get('content', '')).strip()}"
            for m in messages[-limit:]
            if str(m.get("content", "")).strip()
        ]
        return "\n".join(fragments)

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        """Mirror built-in memory writes to the durable backend."""
        if self._storage is None:
            return
        self._storage.mirror_builtin_write(
            workspace=self._config.workspace,
            action=action,
            target=target,
            content=content,
        )

    def get_config_schema(self) -> list[dict[str, Any]]:
        """Return setup fields for `hermes memory setup`."""
        return [
            {
                "key": "dsn",
                "description": "Backend DSN. Use postgres://... or file:///absolute/path.json",
                "required": True,
            },
            {
                "key": "workspace",
                "description": "Workspace identifier stored with memory items",
                "default": "hermes",
            },
            {
                "key": "embedding_base_url",
                "description": "OpenAI-compatible base URL for embeddings",
                "default": "https://llm-gateway.centralcloud.com/v1",
            },
            {
                "key": "embedding_model",
                "description": "Embedding model name for v1/embeddings (default stack: Qwen3 4B, 2560D)",
                "default": "qwen3-embedding-4b",
            },
            {
                "key": "embedding_dimensions",
                "description": "Dense embedding width for VectorChord storage",
                "default": 2560,
            },
            {
                "key": "rerank_enabled",
                "description": "Use a reranker after RRF fusion",
                "default": False,
            },
            {
                "key": "rerank_base_url",
                "description": "OpenAI-like base URL for rerankers",
                "default": "https://llm-embedding.centralcloud.com/v1",
            },
            {
                "key": "rerank_model",
                "description": "Reranker model name on the reranker endpoint (for example the Qwen3 0.6B or 4B reranker)",
                "default": "",
            },
            {
                "key": "rerank_fast_model",
                "description": "Fast first-stage reranker model, typically the smaller Qwen3 reranker",
                "default": "",
            },
            {
                "key": "rerank_deep_model",
                "description": "Second-stage reranker model, typically the stronger Qwen3 4B reranker",
                "default": "",
            },
            {
                "key": "graph_enabled",
                "description": "Enable AGE graph projection and graph recall",
                "default": False,
            },
            {
                "key": "graph_name",
                "description": "AGE graph name used for memory projection",
                "default": "hermes_memory_graph",
            },
            {
                "key": "bootstrap_schema",
                "description": "Create required extensions, tables, tokenizer, and indexes on initialize",
                "default": True,
            },
            {
                "key": "hindsight_enabled",
                "description": "Use Hindsight memory engine",
                "default": False,
            },
            {
                "key": "hindsight_profile",
                "description": "Hindsight profile name",
                "default": "hermes",
            },
            {
                "key": "pool_min_size",
                "description": "Minimum number of pooled Postgres connections",
                "default": 1,
            },
            {
                "key": "pool_max_size",
                "description": "Maximum number of pooled Postgres connections",
                "default": 4,
            },
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        """Persist provider-local config into `$HERMES_HOME`."""
        save_provider_config(values=values, hermes_home=hermes_home)

    def _search_and_fuse(self, query: str, limit: int) -> list[Any]:
        """Run lexical/vector retrieval, fuse, and optionally rerank."""
        if self._config.hindsight_enabled and self._hindsight_client:
            try:
                from .retrieval import MemoryCandidate
                result = self._hindsight_client.client().recall(
                    bank_id=self._config.workspace,
                    query=query,
                )
                candidates = []
                for i, fact in enumerate(result.facts):
                    candidates.append(MemoryCandidate(
                        memory_item_id=fact.fact_id,
                        content=fact.content,
                        source_uri="hindsight",
                        confidence=1.0,
                        rank=i+1,
                        lane="hindsight"
                    ))
                return candidates
            except Exception:
                logger.warning("Hindsight recall failed; falling back to standard retrieval")

        lexical_candidates = []
        vector_candidates = []
        graph_candidates = []

        if self._config.vector_enabled:
            try:
                vector_candidates = self._storage.search_vector(  # type: ignore[union-attr]
                    workspace=self._config.workspace,
                    query=query,
                    limit=limit,
                )
            except Exception:
                logger.warning("Vector search failed; falling back to expanded lexical retrieval")
                # Boost lexical limit if vector fails to ensure we still have enough candidates
                if self._config.lexical_enabled:
                    lexical_candidates = self._storage.search_lexical(  # type: ignore[union-attr]
                        workspace=self._config.workspace,
                        query=query,
                        limit=limit * 2,
                    )

        # Only run lexical if it wasn't already run by the fallback above
        if self._config.lexical_enabled and not lexical_candidates:
            lexical_candidates = self._storage.search_lexical(  # type: ignore[union-attr]
                workspace=self._config.workspace,
                query=query,
                limit=limit,
            )

        if self._config.graph_enabled:
            try:
                graph_candidates = self._storage.search_graph(  # type: ignore[union-attr]
                    workspace=self._config.workspace,
                    query=query,
                    limit=self._config.graph_limit,
                )
            except Exception:
                logger.exception("Graph search failed")

        fused_candidates = fuse_candidate_groups(
            candidate_groups=[lexical_candidates, vector_candidates, graph_candidates],
            rrf_k=self._config.rrf_k,
            weights=[
                self._config.lexical_weight,
                self._config.vector_weight,
                self._config.graph_weight,
            ],
        )

        if not self._rerankers or not fused_candidates:
            return fused_candidates

        return self._apply_reranking(query, fused_candidates)

    def _apply_reranking(self, query: str, candidates: list[Any]) -> list[Any]:
        """Apply the configured reranker pipeline to fused candidates."""
        reranked = candidates
        for reranker_client, stage_limit in self._rerankers:
            if not reranked:
                break
            
            top_n = min(stage_limit or self._config.rerank_top_n, len(reranked))
            try:
                reranked = reranker_client.rerank(
                    query=query,
                    candidates=reranked,
                    top_n=top_n,
                )
            except Exception:
                logger.exception("Rerank stage failed; using previous ranking")
                
        return reranked

    def install(self, hermes_home: str, *, symlink: bool = True) -> str:
        """Install this provider repo into the Hermes plugin directory."""
        installed_path = install_plugin(
            source_directory=_get_plugin_dir(),
            hermes_home=hermes_home,
            symlink=symlink,
        )
        return str(installed_path)

    def get_install_path(self, hermes_home: str) -> str:
        """Return the canonical install path for this provider."""
        return str(resolve_install_path(hermes_home))

    def _build_reranker_pipeline(self) -> list[tuple[OpenAICompatibleRerankerClient, int | None]]:
        """Return the configured reranker pipeline."""
        if not self._config.rerank_enabled:
            return []
            
        pipeline: list[tuple[OpenAICompatibleRerankerClient, int | None]] = []
        
        # Single model override
        if self._config.rerank_model.strip():
            client = OpenAICompatibleRerankerClient(
                RerankerClientConfig(
                    base_url=self._config.rerank_base_url,
                    model=self._config.rerank_model,
                    api_key=self._config.rerank_api_key,
                )
            )
            return [(client, self._config.rerank_top_n)]

        # Multi-stage pipeline
        if self._config.rerank_fast_model.strip():
            pipeline.append((
                OpenAICompatibleRerankerClient(
                    RerankerClientConfig(
                        base_url=self._config.rerank_base_url,
                        model=self._config.rerank_fast_model,
                        api_key=self._config.rerank_api_key,
                    )
                ),
                self._config.rerank_top_n
            ))
            
        if self._config.rerank_deep_model.strip():
            pipeline.append((
                OpenAICompatibleRerankerClient(
                    RerankerClientConfig(
                        base_url=self._config.rerank_base_url,
                        model=self._config.rerank_deep_model,
                        api_key=self._config.rerank_api_key,
                    )
                ),
                self._config.rerank_deep_top_n
            ))
            
        return pipeline


def _get_plugin_dir() -> str:
    """Return the plugin repo directory used for install flows."""
    from pathlib import Path
    return str(Path(__file__).resolve().parent)
