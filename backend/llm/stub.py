"""Deterministic test double for the LLM (LLM_PROVIDER=stub). Regex-reads the scripted demo emails so tests and
offline runs work without a model. Real runs use the serving endpoint; this is never used to make decisions."""
import json
import re

from pydantic import BaseModel

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}
NUM = r"(\d+|" + "|".join(WORDS) + r")"
MONEY = r"£\s?(\d+(?:\.\d{1,2})?)"


def _n(s: str | None) -> int | None:
    """'7' or 'seven' -> 7."""
    return None if s is None else int(s) if s.isdigit() else WORDS.get(s.lower())


def _find(pattern: str, text: str, conv=float):
    """First capture group of a case-insensitive match, converted; None if absent."""
    m = re.search(pattern, text, re.I)
    return conv(m.group(1)) if m else None


def _time(text: str) -> str | None:
    """First HH:MM time in the text."""
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def _offer(s: str) -> dict:
    """Parse one offer sentence group."""
    included = bool(re.search(r"(including|incl\.?|delivery included)", s, re.I))
    max_packs = _find(rf"up to {NUM} bags?", s, _n)
    return {
        "label": "early van" if "early van" in s.lower() else None,
        "packs": None if max_packs else (_find(rf"\b{NUM}\s*(?:×|x)\s*25\s*kg", s, _n) or _find(rf"\b{NUM}\s+bags?", s, _n)),
        "max_packs": max_packs,
        "pack_size_kg": 25.0 if re.search(r"25\s*kg|bags?", s, re.I) else None,
        "unit_price": _find(rf"{MONEY}\s*(?:per|a|/)\s*bag", s),
        "goods_price": _find(rf"\bfor {MONEY}", s),
        "delivery_charge": 0.0 if included else (_find(rf"{MONEY}\s*delivery", s) or _find(rf"delivery[: ]+{MONEY}", s)),
        "delivery_included": True if included else None,
        "vat_rate": 0.0 if re.search(r"zero[- ]rated|no vat|vat 0", s, re.I) else None,
        "total": _find(rf"{MONEY}\s*total", s) or _find(rf"total[: ]+{MONEY}", s) or (_find(rf"\bfor {MONEY}", s) if included else None),
        "arrival_time": _time(s),
        "arrival_text": _find(r"\b(tomorrow|by \d\d:\d\d|arriving [^.,]+)", s, str),
    }


def _quote(text: str) -> dict:
    """Supplier reply: split capacity-limited 'early van' sentences into their own offer."""
    if re.search(r"\b(sorry|unable|out of stock|can't supply|cannot supply|out of)\b", text, re.I) and not re.search(MONEY, text):
        return {"declined": True, "offers": []}
    parts = re.split(r"(?<=[.!])\s+(?=Our early van)", text)
    return {"declined": False, "offers": [_offer(p) for p in parts]}


def _confirmation(text: str) -> dict:
    """Order confirmation echoing the agreed terms."""
    return {
        "po_reference": _find(r"(PO[-–\s]?\d{4})", text, str),
        "product": "strong white flour" if "strong white flour" in text.lower() else None,
        "packs": _find(rf"\b{NUM}\s*(?:×|x)\s*25\s*kg", text, _n),
        "pack_size_kg": 25.0 if "25 kg" in text else None,
        "unit_price": _find(rf"{MONEY}\s*per bag", text),
        "delivery_charge": _find(rf"delivery[: ]+{MONEY}", text),
        "total": _find(rf"total[: ]+{MONEY}", text),
        "arrival_time": _time(text),
    }


def _trigger(text: str) -> dict:
    """Cancellation / short-delivery notice."""
    problem = bool(re.search(r"cancel|unable to|can't deliver|cannot deliver|short", text, re.I))
    packs = _find(rf"\b{NUM}\s*(?:×|x)\s*25\s*kg", text, _n)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return {
        "is_supply_problem": problem,
        "kind": "cancelled" if problem else None,
        "supplier_name": lines[-1] if problem and len(lines[-1]) < 40 else None,  # signature line
        "po_reference": _find(r"(PO[-–\s]?\d{4})", text, str),
        "ingredient": "strong white flour" if "strong white flour" in text.lower() else None,
        "quantity_kg_lost": packs * 25.0 if packs else None,
    }


PARSERS = {"TriggerExtract": _trigger, "QuoteExtract": _quote, "ConfirmationExtract": _confirmation}


def stub_complete(messages: list[dict], schema: type[BaseModel] | None, tools: list | None) -> dict:
    """Mimic a chat completion: schema extraction via regex, tool-calling via the assistant's keyword router."""
    text = messages[-1]["content"]
    if schema is not None:
        return {"content": json.dumps(PARSERS[schema.__name__](text)), "tool_calls": []}
    from backend.assistant.chat import stub_router

    return stub_router(messages, tools or [])
