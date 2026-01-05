#execution - how prompts are sent to the LLM 
\
from __future__ import annotations
import os
import json
from typing import Any, Dict, Optional
from openai import OpenAI
import streamlit as st

# ---- secrets helper -------------------------------------------------

def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Priority:
    1. Streamlit Secrets (production)
    2. Environment variables / .env (local dev)
    """
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
    
#-------chat
def chat_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> Dict[str, Any]:

    client = get_client()
    model = model or get_setting("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")

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
        raise RuntimeError(
            f"Model did not return valid JSON.\n"
            f"Error: {e}\n\n"
            f"Raw content:\n{content}"
        )
