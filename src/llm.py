#execution - how prompts are sent to the LLM 
from __future__ import annotations
import os
import json
import re
from typing import Any, Dict, Optional
from openai import OpenAI
import streamlit as st

# ---- secrets helper -------------------------------------------------
def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)

#--------client 
def get_client() -> OpenAI:
    api_key = get_setting("LLM_API_KEY") or get_setting("OPENAI_API_KEY")
    base_url = get_setting("LLM_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError(
            "Missing LLM_API_KEY (or OPENAI_API_KEY). "
            "Add it to Streamlit Secrets or your local .env file."
        )
    return OpenAI(api_key=api_key, base_url=base_url)

#-------extract JSON from response that might have extra text
def extract_json(text: str) -> dict:
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON in markdown code blocks
    code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON object in text
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    
    raise RuntimeError(f"Could not extract valid JSON from response:\n{text}")

#-------chat
def chat_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> Dict[str, Any]:
    client = get_client()
    model = model or get_setting("LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    
    # Try with response_format first, fall back without it
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception:
        # Some providers don't support response_format
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    content = resp.choices[0].message.content or "{}"
    
    return extract_json(content)
