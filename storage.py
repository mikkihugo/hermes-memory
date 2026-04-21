"""Storage backend for the hermes_memory provider.

## Purpose
Provide a PostgreSQL-first backend with connection pooling, versioned schema
migrations, VectorChord vector retrieval, VectorChord-BM25 lexical retrieval,
and optional AGE graph projection. A local JSON fallback remains available for
development and tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg import Cursor
    from psycopg_pool import ConnectionPool
except ImportError:
    psycopg = None  # type: ignore
    Cursor = Any  # type: ignore
    ConnectionPool = Any  # type: ignore

try:
    from .embeddings import EmbeddingClientConfig, OpenAICompatibleEmbeddingClient
    from .retrieval import MemoryCandidate
except ImportError:
    from embeddings import EmbeddingClientConfig, OpenAICompatibleEmbeddingClient
    from retrieval import MemoryCandidate


POSTGRESQL_DSN_PREFIX = "postgresql://"
POSTGRES_DSN_PREFIX = "postgres://"
FILE_DSN_PREFIX = "file://"
DEFAULT_LOCAL_STORAGE_FILENAME = "hermes-memory.json"
DEFAULT_SOURCE_URI = "session://turn"
CURRENT_SCHEMA_VERSION = 2
MINIMUM_GRAPH_TOKEN_LENGTH = 3
MAX_CONTENT_LENGTH = 100_000  # 100KB max for content
try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default


MAX_SOURCE_URI_LENGTH = 2048  # Standard URL max length
MAX_WORKSPACE_LENGTH = 256

# BM25 retrieval constants
BM25_TOPK_MULTIPLIER = 4  # Retrieve 4x requested limit for better ranking
BM25_TOPK_MINIMUM = 100  # Always retrieve at least 100 candidates for BM25

HERMES_MEMORY_ITEMS_TABLE = "hermes_memory_items"
HERMES_MEMORY_TURNS_TABLE = "hermes_memory_turns"
HERMES_MEMORY_FEEDBACK_TABLE = "hermes_memory_feedback"
HERMES_MEMORY_SCHEMA_VERSION_TABLE = "hermes_memory_schema_version"
HERMES_MEMORY_SCHEMA_NAME = "hermes_memory"


class MemoryItemRecord(BaseModel):
    """Stored memory item record with validation."""

    memory_item_id: str = Field(..., min_length=1, description="Unique memory item ID")
    workspace: str = Field(..., min_length=1, max_length=256, description="Workspace identifier")
    content: str = Field(..., min_length=1, max_length=100_000, description="Memory content")
    source_uri: str = Field(..., min_length=1, max_length=2048, description="Source URI")
    helpful_count: int = Field(default=0, ge=0, description="Number of helpful feedbacks")
    unhelpful_count: int = Field(default=0, ge=0, description="Number of unhelpful feedbacks")
    created_at: str = Field(..., description="ISO format creation timestamp")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


class TurnRecord(BaseModel):
    """Stored turn record with validation."""

    turn_id: str = Field(..., min_length=1, description="Unique turn ID")
    workspace: str = Field(..., min_length=1, max_length=256, description="Workspace identifier")
    session_id: str = Field(..., min_length=1, description="Session identifier")
    user_content: str = Field(..., min_length=1, description="User message content")
    assistant_content: str = Field(..., min_length=1, description="Assistant response content")
    created_at: str = Field(..., description="ISO format creation timestamp")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


class HermesMemoryStorageProtocol(Protocol):
    """Backend contract for hermes_memory storage."""

    def search_lexical(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the BM25 lexical lane."""
        ...

    def search_vector(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the VectorChord semantic lane."""
        ...

    def search_graph(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the AGE graph lane."""
        ...

    def store_turn(self, workspace: str, session_id: str, user_content: str, assistant_content: str) -> None:
        """Persist a completed conversation turn."""
        ...

    def store_memory_item(self, workspace: str, content: str, source_uri: str) -> str:
        """Persist one explicit durable memory item."""
        ...

    def store_feedback(self, memory_item_id: str, helpful: bool) -> None:
        """Persist helpfulness feedback for one memory item."""
        ...

    def mirror_builtin_write(self, workspace: str, action: str, target: str, content: str) -> None:
        """Mirror a built-in Hermes memory write into durable storage."""
        ...

    def close(self) -> None:
        """Release backend resources."""
        ...


class HermesMemoryStorage:
    """Durable storage adapter for Hermes memory."""

    def __init__(
        self,
        dsn: str,
        embedding_base_url: str,
        embedding_model: str,
        embedding_dimensions: int,
        embedding_api_key: str | None,
        tokenizer_name: str,
        vector_index_name: str,
        bm25_index_name: str,
        pool_min_size: int,
        pool_max_size: int,
        bootstrap_schema: bool,
        graph_enabled: bool,
        graph_name: str,
    ) -> None:
        """Initialize the storage backend."""
        if not dsn.strip():
            raise ValueError("Storage DSN must not be empty.")
        self._dsn = dsn
        self._tokenizer_name = tokenizer_name
        self._vector_index_name = vector_index_name
        self._bm25_index_name = bm25_index_name
        self._graph_enabled = graph_enabled
        self._graph_name = graph_name
        self._embedding_dimensions = embedding_dimensions
        self._embedding_client = OpenAICompatibleEmbeddingClient(
            EmbeddingClientConfig(
                base_url=embedding_base_url,
                model=embedding_model,
                dimensions=embedding_dimensions,
                api_key=embedding_api_key,
            )
        )
        self._local_storage_path = self._resolve_local_storage_path(dsn)
        self._is_postgres_backend = dsn.startswith((POSTGRESQL_DSN_PREFIX, POSTGRES_DSN_PREFIX))
        self._pool: ConnectionPool | None = None
        if self._is_postgres_backend:
            self._pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=pool_min_size,
                max_size=pool_max_size,
                open=True,
            )
            if bootstrap_schema:
                self._ensure_postgres_schema()
        else:
            self._ensure_local_storage_file_exists()

    def search_lexical(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the BM25 lexical lane."""
        if self._is_postgres_backend:
            return self._search_lexical_postgres(workspace=workspace, query=query, limit=limit)
        return self._search_local(workspace=workspace, query=query, limit=limit, lane="lexical")

    def search_vector(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the VectorChord semantic lane."""
        if self._is_postgres_backend:
            return self._search_vector_postgres(workspace=workspace, query=query, limit=limit)
        return self._search_local(workspace=workspace, query=query, limit=limit, lane="vector")

    def search_graph(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run the AGE graph lane."""
        if not self._graph_enabled:
            return []
        if self._is_postgres_backend:
            return self._search_graph_postgres(workspace=workspace, query=query, limit=limit)
        return []

    def store_turn(self, workspace: str, session_id: str, user_content: str, assistant_content: str) -> None:
        """Persist a completed conversation turn."""
        turn_record = TurnRecord(
            turn_id=self._generate_identifier(),
            workspace=workspace,
            session_id=session_id,
            user_content=user_content,
            assistant_content=assistant_content,
            created_at=self._utc_now_isoformat(),
        )
        if self._is_postgres_backend:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO {HERMES_MEMORY_TURNS_TABLE} (
                            turn_id,
                            workspace,
                            session_id,
                            user_content,
                            assistant_content,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            turn_record.turn_id,
                            turn_record.workspace,
                            turn_record.session_id,
                            turn_record.user_content,
                            turn_record.assistant_content,
                            turn_record.created_at,
                        ),
                    )
                connection.commit()
            self.store_memory_item(
                workspace=workspace,
                content=f"User: {user_content}\nAssistant: {assistant_content}",
                source_uri=DEFAULT_SOURCE_URI,
            )
            return
        payload = self._read_local_payload()
        payload["turns"].append(_model_to_dict(turn_record))
        self._write_local_payload(payload)
        self.store_memory_item(
            workspace=workspace,
            content=f"User: {user_content}\nAssistant: {assistant_content}",
            source_uri=DEFAULT_SOURCE_URI,
        )

    def store_memory_item(self, workspace: str, content: str, source_uri: str) -> str:
        """Persist one explicit durable memory item.
        
        Args:
            workspace: Workspace identifier (max 256 chars)
            content: Memory content (max 100KB)
            source_uri: Source URI (max 2048 chars)
            
        Returns:
            The memory item ID
            
        Raises:
            ValueError: If input validation fails
        """
        # Input validation
        if not workspace or not workspace.strip():
            raise ValueError("Workspace cannot be empty")
        if len(workspace) > MAX_WORKSPACE_LENGTH:
            raise ValueError(f"Workspace exceeds maximum length of {MAX_WORKSPACE_LENGTH}")
        if not content or not content.strip():
            raise ValueError("Content cannot be empty")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"Content exceeds maximum length of {MAX_CONTENT_LENGTH}")
        if not source_uri or not source_uri.strip():
            raise ValueError("Source URI cannot be empty")
        if len(source_uri) > MAX_SOURCE_URI_LENGTH:
            raise ValueError(f"Source URI exceeds maximum length of {MAX_SOURCE_URI_LENGTH}")
        
        memory_item_record = MemoryItemRecord(
            memory_item_id=self._generate_identifier(),
            workspace=workspace.strip(),
            content=content.strip(),
            source_uri=source_uri.strip(),
            helpful_count=0,
            unhelpful_count=0,
            created_at=self._utc_now_isoformat(),
        )
        if self._is_postgres_backend:
            # Generate embedding with error handling
            try:
                embedding = self._embedding_client.embed_text(content)
                vector_literal = self._format_vector_literal(embedding)
            except Exception as e:
                logger.warning(
                    f"Embedding generation failed for memory item, using zero vector: {e}",
                    extra={"workspace": workspace, "source_uri": source_uri},
                )
                # Use zero vector as fallback to allow storage to proceed
                embedding = [0.0] * self._embedding_dimensions
                vector_literal = self._format_vector_literal(embedding)
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO {HERMES_MEMORY_ITEMS_TABLE} (
                            memory_item_id,
                            workspace,
                            content,
                            source_uri,
                            confidence,
                            embedding,
                            bm25,
                            created_at,
                            updated_at
                        ) VALUES (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s::vector,
                            tokenize(%s, %s),
                            %s,
                            %s
                        )
                        """,
                        (
                            memory_item_record.memory_item_id,
                            workspace,
                            content,
                            source_uri,
                            self._compute_feedback_confidence(memory_item_record),
                            vector_literal,
                            content,
                            self._tokenizer_name,
                            memory_item_record.created_at,
                            memory_item_record.created_at,
                        ),
                    )
                    if self._graph_enabled:
                        self._upsert_graph_projection(cursor=cursor, memory_item=memory_item_record)
                connection.commit()
            return memory_item_record.memory_item_id

        payload = self._read_local_payload()
        payload["memory_items"].append(_model_to_dict(memory_item_record))
        self._write_local_payload(payload)
        return memory_item_record.memory_item_id

    def store_feedback(self, memory_item_id: str, helpful: bool) -> None:
        """Persist helpfulness feedback for one memory item."""
        if self._is_postgres_backend:
            feedback_id = self._generate_identifier()
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        INSERT INTO {HERMES_MEMORY_FEEDBACK_TABLE} (
                            feedback_id,
                            memory_item_id,
                            helpful,
                            created_at
                        ) VALUES (%s, %s, %s, %s)
                        """,
                        (feedback_id, memory_item_id, helpful, self._utc_now_isoformat()),
                    )
                    cursor.execute(
                        f"""
                        UPDATE {HERMES_MEMORY_ITEMS_TABLE}
                        SET confidence = (
                            SELECT GREATEST(
                                0.1,
                                LEAST(
                                    1.0,
                                    0.5
                                    + 0.1 * COALESCE(SUM(CASE WHEN helpful THEN 1 ELSE 0 END), 0)
                                    - 0.1 * COALESCE(SUM(CASE WHEN helpful THEN 0 ELSE 1 END), 0)
                                )
                            )
                            FROM {HERMES_MEMORY_FEEDBACK_TABLE}
                            WHERE memory_item_id = %s
                        ),
                        updated_at = NOW()
                        WHERE memory_item_id = %s
                        """,
                        (memory_item_id, memory_item_id),
                    )
                connection.commit()
            return

        payload = self._read_local_payload()
        payload["feedback"].append(
            {
                "feedback_id": self._generate_identifier(),
                "memory_item_id": memory_item_id,
                "helpful": helpful,
                "created_at": self._utc_now_isoformat(),
            }
        )
        for memory_item in payload["memory_items"]:
            if memory_item["memory_item_id"] != memory_item_id:
                continue
            field_name = "helpful_count" if helpful else "unhelpful_count"
            memory_item[field_name] += 1
            break
        self._write_local_payload(payload)

    def mirror_builtin_write(self, workspace: str, action: str, target: str, content: str) -> None:
        """Mirror a built-in Hermes memory write into durable storage."""
        if action == "remove" or not content.strip():
            return
        self.store_memory_item(
            workspace=workspace,
            content=content,
            source_uri=f"builtin://{action}/{target}",
        )

    def close(self) -> None:
        """Release backend resources."""
        if self._pool is not None:
            self._pool.close()

    def _search_lexical_postgres(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run lexical retrieval using VectorChord-BM25."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Boost topk for better RRF coverage
                topk = int(max(limit * 4, 100))
                cur.execute(f"SET LOCAL bm25.topk = {topk}")
                cur.execute(
                    f"""
                    SELECT
                        memory_item_id,
                        content,
                        source_uri,
                        confidence,
                        bm25 <&> to_bm25query(%s, tokenize(%s, %s)) AS bm25_rank
                    FROM {HERMES_MEMORY_ITEMS_TABLE}
                    WHERE workspace = %s
                    ORDER BY bm25_rank
                    LIMIT %s
                    """,
                    (self._bm25_index_name, query, self._tokenizer_name, workspace, limit),
                )
                rows = cur.fetchall()
        
        return [
            MemoryCandidate(
                memory_item_id=str(row[0]),
                content=str(row[1]),
                source_uri=str(row[2]),
                confidence=float(row[3]),
                rank=idx,
                lane="lexical",
            )
            for idx, row in enumerate(rows, start=1)
        ]

    def _search_vector_postgres(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run semantic retrieval using VectorChord.
        
        Raises:
            Exception: If embedding generation fails (caller should handle gracefully)
        """
        try:
            query_embedding = self._embedding_client.embed_text(query)
            vector_literal = self._format_vector_literal(query_embedding)
        except Exception as e:
            logger.error(
                f"Embedding generation failed for vector search query: {e}",
                extra={"workspace": workspace, "query_preview": query[:100]},
            )
            # Re-raise to allow caller to fall back to lexical search
            raise
        
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        memory_item_id,
                        content,
                        source_uri,
                        confidence,
                        embedding <-> %s::vector AS vector_rank
                    FROM {HERMES_MEMORY_ITEMS_TABLE}
                    WHERE workspace = %s
                    ORDER BY vector_rank
                    LIMIT %s
                    """,
                    (vector_literal, workspace, limit),
                )
                rows = cur.fetchall()
        
        return [
            MemoryCandidate(
                memory_item_id=str(row[0]),
                content=str(row[1]),
                source_uri=str(row[2]),
                confidence=float(row[3]),
                rank=idx,
                lane="vector",
            )
            for idx, row in enumerate(rows, start=1)
        ]

    def _search_graph_postgres(self, workspace: str, query: str, limit: int) -> list[MemoryCandidate]:
        """Run one-hop AGE graph expansion around seed matches."""
        query_tokens = self._tokenize_graph_query(query)
        if not query_tokens:
            return []
        graph_candidates: list[MemoryCandidate] = []
        seen_memory_item_ids: set[str] = set()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._prepare_age_cursor(cursor)
                seed_rows = self._run_age_query(
                    cursor=cursor,
                    cypher_query=self._build_seed_graph_query(workspace=workspace, query_tokens=query_tokens, limit=limit),
                )
                for row in seed_rows:
                    candidate = self._memory_candidate_from_age_row(row=row, rank=len(graph_candidates) + 1)
                    if candidate.memory_item_id in seen_memory_item_ids:
                        continue
                    seen_memory_item_ids.add(candidate.memory_item_id)
                    graph_candidates.append(candidate)
                related_rows = self._run_age_query(
                    cursor=cursor,
                    cypher_query=self._build_related_graph_query(workspace=workspace, query_tokens=query_tokens, limit=limit),
                )
                for row in related_rows:
                    candidate = self._memory_candidate_from_age_row(row=row, rank=len(graph_candidates) + 1)
                    if candidate.memory_item_id in seen_memory_item_ids:
                        continue
                    seen_memory_item_ids.add(candidate.memory_item_id)
                    graph_candidates.append(candidate)
                    if len(graph_candidates) >= limit:
                        break
        return graph_candidates[:limit]

    def _search_local(self, workspace: str, query: str, limit: int, lane: str) -> list[MemoryCandidate]:
        """Run development-only local retrieval."""
        memory_items = [
            MemoryItemRecord(**memory_item)
            for memory_item in self._read_local_payload()["memory_items"]
            if memory_item["workspace"] == workspace
        ]
        scored_candidates = [
            MemoryCandidate(
                memory_item_id=memory_item.memory_item_id,
                content=memory_item.content,
                source_uri=memory_item.source_uri,
                confidence=self._score_local_memory_item(memory_item=memory_item, query=query, lane=lane),
                rank=index,
                lane=lane,
            )
            for index, memory_item in enumerate(
                sorted(
                    (
                        memory_item
                        for memory_item in memory_items
                        if self._score_local_memory_item(memory_item=memory_item, query=query, lane=lane) > 0.0
                    ),
                    key=lambda item: self._score_local_memory_item(memory_item=item, query=query, lane=lane),
                    reverse=True,
                )[:limit],
                start=1,
            )
        ]
        return scored_candidates

    def _ensure_postgres_schema(self) -> None:
        """Create required extensions, tables, indexes, and optional graph state."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._ensure_schema_version_table(cursor)
                current_version = self._read_schema_version(cursor)
                if current_version < 1:
                    self._apply_schema_migration_v1(cursor)
                    self._write_schema_version(cursor, 1)
                if current_version < 2:
                    self._apply_schema_migration_v2(cursor)
                    self._write_schema_version(cursor, 2)
                if self._graph_enabled:
                    self._ensure_age_graph(cursor)
            connection.commit()

    def _ensure_schema_version_table(self, cursor: Cursor[Any]) -> None:
        """Create the schema-version table when absent."""
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERMES_MEMORY_SCHEMA_VERSION_TABLE} (
                schema_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL
            )
            """
        )

    def _read_schema_version(self, cursor: Cursor[Any]) -> int:
        """Return the applied schema version."""
        cursor.execute(
            f"""
            SELECT version
            FROM {HERMES_MEMORY_SCHEMA_VERSION_TABLE}
            WHERE schema_name = %s
            """,
            (HERMES_MEMORY_SCHEMA_NAME,),
        )
        row = cursor.fetchone()
        if row is None:
            return 0
        return int(row[0])

    def _write_schema_version(self, cursor: Cursor[Any], version: int) -> None:
        """Persist the current schema version."""
        cursor.execute(
            f"""
            INSERT INTO {HERMES_MEMORY_SCHEMA_VERSION_TABLE} (schema_name, version)
            VALUES (%s, %s)
            ON CONFLICT (schema_name)
            DO UPDATE SET version = EXCLUDED.version
            """,
            (HERMES_MEMORY_SCHEMA_NAME, version),
        )

    def _apply_schema_migration_v1(self, cursor: Cursor[Any]) -> None:
        """Apply the base schema migration."""
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vchord CASCADE")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_tokenizer CASCADE")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vchord_bm25 CASCADE")
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERMES_MEMORY_ITEMS_TABLE} (
                memory_item_id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                content TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                embedding vector({self._embedding_dimensions}),
                bm25 bm25vector,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERMES_MEMORY_TURNS_TABLE} (
                turn_id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_content TEXT NOT NULL,
                assistant_content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HERMES_MEMORY_FEEDBACK_TABLE} (
                feedback_id TEXT PRIMARY KEY,
                memory_item_id TEXT NOT NULL REFERENCES {HERMES_MEMORY_ITEMS_TABLE}(memory_item_id),
                helpful BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )

    def _apply_schema_migration_v2(self, cursor: Cursor[Any]) -> None:
        """Apply indexes and tokenizer provisioning."""
        cursor.execute(
            f"""
            DO $$
            BEGIN
                PERFORM create_tokenizer('{self._tokenizer_name}', $tokenizer$
                tokenizer = 'unicode'
                stopwords = 'nltk'
                $tokenizer$);
            EXCEPTION
                WHEN OTHERS THEN
                    NULL;
            END
            $$;
            """
        )
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {self._vector_index_name} "
            f"ON {HERMES_MEMORY_ITEMS_TABLE} USING vchordrq (embedding vector_l2_ops)"
        )
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {self._bm25_index_name} "
            f"ON {HERMES_MEMORY_ITEMS_TABLE} USING bm25 (bm25 bm25_ops)"
        )
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {HERMES_MEMORY_ITEMS_TABLE}_workspace_idx "
            f"ON {HERMES_MEMORY_ITEMS_TABLE} (workspace)"
        )
        # Add index on feedback table for performance
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {HERMES_MEMORY_FEEDBACK_TABLE}_memory_item_id_idx "
            f"ON {HERMES_MEMORY_FEEDBACK_TABLE} (memory_item_id)"
        )

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection[Any]]:
        """Yield a pooled or direct Postgres connection."""
        if self._pool is not None:
            with self._pool.connection() as connection:
                yield connection
            return
        connection = psycopg.connect(self._dsn)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _resolve_local_storage_path(dsn: str) -> Path:
        """Resolve the local JSON storage path for development mode."""
        if dsn.startswith(FILE_DSN_PREFIX):
            return Path(dsn.removeprefix(FILE_DSN_PREFIX))
        return Path.cwd() / DEFAULT_LOCAL_STORAGE_FILENAME

    def _ensure_local_storage_file_exists(self) -> None:
        """Create the local JSON storage file when absent."""
        if self._local_storage_path.exists():
            return
        self._local_storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_local_payload({"memory_items": [], "turns": [], "feedback": []})

    def _read_local_payload(self) -> dict[str, Any]:
        """Read the local JSON storage payload."""
        return json.loads(self._local_storage_path.read_text())

    def _write_local_payload(self, payload: dict[str, Any]) -> None:
        """Write the local JSON storage payload."""
        self._local_storage_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def _ensure_age_graph(self, cursor: Cursor[Any]) -> None:
        """Create the AGE graph when graph support is enabled."""
        cursor.execute("CREATE EXTENSION IF NOT EXISTS age")
        cursor.execute(
            "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s",
            (self._graph_name,),
        )
        if cursor.fetchone() is None:
            cursor.execute("SELECT ag_catalog.create_graph(%s)", (self._graph_name,))

    def _upsert_graph_projection(self, cursor: Cursor[Any], memory_item: MemoryItemRecord) -> None:
        """Project one memory item into AGE."""
        self._prepare_age_cursor(cursor)
        cypher_query = f"""
        MERGE (w:Workspace {{name: {self._to_cypher_string_literal(memory_item.workspace)}}})
        MERGE (s:Source {{uri: {self._to_cypher_string_literal(memory_item.source_uri)}}})
        MERGE (m:MemoryItem {{memory_item_id: {self._to_cypher_string_literal(memory_item.memory_item_id)}}})
        SET m.workspace = {self._to_cypher_string_literal(memory_item.workspace)},
            m.content = {self._to_cypher_string_literal(memory_item.content)},
            m.source_uri = {self._to_cypher_string_literal(memory_item.source_uri)},
            m.confidence = {self._compute_feedback_confidence(memory_item)}
        MERGE (w)-[:CONTAINS]->(m)
        MERGE (m)-[:FROM_SOURCE]->(s)
        RETURN m.memory_item_id
        """
        self._run_age_write_query(cursor=cursor, cypher_query=cypher_query)

    def _prepare_age_cursor(self, cursor: Cursor[Any]) -> None:
        """Prepare one cursor for AGE operations."""
        cursor.execute("LOAD 'age'")
        cursor.execute('SET search_path = ag_catalog, "$user", public')

    def _run_age_query(self, cursor: Cursor[Any], cypher_query: str) -> list[tuple[Any, ...]]:
        """Execute one AGE cypher query and return raw rows."""
        cursor.execute(
            f"""
            SELECT *
            FROM ag_catalog.cypher(%s, %s) AS (
                memory_item_id agtype,
                content agtype,
                source_uri agtype,
                confidence agtype
            )
            """,
            (self._graph_name, cypher_query),
        )
        return cursor.fetchall()

    def _run_age_write_query(self, cursor: Cursor[Any], cypher_query: str) -> None:
        """Execute one AGE write query."""
        cursor.execute(
            """
            SELECT *
            FROM ag_catalog.cypher(%s, %s) AS (result agtype)
            """,
            (self._graph_name, cypher_query),
        )

    def _build_seed_graph_query(self, workspace: str, query_tokens: list[str], limit: int) -> str:
        """Build the AGE seed-match query."""
        where_clause = " OR ".join(
            [
                f"toLower(m.content) CONTAINS {self._to_cypher_string_literal(token)}"
                for token in query_tokens
            ]
            + [
                f"toLower(m.source_uri) CONTAINS {self._to_cypher_string_literal(token)}"
                for token in query_tokens
            ]
        )
        return f"""
        MATCH (:Workspace {{name: {self._to_cypher_string_literal(workspace)}}})-[:CONTAINS]->(m:MemoryItem)
        WHERE {where_clause}
        RETURN m.memory_item_id, m.content, m.source_uri, m.confidence
        LIMIT {limit}
        """

    def _build_related_graph_query(self, workspace: str, query_tokens: list[str], limit: int) -> str:
        """Build the AGE one-hop related-item query."""
        where_clause = " OR ".join(
            [
                f"toLower(seed.content) CONTAINS {self._to_cypher_string_literal(token)}"
                for token in query_tokens
            ]
            + [
                f"toLower(seed.source_uri) CONTAINS {self._to_cypher_string_literal(token)}"
                for token in query_tokens
            ]
        )
        return f"""
        MATCH (:Workspace {{name: {self._to_cypher_string_literal(workspace)}}})-[:CONTAINS]->(seed:MemoryItem)-[:FROM_SOURCE]->(source:Source)<-[:FROM_SOURCE]-(related:MemoryItem)
        WHERE ({where_clause}) AND related.memory_item_id <> seed.memory_item_id
        RETURN related.memory_item_id, related.content, related.source_uri, related.confidence
        LIMIT {limit}
        """

    def _memory_candidate_from_age_row(self, row: tuple[Any, ...], rank: int) -> MemoryCandidate:
        """Convert one AGE row into a memory candidate."""
        return MemoryCandidate(
            memory_item_id=str(self._parse_age_scalar(row[0])),
            content=str(self._parse_age_scalar(row[1])),
            source_uri=str(self._parse_age_scalar(row[2])),
            confidence=float(self._parse_age_scalar(row[3])),
            rank=rank,
            lane="graph",
        )

    @staticmethod
    def _parse_age_scalar(value: Any) -> Any:
        """Parse a scalar AGE value into a Python primitive."""
        if value is None:
            return ""
        if not isinstance(value, str):
            return value
        
        # Strip AGE-specific type annotation if present
        cleaned = value.removesuffix("::agtype")
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Handle potential double-quoting or raw strings from AGE
            return cleaned.strip('"')

    @staticmethod
    def _tokenize_graph_query(query: str) -> list[str]:
        """Tokenize a graph query into lower-cased seed terms."""
        return [
            token
            for token in query.lower().replace("\n", " ").split(" ")
            if len(token) >= MINIMUM_GRAPH_TOKEN_LENGTH
        ]

    @staticmethod
    def _generate_identifier() -> str:
        """Generate one stable identifier."""
        return str(uuid.uuid4())

    @staticmethod
    def _utc_now_isoformat() -> str:
        """Return the current UTC timestamp as ISO-8601 text."""
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _format_vector_literal(embedding: list[float]) -> str:
        """Convert an embedding to a Postgres vector literal.
        
        Args:
            embedding: List of float values representing the embedding
            
        Returns:
            A Postgres-compatible vector literal string like '[0.1, 0.2, 0.3]'
        """
        return "[" + ",".join(str(value) for value in embedding) + "]"

    @staticmethod
    def _compute_feedback_confidence(memory_item: MemoryItemRecord) -> float:
        """Compute the confidence score stored with a memory item.
        
        Uses a simple linear scale: base 0.5, +0.1 per helpful, -0.1 per unhelpful,
        clamped to [0.1, 1.0].
        
        Args:
            memory_item: The memory item record with feedback counts
            
        Returns:
            Confidence score between 0.1 and 1.0
        """
        helpful_delta = memory_item.helpful_count - memory_item.unhelpful_count
        return max(0.1, min(1.0, 0.5 + 0.1 * helpful_delta))

    @staticmethod
    def _tokenize_local_text(text: str) -> list[str]:
        """Tokenize text for local fallback search.
        
        Simple whitespace tokenization used only when Postgres BM25 is unavailable.
        
        Args:
            text: Text to tokenize
            
        Returns:
            List of lowercased tokens
        """
        return [token for token in text.lower().replace("\n", " ").split(" ") if token]

    def _score_local_memory_item(self, memory_item: MemoryItemRecord, query: str, lane: str) -> float:
        """Score one memory item in local fallback mode."""
        query_tokens = self._tokenize_local_text(query)
        content_tokens = self._tokenize_local_text(memory_item.content)
        if not query_tokens or not content_tokens:
            return 0.0
        query_set = set(query_tokens)
        content_set = set(content_tokens)
        overlap = len(query_set & content_set)
        exact_match_bonus = 1.0 if query.strip().lower() in memory_item.content.lower() else 0.0
        confidence_bonus = self._compute_feedback_confidence(memory_item)
        if lane == "lexical":
            return overlap + exact_match_bonus + confidence_bonus
        if lane == "graph":
            return overlap + confidence_bonus
        union = len(query_set | content_set)
        jaccard = overlap / union if union else 0.0
        return jaccard + exact_match_bonus + confidence_bonus

    @staticmethod
    def _to_cypher_string_literal(value: str) -> str:
        """Convert a Python string to a safe Cypher string literal.
        
        This implements comprehensive escaping for Cypher string literals following
        the Neo4j/AGE specification. This is a defense-in-depth measure, but
        parameterized queries should be preferred when available.
        
        Args:
            value: The string to escape
            
        Returns:
            A Cypher string literal including surrounding quotes
            
        Security Note:
            While this function attempts comprehensive escaping, it's recommended
            to validate inputs at the application layer and keep queries simple.
        """
        # Escape backslashes first (must be first to avoid double-escaping)
        escaped_value = value.replace("\\", "\\\\")
        # Escape single quotes (Cypher uses single quotes for strings)
        escaped_value = escaped_value.replace("'", "\\'")
        # Escape double quotes for safety
        escaped_value = escaped_value.replace('"', '\\"')
        # Escape newlines and carriage returns
        escaped_value = escaped_value.replace("\n", "\\n")
        escaped_value = escaped_value.replace("\r", "\\r")
        # Escape tabs
        escaped_value = escaped_value.replace("\t", "\\t")
        # Escape other control characters
        escaped_value = escaped_value.replace("\b", "\\b")
        escaped_value = escaped_value.replace("\f", "\\f")
        
        return f"'{escaped_value}'"
