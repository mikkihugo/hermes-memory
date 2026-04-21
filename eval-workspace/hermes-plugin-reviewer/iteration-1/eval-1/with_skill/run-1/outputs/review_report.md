# Hermes Plugin Review: BasicProvider

## Executive Summary
**Grade: 2/10 (Critical Missing Logic)**
The `BasicProvider` is a bare scaffold that implements the required method signatures but contains zero operational logic. It is entirely non-functional for any real-world "smart" memory retrieval task. It lacks the core intelligence components (Hybrid Search, RRF) and resilience patterns required for a production-grade Hermes plugin.

## Detailed Audit
### Interface Compliance
- [x] **Partial** - Implements the base `MemoryProvider` methods (`initialize`, `prefetch`, `sync_turn`, `handle_tool_call`).
- [ ] **Incomplete** - Signatures do not fully match the recommended `MemoryProvider` spec (e.g., missing keyword-only arguments in `prefetch` and `sync_turn`).
- [ ] **Incomplete** - Methods are no-ops (`pass`) or return static values, providing no actual functionality.

### Retrieval Intelligence
- [ ] **Critical Missing** - **Hybrid Search**: No implementation of concurrent Vector and Lexical retrieval.
- [ ] **Critical Missing** - **Weighted RRF**: No mechanism to merge or rank diverse search results.
- [ ] **Missing** - **Temporal Bias**: All memory is treated as equally relevant regardless of age.
- [ ] **Missing** - **Graph Expansion**: No relational context is pulled into retrieval.

### System Resilience
- [ ] **Critical Missing** - **Sparse Refill**: If a vector database or embedding service were added and failed, there is no keyword-only fallback to fill the context.
- [ ] **Missing** - **Optional Dependencies**: No fallback to local JSON/SQLite storage.
- [ ] **Missing** - **Error Handling**: Methods do not account for potential network or I/O failures.

### Agent Integration
- [ ] **Critical Missing** - **System Prompt Block**: No guidance provided to the LLM on how to use this memory provider.
- [ ] **Missing** - **Magic Words**: No instructions for "Remember when..." or similar trigger phrases.

## Technical Recommendations
1. **[Critical] Implement Hybrid Search**: Integrate a vector store (e.g., Chroma, FAISS) alongside a lexical engine (e.g., BM25). A "smart" system must be able to find both semantic matches and exact keyword matches.
2. **[Major] Add Reciprocal Rank Fusion (RRF)**: Implement an RRF lane-merging algorithm to combine vector and sparse results. This is essential for ranking "smart" results effectively.
3. **[Major] Implement Sparse Refill logic**: Ensure that if vector retrieval returns zero results (or fails), the lexical search is expanded to ensure the agent still has relevant context.
4. **[Optimization] Add `system_prompt_block`**: Define a clear instruction block for the agent. For example: "You have access to a long-term memory. If the user asks about past events, use the available tools to retrieve context."
5. **[Compliance] Correct Signatures**: Update `prefetch` and `sync_turn` to use keyword-only `session_id` to ensure compatibility with the Hermes orchestrator's expectations.

## Final Score: 2/10
