"""Tool schemas for the hermes-memory provider.

## Purpose
Describe the provider-specific tools Hermes exposes when this memory backend is
active.
"""

HERMES_MEMORY_SEARCH_SCHEMA = {
    "name": "hermes_memory_search",
    "description": (
        "Search durable memory using fused lexical and semantic retrieval. "
        "Use this when you need specific prior facts, incidents, documents, or "
        "config context relevant to the current task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The memory query to search for.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of fused results to return.",
            },
        },
        "required": ["query"],
    },
}

HERMES_MEMORY_CONTEXT_SCHEMA = {
    "name": "hermes_memory_context",
    "description": (
        "Return a compact, prompt-ready memory context block assembled from "
        "fused retrieval results."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The task or question that needs supporting context.",
            },
            "token_budget": {
                "type": "integer",
                "description": "Approximate token budget for the returned context.",
            },
        },
        "required": ["query"],
    },
}

HERMES_MEMORY_STORE_SCHEMA = {
    "name": "hermes_memory_store",
    "description": (
        "Store an explicit durable memory item in the Postgres memory backend. "
        "Use this for stable facts, lessons, and operational findings worth "
        "remembering beyond the current session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The durable fact or note to store.",
            },
            "source_uri": {
                "type": "string",
                "description": "Optional provenance URI for the memory item.",
            },
        },
        "required": ["content"],
    },
}

HERMES_MEMORY_FEEDBACK_SCHEMA = {
    "name": "hermes_memory_feedback",
    "description": (
        "Mark a retrieved memory as helpful or unhelpful so future ranking can "
        "improve."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "memory_item_id": {
                "type": "string",
                "description": "The retrieved memory item identifier.",
            },
            "helpful": {
                "type": "boolean",
                "description": "Whether the memory item was helpful.",
            },
        },
        "required": ["memory_item_id", "helpful"],
    },
}

HERMES_MEMORY_GRAPH_SCHEMA = {
    "name": "hermes_memory_graph",
    "description": (
        "Query AGE-backed graph memory expansion for related memory items. "
        "Use this when you need relationship-aware recall around shared "
        "sources, workspaces, or graph-linked incidents."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The seed query used to locate graph-connected memory.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of graph-expanded results to return.",
            },
        },
        "required": ["query"],
    },
}

HERMES_MEMORY_METRICS_SCHEMA = {
    "name": "hermes_memory_metrics",
    "description": (
        "Return provider-local metrics including operation counts, failures, "
        "and average latency."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

ALL_TOOL_SCHEMAS = [
    HERMES_MEMORY_SEARCH_SCHEMA,
    HERMES_MEMORY_CONTEXT_SCHEMA,
    HERMES_MEMORY_STORE_SCHEMA,
    HERMES_MEMORY_FEEDBACK_SCHEMA,
    HERMES_MEMORY_GRAPH_SCHEMA,
    HERMES_MEMORY_METRICS_SCHEMA,
]
