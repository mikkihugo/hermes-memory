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

# ── Admin tool schemas ─────────────────────────────────────────────────────────

HERMES_MEMORY_BANK_CREATE_SCHEMA = {
    "name": "memory_bank_create",
    "description": "Create a new memory bank with the given name and optional background context.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique name for the new memory bank.",
            },
            "background": {
                "type": "string",
                "description": "Optional background context or mission statement for the bank.",
            },
        },
        "required": ["name"],
    },
}

HERMES_MEMORY_BANK_DELETE_SCHEMA = {
    "name": "memory_bank_delete",
    "description": "Delete a memory bank and all its stored memories.",
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank to delete.",
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_BANK_LIST_SCHEMA = {
    "name": "memory_bank_list",
    "description": "List all memory banks and their profiles.",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

HERMES_MEMORY_BANK_CONFIG_GET_SCHEMA = {
    "name": "memory_bank_config_get",
    "description": "Get the full resolved configuration for a memory bank.",
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_BANK_CONFIG_SET_SCHEMA = {
    "name": "memory_bank_config_set",
    "description": (
        "Update bank configuration overrides such as mission, disposition traits, "
        "retention settings, and processing options."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
            "disposition_skepticism": {
                "type": "integer",
                "description": "Disposition skepticism value (0-100).",
            },
            "disposition_literalism": {
                "type": "integer",
                "description": "Disposition literalism value (0-100).",
            },
            "disposition_empathy": {
                "type": "integer",
                "description": "Disposition empathy value (0-100).",
            },
            "retain_mission": {
                "type": "string",
                "description": "Mission statement steering what gets extracted during retain.",
            },
            "retain_extraction_mode": {
                "type": "string",
                "description": "Fact extraction mode: 'concise', 'verbose', or 'custom'.",
            },
            "reflect_mission": {
                "type": "string",
                "description": "Mission or context for Reflect operations.",
            },
            "enable_observations": {
                "type": "boolean",
                "description": "Toggle automatic observation consolidation after retain.",
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_STATS_SCHEMA = {
    "name": "memory_stats",
    "description": "Get statistics about nodes, links, and operations for a memory bank.",
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_BROWSE_SCHEMA = {
    "name": "memory_browse",
    "description": (
        "Browse memory items in a bank with pagination and optional fact-type filter. "
        "Results are sorted by most recent first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return (default 20).",
                "default": 20,
            },
            "offset": {
                "type": "integer",
                "description": "Offset for pagination (default 0).",
                "default": 0,
            },
            "fact_type": {
                "type": "string",
                "description": "Optional fact type filter: 'world', 'experience', or 'observation'.",
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_SEARCH_DEBUG_SCHEMA = {
    "name": "memory_search_debug",
    "description": (
        "Search memories with a full retrieval trace showing all methods and scores. "
        "Useful for debugging recall quality."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "show_trace": {
                "type": "boolean",
                "description": "Whether to include the full retrieval trace in the response.",
                "default": False,
            },
        },
        "required": ["bank_id", "query"],
    },
}

HERMES_MEMORY_ENTITIES_SCHEMA = {
    "name": "memory_entities",
    "description": "Get the entity graph for a memory bank.",
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of entities to return (default 50).",
                "default": 50,
            },
        },
        "required": ["bank_id"],
    },
}

HERMES_MEMORY_AUDIT_SCHEMA = {
    "name": "memory_audit",
    "description": "Get the audit log for a memory bank, showing recent operations.",
    "parameters": {
        "type": "object",
        "properties": {
            "bank_id": {
                "type": "string",
                "description": "The identifier of the bank.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of log entries to return (default 50).",
                "default": 50,
            },
        },
        "required": ["bank_id"],
    },
}

ALL_TOOL_SCHEMAS = [
    HERMES_MEMORY_SEARCH_SCHEMA,
    HERMES_MEMORY_CONTEXT_SCHEMA,
    HERMES_MEMORY_STORE_SCHEMA,
    HERMES_MEMORY_FEEDBACK_SCHEMA,
    HERMES_MEMORY_GRAPH_SCHEMA,
    HERMES_MEMORY_METRICS_SCHEMA,
    HERMES_MEMORY_BANK_CREATE_SCHEMA,
    HERMES_MEMORY_BANK_DELETE_SCHEMA,
    HERMES_MEMORY_BANK_LIST_SCHEMA,
    HERMES_MEMORY_BANK_CONFIG_GET_SCHEMA,
    HERMES_MEMORY_BANK_CONFIG_SET_SCHEMA,
    HERMES_MEMORY_STATS_SCHEMA,
    HERMES_MEMORY_BROWSE_SCHEMA,
    HERMES_MEMORY_SEARCH_DEBUG_SCHEMA,
    HERMES_MEMORY_ENTITIES_SCHEMA,
    HERMES_MEMORY_AUDIT_SCHEMA,
]
