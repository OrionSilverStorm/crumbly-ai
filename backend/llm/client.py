"""Swappable LLM client (Databricks serving endpoint, any OpenAI-compatible API, or a test stub).

Outputs are always validated against a Pydantic schema: on failure we retry once, then return None so the caller
treats every field as missing (which triggers a follow-up). We never guess.
"""
import json
import logging
import re
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.config import settings
from backend.tracing import traced

log = logging.getLogger("crumbly.llm")
M = TypeVar("M", bound=BaseModel)
EXTRACT_RULES = (
    "Extract only facts stated in the text. Use null for anything not explicitly stated; never infer or guess "
    "numbers. Reply with a single JSON object matching the schema."
)


@lru_cache
def _openai():
    """OpenAI-compatible client for the configured provider."""
    if settings.llm_provider == "databricks":
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient().serving_endpoints.get_open_ai_client()  # auth from the SDK (PAT or app identity)
    from openai import OpenAI

    return OpenAI(base_url=settings.openai_base_url or None, api_key=settings.openai_api_key)


def _json_text(text: str) -> str:
    """Strip markdown fences some models wrap JSON in."""
    m = re.search(r"\{.*\}", text or "", re.S)
    return m.group(0) if m else (text or "")


class LLM:
    """Provider-agnostic facade used by agents, the pipeline fallback and the assistant."""

    def complete(self, messages: list[dict], schema: type[BaseModel] | None = None, tools: list | None = None) -> dict:
        """One chat completion. Returns {'content': str, 'tool_calls': [{'id','name','arguments'}]}."""
        if settings.llm_provider == "stub":
            from backend.llm.stub import stub_complete

            return stub_complete(messages, schema, tools)
        kwargs = {"model": settings.llm_endpoint, "messages": messages, "temperature": 0}
        if schema:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        if tools:
            kwargs["tools"] = tools
        msg = _openai().chat.completions.create(**kwargs).choices[0].message
        calls = [{"id": c.id, "name": c.function.name, "arguments": c.function.arguments} for c in (msg.tool_calls or [])]
        return {"content": msg.content or "", "tool_calls": calls}

    @traced("llm.extract", span_type="LLM")
    def extract(self, schema: type[M], text: str, context: str = "") -> M | None:
        """Extract `schema` from `text`. Validate, retry once with the error, else None (caller marks fields missing)."""
        messages = [
            {"role": "system", "content": f"{EXTRACT_RULES}\n{context}\nJSON schema:\n{json.dumps(schema.model_json_schema())}"},
            {"role": "user", "content": text},
        ]
        for attempt in range(2):
            raw = self.complete(messages, schema=schema)["content"]
            try:
                return schema.model_validate_json(_json_text(raw))
            except (ValidationError, ValueError) as e:
                log.warning("LLM output failed validation (attempt %d): %s", attempt + 1, e)
                messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": f"Invalid: {e}. Return corrected JSON only."}]
        return None


# Shared instance.
llm = LLM()
