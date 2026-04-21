"""Tests for error handling and edge cases in hermes-memory provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG_FILENAME, HermesMemoryConfig  # noqa: E402
from provider import HermesMemoryProvider  # noqa: E402
from storage import HermesMemoryStorage, MAX_CONTENT_LENGTH, MAX_SOURCE_URI_LENGTH, MAX_WORKSPACE_LENGTH  # noqa: E402

try:
    from pydantic import ValidationError
except ImportError:
    ValidationError = ValueError  # type: ignore


def _write_provider_config(hermes_home: Path, config_dict: dict) -> None:
    """Write a provider config for tests."""
    config_path = hermes_home / CONFIG_FILENAME
    config_path.write_text(
        json.dumps(config_dict),
        encoding="utf-8",
    )


def _create_initialized_provider(hermes_home: Path, dsn: str = None) -> HermesMemoryProvider:
    """Return one initialized provider."""
    storage_path = hermes_home / "memory-store.json"
    config = {
        "context_tokens": 12,
        "dsn": dsn or f"file://{storage_path}",
        "workspace": "test-workspace",
    }
    _write_provider_config(hermes_home, config)
    provider = HermesMemoryProvider()
    provider.initialize(session_id="session-1", hermes_home=str(hermes_home))
    return provider


class TestConfigValidation:
    """Test configuration validation using Pydantic."""
    
    def test_invalid_dsn_prefix_raises_error(self, tmp_path: Path) -> None:
        """Invalid DSN prefix should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError), match="DSN must start with"):
            HermesMemoryConfig(dsn="invalid://path")
    
    def test_negative_embedding_dimensions_raises_error(self, tmp_path: Path) -> None:
        """Negative embedding dimensions should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", embedding_dimensions=-1)
    
    def test_excessive_embedding_dimensions_raises_error(self, tmp_path: Path) -> None:
        """Excessive embedding dimensions should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", embedding_dimensions=20000)
    
    def test_negative_pool_size_raises_error(self, tmp_path: Path) -> None:
        """Negative pool size should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", pool_min_size=-1)
    
    def test_invalid_pool_size_range_raises_error(self, tmp_path: Path) -> None:
        """Invalid pool size range should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", pool_min_size=5, pool_max_size=2)
    
    def test_zero_prefetch_limit_raises_error(self, tmp_path: Path) -> None:
        """Zero prefetch limit should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", prefetch_limit=0)
    
    def test_negative_rrf_k_raises_error(self, tmp_path: Path) -> None:
        """Negative RRF k should raise ValidationError."""
        with pytest.raises((ValidationError, ValueError)):
            HermesMemoryConfig(dsn="file://test", rrf_k=-1)
    
    def test_valid_config_succeeds(self, tmp_path: Path) -> None:
        """Valid config should be accepted."""
        config = HermesMemoryConfig(
            dsn="file:///tmp/test.json",
            workspace="test",
            embedding_dimensions=512,
            pool_min_size=1,
            pool_max_size=4,
        )
        assert config.dsn == "file:///tmp/test.json"
        assert config.workspace == "test"
    
    def test_unknown_fields_rejected(self, tmp_path: Path) -> None:
        """Unknown configuration fields should be rejected."""
        # Only applies when Pydantic is available
        try:
            from pydantic import ValidationError
            with pytest.raises(ValidationError):
                HermesMemoryConfig(unknown_field="value")  # type: ignore
        except ImportError:
            pytest.skip("Pydantic not available")


class TestInputValidation:
    """Test input validation for memory storage."""
    
    def test_empty_workspace_raises_error(self, tmp_path: Path) -> None:
        """Empty workspace should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        
        with pytest.raises(ValueError, match="Workspace cannot be empty"):
            provider._storage.store_memory_item(
                workspace="",
                content="test content",
                source_uri="test://uri",
            )
    
    def test_excessively_long_workspace_raises_error(self, tmp_path: Path) -> None:
        """Excessively long workspace should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        long_workspace = "x" * (MAX_WORKSPACE_LENGTH + 1)
        
        with pytest.raises(ValueError, match="Workspace exceeds maximum length"):
            provider._storage.store_memory_item(
                workspace=long_workspace,
                content="test content",
                source_uri="test://uri",
            )
    
    def test_empty_content_raises_error(self, tmp_path: Path) -> None:
        """Empty content should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        
        with pytest.raises(ValueError, match="Content cannot be empty"):
            provider._storage.store_memory_item(
                workspace="test",
                content="",
                source_uri="test://uri",
            )
    
    def test_excessively_long_content_raises_error(self, tmp_path: Path) -> None:
        """Excessively long content should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        long_content = "x" * (MAX_CONTENT_LENGTH + 1)
        
        with pytest.raises(ValueError, match="Content exceeds maximum length"):
            provider._storage.store_memory_item(
                workspace="test",
                content=long_content,
                source_uri="test://uri",
            )
    
    def test_empty_source_uri_raises_error(self, tmp_path: Path) -> None:
        """Empty source URI should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        
        with pytest.raises(ValueError, match="Source URI cannot be empty"):
            provider._storage.store_memory_item(
                workspace="test",
                content="test content",
                source_uri="",
            )
    
    def test_excessively_long_source_uri_raises_error(self, tmp_path: Path) -> None:
        """Excessively long source URI should raise ValueError."""
        provider = _create_initialized_provider(tmp_path)
        long_uri = "x" * (MAX_SOURCE_URI_LENGTH + 1)
        
        with pytest.raises(ValueError, match="Source URI exceeds maximum length"):
            provider._storage.store_memory_item(
                workspace="test",
                content="test content",
                source_uri=long_uri,
            )
    
    def test_whitespace_only_inputs_are_rejected(self, tmp_path: Path) -> None:
        """Whitespace-only inputs should be rejected."""
        provider = _create_initialized_provider(tmp_path)
        
        with pytest.raises(ValueError, match="Workspace cannot be empty"):
            provider._storage.store_memory_item(
                workspace="   ",
                content="test content",
                source_uri="test://uri",
            )


