"""Retrieval helpers for the hermes-memory provider.

## Purpose
Provide deterministic reciprocal-rank fusion and context formatting for the
provider's lexical and vector retrieval lanes.
"""

from __future__ import annotations

from typing import Sequence

try:
    from pydantic import BaseModel, Field
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default


DEFAULT_CHARACTERS_PER_TOKEN = 4


class MemoryCandidate(BaseModel):
    """One ranked retrieval candidate with validation."""

    memory_item_id: str = Field(..., min_length=1, description="Unique memory item ID")
    content: str = Field(..., min_length=1, description="Memory content")
    source_uri: str = Field(..., min_length=1, description="Source URI")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    rank: int = Field(..., ge=1, description="Rank position (1-indexed)")
    lane: str = Field(..., description="Retrieval lane (lexical/vector/graph)")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


class FusedCandidate(BaseModel):
    """One fused retrieval result with validation."""

    memory_item_id: str = Field(..., min_length=1, description="Unique memory item ID")
    content: str = Field(..., min_length=1, description="Memory content")
    source_uri: str = Field(..., min_length=1, description="Source URI")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score")
    fused_score: float = Field(..., ge=0.0, description="Fused ranking score")

    class Config:
        """Pydantic config."""
        frozen = True  # Immutable after creation


def fuse_ranked_candidates(
    lexical_candidates: Sequence[MemoryCandidate],
    vector_candidates: Sequence[MemoryCandidate],
    rrf_k: int,
    weights: Sequence[float] | None = None,
) -> list[FusedCandidate]:
    """Fuse lexical and vector candidates using reciprocal-rank fusion."""
    return fuse_candidate_groups(
        candidate_groups=[lexical_candidates, vector_candidates],
        rrf_k=rrf_k,
        weights=weights,
    )


def fuse_candidate_groups(
    candidate_groups: Sequence[Sequence[MemoryCandidate]],
    rrf_k: int,
    weights: Sequence[float] | None = None,
) -> list[FusedCandidate]:
    """Fuse any number of ranked candidate groups using reciprocal-rank fusion.
    
    Args:
        candidate_groups: Lists of candidates from different retrieval lanes.
        rrf_k: The RRF constant (default 60).
        weights: Optional list of weights for each lane. If provided, must match length of candidate_groups.
    """
    if weights and len(weights) != len(candidate_groups):
        raise ValueError(f"Weights length ({len(weights)}) must match candidate_groups length ({len(candidate_groups)})")

    scores_by_id: dict[str, float] = {}
    canonical_candidates: dict[str, MemoryCandidate] = {}

    for i, group in enumerate(candidate_groups):
        weight = weights[i] if weights else 1.0
        for candidate in group:
            item_id = candidate.memory_item_id
            if item_id not in canonical_candidates:
                canonical_candidates[item_id] = candidate
            
            # Reciprocal Rank Fusion: 1 / (k + rank)
            scores_by_id[item_id] = scores_by_id.get(item_id, 0.0) + weight * (1.0 / (rrf_k + candidate.rank))

    fused_candidates = [
        FusedCandidate(
            memory_item_id=item_id,
            content=cand.content,
            source_uri=cand.source_uri,
            confidence=cand.confidence,
            fused_score=scores_by_id[item_id],
        )
        for item_id, cand in canonical_candidates.items()
    ]
    
    fused_candidates.sort(key=lambda c: c.fused_score, reverse=True)
    return fused_candidates


def format_context_block(fused_candidates: Sequence[FusedCandidate], limit: int) -> str:
    """Format a compact provider context block for Hermes prompt injection."""
    selected = fused_candidates[:limit]
    if not selected:
        return ""
    return "\n".join(f"- {c.content} [{c.source_uri}]" for c in selected)


def format_context_block_with_token_budget(
    fused_candidates: Sequence[FusedCandidate],
    limit: int,
    token_budget: int,
) -> str:
    """Format a provider context block while respecting an approximate token budget."""
    maximum_characters = max(token_budget, 1) * DEFAULT_CHARACTERS_PER_TOKEN
    selected_lines: list[str] = []
    current_length = 0

    for candidate in fused_candidates[:limit]:
        line = f"- {candidate.content} [{candidate.source_uri}]"
        # Account for newline if not first line
        line_length = len(line) + (1 if selected_lines else 0)
        
        if selected_lines and (current_length + line_length) > maximum_characters:
            break
            
        selected_lines.append(line)
        current_length += line_length

    return "\n".join(selected_lines)
