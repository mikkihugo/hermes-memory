---
name: hermes-plugin-reviewer
description: Review and optimize Hermes Agent plugins (specifically MemoryProviders). Use this skill whenever a user mentions Hermes plugins, MemoryProvider implementations, or wants a code review for files like provider.py, storage.py, or retrieval.py within the Hermes ecosystem.
---

# Hermes Plugin System Reviewer

This skill specializes in reviewing, auditing, and optimizing plugins for the Hermes Agent system. It focuses on ensuring high-performance, resilient, and "smart" memory retrieval.

## Core Review Pillars

### 1. Interface Compliance
Ensure the plugin correctly implements the `MemoryProvider` abstract base class and required lifecycle methods:
- `initialize(session_id, **kwargs)`: Robust setup of storage and config.
- `prefetch(query, *, session_id)`: Non-blocking background prefetching.
- `sync_turn(user_content, assistant_content, *, session_id)`: Reliable turn persistence.
- `handle_tool_call(tool_name, tool_args)`: Clean dispatch map for semantic tools.

### 2. Retrieval Intelligence (Smart Patterns)
Check for advanced search and ranking techniques:
- **Hybrid Search**: Concurrent Lexical (BM25) and Vector retrieval.
- **Weighted RRF**: Reciprocal Rank Fusion with configurable lane weights.
- **Graph Expansion**: Relationship-based retrieval (e.g., Apache AGE).
- **Temporal Bias**: Prioritizing recent information.

### 3. System Resilience & Robustness
Audit the "fail-safe" mechanisms:
- **Sparse Refill**: If the embedding service is down, does the plugin automatically expand its lexical (sparse) search to fill the context window?
- **Optional Dependencies**: Can the plugin fall back to local storage (e.g., JSON/SQLite) if the primary DB (PostgreSQL) is unavailable?
- **Error Handling**: Graceful degradation and clear logging.

### 4. User Experience & Agent Integration
- **Magic Words**: Does the `system_prompt_block` explicitly instruct the agent on phrases like "Remember when..." to trigger search tools?
- **Prefix Caching**: Is the system prompt block static and optimized for KV caching?

## Output Format
ALWAYS provide a structured report with the following sections:

# Hermes Plugin Review: [Plugin Name]

## Executive Summary
[High-level grade and critical findings]

## Detailed Audit
### Interface Compliance
- [ ] [Status] - [Details]

### Retrieval Intelligence
- [ ] [Status] - [Details]

### System Resilience
- [ ] [Status] - [Details]

### Agent Integration
- [ ] [Status] - [Details]

## Technical Recommendations
1. **[Critical/Major]**: [Specific code change suggestion]
2. **[Optimization]**: [Refactoring advice]

## Final Score: X/10