class TestEmbeddingFailureHandling:
    """Test handling of embedding service failures."""
    
    def test_embedding_failure_on_store_uses_zero_vector(self, tmp_path: Path) -> None:
        """Embedding failure during store should use zero vector and succeed."""
        provider = _create_initialized_provider(tmp_path)
        
        # Mock the embedding client to raise an exception
        with patch.object(provider._storage._embedding_client, 'embed_text') as mock_embed:
            mock_embed.side_effect = Exception("Embedding service down")
            
            # Should succeed despite embedding failure (uses zero vector)
            memory_id = provider._storage.store_memory_item(
                workspace="test",
                content="test content",
                source_uri="test://uri",
            )
            
            assert memory_id is not None
            assert len(memory_id) > 0
    
    def test_vector_search_failure_is_logged_and_raised(self, tmp_path: Path) -> None:
        """Vector search failure should be logged and raised to trigger fallback."""
        provider = _create_initialized_provider(tmp_path)
        
        # Store an item first
        provider._storage.store_memory_item(
            workspace="test",
            content="test content",
            source_uri="test://uri",
        )
        
        # Mock the embedding client to raise an exception
        with patch.object(provider._storage._embedding_client, 'embed_text') as mock_embed:
            mock_embed.side_effect = Exception("Embedding service down")
            
            # Should raise to allow provider to fall back to lexical
            with pytest.raises(Exception, match="Embedding service down"):
                provider._storage.search_vector(
                    workspace="test",
                    query="test query",
                    limit=5,
                )


class TestCypherEscaping:
    """Test Cypher string literal escaping."""
    
    def test_single_quotes_are_escaped(self, tmp_path: Path) -> None:
        """Single quotes should be escaped properly."""
        from storage import HermesMemoryStorage
        
        result = HermesMemoryStorage._to_cypher_string_literal("test'quote")
        assert result == "'test\\'quote'"
    
    def test_backslashes_are_escaped(self, tmp_path: Path) -> None:
        """Backslashes should be escaped properly."""
        from storage import HermesMemoryStorage
        
        result = HermesMemoryStorage._to_cypher_string_literal("test\\slash")
        assert result == "'test\\\\slash'"
    
    def test_newlines_are_escaped(self, tmp_path: Path) -> None:
        """Newlines should be escaped properly."""
        from storage import HermesMemoryStorage
        
        result = HermesMemoryStorage._to_cypher_string_literal("test\nline")
        assert result == "'test\\nline'"
    
    def test_complex_string_with_multiple_escapes(self, tmp_path: Path) -> None:
        """Complex strings with multiple special characters should be escaped."""
        from storage import HermesMemoryStorage
        
        result = HermesMemoryStorage._to_cypher_string_literal("test'quote\nline\\slash")
        assert result == "'test\\'quote\\nline\\\\slash'"
    
    def test_control_characters_are_escaped(self, tmp_path: Path) -> None:
        """Control characters should be escaped properly."""
        from storage import HermesMemoryStorage
        
        result = HermesMemoryStorage._to_cypher_string_literal("test\t\r\b\f")
        assert result == "'test\\t\\r\\b\\f'"


class TestToolErrorMessages:
    """Test that tool calls return helpful error messages."""
    
    def test_missing_query_parameter_returns_clear_error(self, tmp_path: Path) -> None:
        """Missing query parameter should return clear error message."""
        provider = _create_initialized_provider(tmp_path)
        
        response = json.loads(provider.handle_tool_call("hermes_memory_search", {}))
        assert "error" in response
        assert "query" in response["error"].lower()
    
    def test_missing_content_parameter_returns_clear_error(self, tmp_path: Path) -> None:
        """Missing content parameter should return clear error message."""
        provider = _create_initialized_provider(tmp_path)
        
        response = json.loads(provider.handle_tool_call("hermes_memory_store", {}))
        assert "error" in response
        assert "content" in response["error"].lower()
    
    def test_unknown_tool_returns_clear_error(self, tmp_path: Path) -> None:
        """Unknown tool should return clear error message."""
        provider = _create_initialized_provider(tmp_path)
        
        response = json.loads(provider.handle_tool_call("unknown_tool", {}))
        assert "error" in response
        assert "unknown" in response["error"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
