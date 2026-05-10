#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_REASONING_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"
VALID_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
BANNED_SYNTHESIS_MODELS = {"gpt-4.1-mini"}


def normalize_reasoning_effort(value: Any) -> str:
    effort = str(value or DEFAULT_REASONING_EFFORT).strip().lower()
    if effort not in VALID_REASONING_EFFORTS:
        raise ValueError(f"reasoning_effort must be one of {sorted(VALID_REASONING_EFFORTS)}.")
    return effort


def ensure_allowed_synthesis_model(model: str, *, field: str) -> str:
    cleaned = str(model or DEFAULT_REASONING_MODEL).strip()
    if not cleaned:
        raise ValueError(f"{field} is required.")
    if cleaned.lower() in BANNED_SYNTHESIS_MODELS:
        raise ValueError(f"{field} must not use {cleaned}; use {DEFAULT_REASONING_MODEL} with {DEFAULT_REASONING_EFFORT} reasoning.")
    return cleaned


def build_json_response_payload(
    *,
    model: str,
    instructions: str,
    user_content: str,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    return {
        "model": ensure_allowed_synthesis_model(model, field="model"),
        "input": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": user_content},
        ],
        "reasoning": {"effort": normalize_reasoning_effort(reasoning_effort)},
        "text": {"format": {"type": "json_object"}},
        "store": False,
    }


def extract_output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str) and response["output_text"].strip():
        return str(response["output_text"])
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(str(content["text"]))
    if parts:
        return "\n".join(parts)
    if response.get("error"):
        raise ValueError(f"OpenAI Responses API returned an error: {response['error']}")
    if response.get("status") == "incomplete":
        raise ValueError(f"OpenAI Responses API returned incomplete output: {response.get('incomplete_details')}")
    raise ValueError("OpenAI Responses API output did not include text.")


def parse_json_response(response: dict[str, Any]) -> dict[str, Any]:
    text = extract_output_text(response).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    return parsed if isinstance(parsed, dict) else {}
