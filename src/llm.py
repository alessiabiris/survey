#execution - how prompts are sent to the LLM 
\
from __future__ import annotations
import os
import json
from typing import Any, Dict, Optional
from openai import OpenAI

def get_client() -> OpenAI:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY (or OPENAI_API_KEY). Set it in .env or environment variables.")
    return OpenAI(api_key=api_key, base_url=base_url)

def chat_json(system: str, user: str, model: Optional[str] = None, temperature: float = 0.2) -> Dict[str, Any]:
    client = get_client()
    model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")

    
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Surface a helpful error with raw content for debugging
        raise RuntimeError(f"Model did not return valid JSON. Error: {e}\n\nRaw content:\n{content}")
