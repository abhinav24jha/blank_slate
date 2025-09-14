#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tiny client for a local Ollama server (http://127.0.0.1:11434).
"""

from __future__ import annotations
import json
import httpx

OLLAMA_URL = "http://127.0.0.1:11434"
# Reuse a single HTTP client for connection pooling/keep-alive
_CLIENT: httpx.Client | None = None


def _client(timeout: int) -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.Client(timeout=timeout)
    return _CLIENT


def warmup_model(model: str, timeout: int = 60) -> bool:
    """Warmup the model by making a simple request to load it into memory."""
    try:
        simple_schema = {"status": {"type": "string"}}
        call_json(model, "You are helpful.", "Say 'ready'", simple_schema, temperature=0.1, timeout=timeout)
        return True
    except Exception as e:
        print(f"Model warmup failed: {e}")
        return False


def call_json(model: str, system: str, prompt: str, schema: dict, temperature: float = 0.6, timeout: int = 120) -> dict:
    full = f"{prompt}\n\nReturn ONLY JSON matching this schema: {json.dumps(schema)}"
    req = {
        "model": model,
        "prompt": full,
        "options": {"temperature": temperature, "num_ctx": 4096},
        "system": system,
        "stream": False,
    }
    cli = _client(timeout)
    r = cli.post(f"{OLLAMA_URL}/api/generate", json=req)
    r.raise_for_status()
    txt = r.json().get("response", "{}")
    try:
        return json.loads(txt)
    except Exception:
        start, end = txt.find("{"), txt.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(txt[start:end+1])
            except Exception:
                pass
    return {}


