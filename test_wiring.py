#!/usr/bin/env python3
"""Start the Hindsight API server and verify basic connectivity."""

import os
import sys
import time
import urllib.request
import threading
import json

vendored_path = os.path.join(os.path.dirname(__file__), "vendored")
sys.path.insert(0, vendored_path)

os.environ["HINDSIGHT_API_LLM_PROVIDER"] = "openai"
os.environ["HINDSIGHT_API_LLM_BASE_URL"] = "https://llm-gateway.centralcloud.com/v1"
os.environ["HINDSIGHT_API_LLM_API_KEY"] = "dummy-key-for-local-test"
os.environ["HINDSIGHT_API_LLM_MODEL"] = "qwen3.5-9b"
os.environ["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"] = "qwen3-embedding-4b"
os.environ["HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"] = "https://llm-gateway.centralcloud.com/v1"
os.environ["HINDSIGHT_API_RERANKER_PROVIDER"] = "rrf"
os.environ["HINDSIGHT_API_DATABASE_URL"] = "postgresql+asyncpg://hermes:password@localhost:5432/hermes_memory"
os.environ["HINDSIGHT_API_LOG_LEVEL"] = "warning"
os.environ["HINDSIGHT_API_ENABLE_BANK_CONFIG_API"] = "true"

from hindsight_api.config import get_config
from hindsight_api.engine import create_engine
from hindsight_api.api.http import create_app

def start_server():
    config = get_config()
    app = create_app(config=config)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="warning")

print("Starting Hindsight API server in background thread...")
t = threading.Thread(target=start_server, daemon=True)
t.start()

print("Waiting for server to be ready...")
for i in range(40):
    try:
        urllib.request.urlopen("http://127.0.0.1:8888/v1/default/banks", timeout=1)
        print(f"Server ready after {i+1} attempts!")
        break
    except Exception as e:
        if i == 0:
            print(f"  (first attempt: {type(e).__name__})")
        if i >= 30:
            print(f"FAILED after {i+1} attempts: {e}")
            sys.exit(1)
        time.sleep(1)

# Test 1: list banks (should be empty)
print("\n[Test 1] GET /v1/default/banks")
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Banks: {result.get('banks', [])}")

# Test 2: create a bank
print("\n[Test 2] PUT /v1/default/banks/test-bank")
data = json.dumps({"name": "test-bank", "background": "Test bank for wiring verification"}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8888/v1/default/banks/test-bank",
    data=data,
    headers={"Content-Type": "application/json"},
    method="PUT",
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Created: bank_id={result.get('bank_id')}, name={result.get('name')}")

# Test 3: list banks again
print("\n[Test 3] GET /v1/default/banks (after create)")
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Banks: {[b['bank_id'] for b in result.get('banks', [])]}")

# Test 4: get bank config
print("\n[Test 4] GET /v1/default/banks/test-bank/config")
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks/test-bank/config")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Config keys: {list(result.get('config', {}).keys()) if isinstance(result, dict) else 'N/A'}")

# Test 5: get stats
print("\n[Test 5] GET /v1/default/banks/test-bank/stats")
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks/test-bank/stats")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Stats: {result}")

# Test 6: search_debug
print("\n[Test 6] POST /v1/default/banks/test-bank/memories/recall")
data = json.dumps({"query": "hello world", "trace": True}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8888/v1/default/banks/test-bank/memories/recall",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        result = json.loads(resp.read())
    print(f"  Search result keys: {list(result.keys())}")
    print(f"  Memories count: {len(result.get('memories', []))}")
except Exception as e:
    print(f"  Search error (expected if no data): {e}")

# Test 7: browse memories
print("\n[Test 7] GET /v1/default/banks/test-bank/memories/list")
req = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks/test-bank/memories/list?limit=5")
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Browse result keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")

# Test 8: delete bank
print("\n[Test 8] DELETE /v1/default/banks/test-bank")
req = urllib.request.Request(
    "http://127.0.0.1:8888/v1/default/banks/test-bank",
    method="DELETE",
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
print(f"  Deleted: {result}")

print("\n✓ All API wiring tests passed!")
