#execution - how prompts are sent to the LLM 
from __future__ import annotations
import os
import json
import re
import logging
from typing import Any, Dict, Optional
from openai import OpenAI
import streamlit as st

# Basic logger for server-side diagnostics
logger = logging.getLogger(__name__)

# ---- secrets helper -------------------------------------------------
def get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


# Sensible defaults, overridable via env/secrets
DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-72B-Instruct"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 8192


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

    raise RuntimeError("The language model did not return valid JSON.")


#-------chat
def chat_json(
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> Dict[str, Any]:
    client = get_client()
    model_name = model or get_setting("LLM_MODEL", DEFAULT_LLM_MODEL)

    try:
        # Try with response_format first
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        # Some providers don't support response_format or may error differently
        logger.warning("LLM call without response_format due to error: %s", e)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    content = resp.choices[0].message.content or "{}"
    data = extract_json(content)

    if not isinstance(data, dict):
        raise RuntimeError("The language model response was parsed but is not a JSON object.")

    return data
