
import os
import json
import shutil
from pathlib import Path
from provider import HermesMemoryProvider

def smoke_test():
    print("Starting hermes_memory smoke test...")
    
    # Setup temp home
    hermes_home = Path("/tmp/hermes_test_home")
    if hermes_home.exists():
        shutil.rmtree(hermes_home)
    hermes_home.mkdir(parents=True)
    
    dsn = f"file://{hermes_home}/memory-store.json"
    
    # Create a dummy config
    config_path = hermes_home / "hermes-memory.json"
    config = {
        "dsn": dsn,
        "workspace": "test-space",
        "lexical_enabled": True,
        "vector_enabled": False, # Disable vector to avoid API calls in smoke test
        "graph_enabled": False,
        "bootstrap_schema": True
    }
    config_path.write_text(json.dumps(config))
    
    provider = HermesMemoryProvider()
    print(f"Provider name: {provider.name}")
    
    # Initialize
    print("Initializing provider...")
    provider.initialize(session_id="test-session", hermes_home=str(hermes_home))
    
    # Test Tool call: store
    print("Testing hermes_memory_store...")
    provider.handle_tool_call(
        "hermes_memory_store", 
        {"content": "The secret code is 12345", "source_uri": "test://secret"}
    )
    
    # Test Tool call: search (Lexical)
    print("Testing hermes_memory_search (Lexical)...")
    search_result = provider.handle_tool_call(
        "hermes_memory_search",
        {"query": "secret code"}
    )
    print(f"Search Result: {search_result}")
    
    if "12345" in search_result:
        print("SUCCESS: Found stored item in lexical search.")
    else:
        print("FAILURE: Could not find stored item.")
        exit(1)
        
    # Test sync_turn
    print("Testing sync_turn...")
    provider.sync_turn(
        user_content="What is the code?", 
        assistant_content="The code is 12345.", 
        session_id="test-session"
    )
    
    # Verify file content
    store_file = hermes_home / "memory-store.json"
    if store_file.exists():
        data = json.loads(store_file.read_text())
        print(f"Stored items count: {len(data['memory_items'])}")
        print(f"Stored turns count: {len(data['turns'])}")
    else:
        print("FAILURE: memory-store.json was not created.")
        exit(1)

    print("Smoke test PASSED.")

if __name__ == "__main__":
    try:
        smoke_test()
    except Exception as e:
        print(f"SMOKE TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
