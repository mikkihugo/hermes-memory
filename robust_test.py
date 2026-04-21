
import os
import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from provider import HermesMemoryProvider
from retrieval import MemoryCandidate

def setup_test_home():
    hermes_home = Path("/tmp/hermes_robust_test")
    if hermes_home.exists():
        shutil.rmtree(hermes_home)
    hermes_home.mkdir(parents=True)
    return hermes_home

def robust_fallback_test():
    print("Starting hermes_memory robust fallback test...")
    hermes_home = setup_test_home()
    dsn = f"file://{hermes_home}/memory-store.json"
    
    config_path = hermes_home / "hermes-memory.json"
    config = {"dsn": dsn, "vector_enabled": True, "lexical_enabled": True}
    config_path.write_text(json.dumps(config))
    
    provider = HermesMemoryProvider()
    provider.initialize(session_id="robust-session", hermes_home=str(hermes_home))
    
    # Mock storage
    provider._storage = MagicMock()
    # Vector search RAISES an exception (simulating API down)
    provider._storage.search_vector.side_effect = Exception("Embedding API Down")
    # Lexical search should be called twice (once for initial, once for refill)
    provider._storage.search_lexical.return_value = [MemoryCandidate("item-1", "...", "...", 1.0, 1, "lexical")]
    provider._storage.search_graph.return_value = []
    
    print("Calling _search_and_fuse (simulating vector failure)...")
    provider._search_and_fuse("query", limit=5)
    
    # Verify search_lexical was called with the REFILL limit (limit * 2 = 10)
    # The last call should have limit=10
    last_call_args = provider._storage.search_lexical.call_args_list[-1]
    limit_used = last_call_args.kwargs.get('limit')
    print(f"Lexical refill limit used: {limit_used}")
    
    if limit_used == 10:
        print("SUCCESS: Sparse refill logic triggered with expanded limit.")
    else:
        print(f"FAILURE: Expected limit 10, got {limit_used}")
        exit(1)

if __name__ == "__main__":
    robust_fallback_test()
