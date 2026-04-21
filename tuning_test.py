
import os
import json
import shutil
from pathlib import Path
from provider import HermesMemoryProvider
from retrieval import MemoryCandidate

def tuning_test():
    print("Starting hermes_memory tuning test (RRF weights)...")
    
    hermes_home = Path("/tmp/hermes_tuning_test")
    if hermes_home.exists():
        shutil.rmtree(hermes_home)
    hermes_home.mkdir(parents=True)
    
    dsn = f"file://{hermes_home}/memory-store.json"
    
    # Test case: 
    # Item A is Rank 1 in Lexical
    # Item B is Rank 1 in Vector
    # If Lexical weight is 2.0 and Vector weight is 1.0, Item A should win.
    
    config_path = hermes_home / "hermes-memory.json"
    config = {
        "dsn": dsn,
        "lexical_weight": 2.0,
        "vector_weight": 1.0,
        "vector_enabled": True,
        "lexical_enabled": True
    }
    config_path.write_text(json.dumps(config))
    
    provider = HermesMemoryProvider()
    provider.initialize(session_id="tuning-session", hermes_home=str(hermes_home))
    
    # Mock some candidates
    lexical_group = [
        MemoryCandidate("item-A", "Lexical Win", "uri-1", 1.0, 1, "lexical"),
        MemoryCandidate("item-B", "Vector Win", "uri-2", 1.0, 2, "lexical")
    ]
    vector_group = [
        MemoryCandidate("item-B", "Vector Win", "uri-2", 1.0, 1, "vector"),
        MemoryCandidate("item-A", "Lexical Win", "uri-1", 1.0, 2, "vector")
    ]
    
    # We need to call the internal _search_and_fuse but mock the storage calls
    from unittest.mock import MagicMock
    provider._storage = MagicMock()
    provider._storage.search_lexical.return_value = lexical_group
    provider._storage.search_vector.return_value = vector_group
    provider._storage.search_graph.return_value = []
    
    fused = provider._search_and_fuse("query", limit=10)
    
    print(f"Top result with Lexical weight 2.0: {fused[0].memory_item_id}")
    if fused[0].memory_item_id == "item-A":
        print("SUCCESS: Lexical weight boost worked.")
    else:
        print("FAILURE: Lexical weight boost failed.")
        exit(1)

    # Now swap weights
    config["lexical_weight"] = 1.0
    config["vector_weight"] = 2.0
    config_path.write_text(json.dumps(config))
    provider.initialize(session_id="tuning-session", hermes_home=str(hermes_home))
    
    # RE-APPLY MOCK after re-initialization
    provider._storage = MagicMock()
    provider._storage.search_lexical.return_value = lexical_group
    provider._storage.search_vector.return_value = vector_group
    provider._storage.search_graph.return_value = []
    
    fused = provider._search_and_fuse("query", limit=10)
    print(f"Top result with Vector weight 2.0: {fused[0].memory_item_id}")
    if fused[0].memory_item_id == "item-B":
        print("SUCCESS: Vector weight boost worked.")
    else:
        print("FAILURE: Vector weight boost failed.")
        exit(1)

    print("Tuning test PASSED.")

if __name__ == "__main__":
    tuning_test()
