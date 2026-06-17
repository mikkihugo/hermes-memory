#!/usr/bin/env python3
"""Minimal test to start the Hindsight API and verify it responds."""

import os
import sys
from pathlib import Path

# Add vendored path
vendored_path = Path(__file__).parent / "vendored"
sys.path.insert(0, str(vendored_path))

# Set required env vars
os.environ["HINDSIGHT_API_DATABASE_URL"] = "postgresql://hermes:password@localhost:5432/hermes_memory"
os.environ["HINDSIGHT_API_LLM_PROVIDER"] = "openai"
os.environ["HINDSIGHT_API_LLM_BASE_URL"] = "https://llm-gateway.centralcloud.com/v1"
os.environ["HINDSIGHT_API_LLM_API_KEY"] = "dummy-key-for-local-test"
os.environ["HINDSIGHT_API_LLM_MODEL"] = "qwen3.5-9b"
os.environ["HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"] = "https://llm-gateway.centralcloud.com/v1"
os.environ["HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL"] = "qwen3-embedding-4b"
os.environ["HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY"] = ""
os.environ["HINDSIGHT_API_RERANKER_PROVIDER"] = "rrf"
os.environ["HINDSIGHT_API_RERANKER_OPENAI_BASE_URL"] = "https://llm-gateway.centralcloud.com/v1"
os.environ["HINDSIGHT_API_RERANKER_OPENAI_API_KEY"] = ""
os.environ["HINDSIGHT_API_RERANKER_OPENAI_MODEL"] = ""
os.environ["HINDSIGHT_API_VECTOR_EXTENSION"] = "vchord"
os.environ["HINDSIGHT_API_TEXT_SEARCH_EXTENSION"] = "vchord"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import threading
import time
import urllib.request
import uvicorn

print("Importing MemoryEngine...")
from hindsight_api import MemoryEngine
from hindsight_api.api import create_app

print("Creating MemoryEngine (run_migrations=False for test)...")
try:
    engine = MemoryEngine(run_migrations=False)
    print("MemoryEngine created OK")
except Exception as e:
    print(f"MemoryEngine init error: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

print("Creating FastAPI app...")
try:
    app = create_app(memory=engine, http_api_enabled=True, mcp_api_enabled=False, initialize_memory=False)
    print("App created OK")
except Exception as e:
    print(f"create_app error: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8888, log_level="info")

server_thread = threading.Thread(target=run_server, daemon=True, name="hindsight-api")
server_thread.start()
print("Server thread started, waiting for it to be ready...")

for i in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1:8888/health", timeout=1)
        print(f"Server ready after {i+1} attempts!")
        break
    except Exception as e:
        if i == 29:
            print(f"Server failed to start: {e}")
            sys.exit(1)
        time.sleep(1)

# Quick HTTP sanity check - health endpoint
req = urllib.request.Request("http://127.0.0.1:8888/health")
with urllib.request.urlopen(req, timeout=5) as resp:
    print(f"/health status: {resp.status}")

# Check banks endpoint
req2 = urllib.request.Request("http://127.0.0.1:8888/v1/default/banks")
with urllib.request.urlopen(req2, timeout=5) as resp:
    print(f"/v1/default/banks status: {resp.status}")
    body = resp.read().decode()
    print(f"/v1/default/banks body: {body[:500]}")

print("\n✅ Hindsight API server started and responding!")
