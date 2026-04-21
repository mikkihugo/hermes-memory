# Review: Hermes BasicProvider Scaffold

## Executive Summary
The provided `BasicProvider` scaffold is a minimal interface implementation that lacks the necessary logic to function as a "smart" memory system within the Hermes ecosystem. While it satisfies the basic class structure, it provides no actual persistence, retrieval, or intelligence.

To evolve into a "smart" system, the provider must implement hybrid retrieval, proactive prefetching, and automated memory management.

---

## Missing Components for a "Smart" System

### 1. Hybrid Multi-Modal Retrieval
A "smart" system doesn't rely on a single search method. The current scaffold lacks:
*   **Lexical Search (BM25):** For exact keyword matching (e.g., error codes, specific filenames).
*   **Vector Search (Dense Embeddings):** For semantic similarity and conceptual recall.
*   **Graph Retrieval:** For understanding relationships between entities and episodes.
*   **Reciprocal Rank Fusion (RRF):** The logic to merge results from these different lanes into a single, high-confidence list.

### 2. Post-Retrieval Refinement (Reranking)
Retrieval often returns "relevant-looking" but unhelpful items. A smart provider should implement:
*   **Cross-Encoder Reranking:** A secondary pass using a more expensive model (like a Qwen3 Reranker) to score the top-N candidates against the query more accurately.

### 3. Proactivity & Latency Management
"Smart" implies being ready before the user asks.
*   **Background Prefetching:** The `queue_prefetch` method is missing. It should run retrieval in a background thread as soon as the user finishes their message, so context is ready when the model starts generating.
*   **Token Budgeting:** The `prefetch` method should not just return text; it needs to respect `token_budget` limits to avoid bloating the model's context window.

### 4. Intelligent Ingestion & Summarization
Simply saving every turn is "dumb" storage. Smart storage includes:
*   **Session Summarization:** Implementing `on_session_end` to extract key facts and store them as a compact, durable summary.
*   **Pre-compression Hook:** Implementing `on_pre_compress` to ensure vital session facts are preserved before Hermes trims the context.
*   **Automated Fact Extraction:** Logic to distinguish between "chitchat" and "durable knowledge" during `sync_turn`.

### 5. Integration & Feedback Loops
To be fully integrated into Hermes, the provider needs:
*   **Tool Schemas:** Defining `get_tool_schemas` so the model can explicitly call `search`, `store`, or `feedback` tools.
*   **System Prompt Blocks:** Providing instructions to the LLM on how and when to use this specific memory provider.
*   **Feedback Mechanism:** Handling `hermes_memory_feedback` tool calls to learn which memories are actually helpful to the user, allowing for future ranking adjustments.

### 6. Observability
*   **Metrics Collection:** Tracking retrieval latency, cache hits/misses, and success rates for different retrieval operations.

---

## Architectural Recommendations

1.  **Integrate a Vector Database:** Move beyond placeholders to a real backend (e.g., PostgreSQL with VectorChord or PGVector).
2.  **Implement RRF:** Use the `retrieval.py` patterns to fuse Lexical and Vector results.
3.  **Add Background Threading:** Implement a robust `queue_prefetch` with locking to handle concurrent retrieval.
4.  **Define Tooling:** Expose at least a `search` and `context` tool to the LLM to allow for manual recall.
