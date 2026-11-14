"""Bronze -> silver: parse a supplier reply into structured quote fields.

Primary path: SQL `ai_query` on the serving endpoint through the warehouse (JSON response format).
Fallback (ai_query unavailable, failing or slower than AI_QUERY_TIMEOUT_S): the direct LLM client with the same schema.
The path that ran is returned and stored with the quote.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as Timeout
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from backend.config import settings
from backend.dbx import sql
from backend.llm.client import EXTRACT_RULES, llm
from backend.tracing import traced

log = logging.getLogger("crumbly.pipeline")
M = TypeVar("M", bound=BaseModel)
_pool = ThreadPoolExecutor(max_workers=2)


def _ai_query(schema: type[M], text: str) -> M:
    """Run ai_query in the warehouse and validate its JSON against the schema."""
    fmt = json.dumps({"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}})
    rows = sql.query(
        "SELECT ai_query(:endpoint, :prompt, responseFormat => :fmt) AS out",
        {"endpoint": settings.llm_endpoint, "prompt": f"{EXTRACT_RULES}\n\nEmail:\n{text}", "fmt": fmt},
    )
    return schema.model_validate_json(rows[0]["out"])


@traced("pipeline.parse", span_type="PARSER")
def parse(schema: type[M], text: str, context: str = "") -> tuple[M | None, str]:
    """Return (parsed model or None, 'ai_query' | 'llm_client')."""
    if settings.warehouse_mode == "databricks" and settings.ai_query_enabled:
        try:
            return _pool.submit(_ai_query, schema, text).result(timeout=settings.ai_query_timeout_s), "ai_query"
        except (Timeout, ValidationError, Exception) as e:  # noqa: B014 - any failure falls back
            log.warning("ai_query path failed (%s); using the LLM client", type(e).__name__)
    return llm.extract(schema, text, context), "llm_client"
