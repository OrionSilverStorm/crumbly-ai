"""Deterministic quote arithmetic: merge replies, derive what can be computed, and list what is still missing."""
import math
from datetime import date
from decimal import Decimal as D

from backend.demo import clock

CENT = D("0.01")
RAW_FIELDS = ["label", "packs", "max_packs", "pack_size_kg", "unit_price", "goods_price", "delivery_charge",
              "delivery_included", "vat_rate", "total", "arrival_time", "arrival_text"]
# Plain-English follow-up question per missing field ({window} filled in by the sourcing agent).
QUESTIONS = {
    "packs": "- How many bags can you supply?",
    "goods_price": "- What is the price for the goods?",
    "delivery_charge": "- Is delivery included? If not, what is the delivery charge?",
    "vat_rate": "- What VAT rate applies?",
    "arrival_at": "- What time exactly would it arrive? We need it between {window}.",
    "total": "- Could you confirm the total? The figures you gave don't add up for us.",
}


def money(v) -> D | None:
    """Value -> Decimal pounds (2 dp), None stays None."""
    return None if v is None else D(str(v)).quantize(CENT)


def packs_needed(shortage_kg, pack_size_kg) -> int:
    """Round a shortage up to whole packs: 160 kg of 25 kg bags -> 7."""
    s, p = D(str(shortage_kg)), D(str(pack_size_kg))
    return int(math.ceil(s / p)) if s > 0 else 0


def merge(previous: dict | None, new: dict) -> dict:
    """Newer stated values override older ones; anything the new reply doesn't mention is kept."""
    out = dict(previous or {})
    out.update({k: v for k, v in new.items() if k in RAW_FIELDS and v is not None})
    return out


def normalise(raw: dict, day: date, vat_default: D | None, pack_default: float) -> dict:
    """Derive unit/goods/delivery/total by arithmetic only. VAT falls back to the catalogue rate for the ingredient;
    pack size falls back to the size we asked for in the enquiry."""
    packs, max_packs = raw.get("packs"), raw.get("max_packs")
    unit, goods = money(raw.get("unit_price")), money(raw.get("goods_price"))
    if unit is None and goods is not None and packs:
        unit = (goods / packs).quantize(CENT)
    if goods is None and unit is not None and packs:
        goods = unit * packs
    delivery = money(raw.get("delivery_charge"))
    if delivery is None and raw.get("delivery_included"):
        delivery = D("0.00")
    vat = D(str(raw["vat_rate"])) if raw.get("vat_rate") is not None else vat_default
    arrival = clock.at(day, raw["arrival_time"]) if raw.get("arrival_time") else None
    computed = money((goods + delivery) * (1 + vat)) if None not in (goods, delivery, vat) else None
    stated = money(raw.get("total"))
    missing = [f for f, gone in (
        ("packs", packs is None and max_packs is None),
        ("goods_price", goods is None and unit is None),
        ("delivery_charge", delivery is None),
        ("vat_rate", vat is None),
        ("arrival_at", arrival is None),
        ("total", stated is not None and computed is not None and abs(stated - computed) > CENT),
    ) if gone]
    return {
        "label": raw.get("label"), "packs": packs, "max_packs": max_packs, "pack_size_kg": raw.get("pack_size_kg") or pack_default,
        "unit_price": unit, "goods_price": goods, "delivery_charge": delivery, "vat_rate": vat,
        "total": stated if stated is not None else computed, "arrival_at": arrival,
        "arrival_text": raw.get("arrival_text"), "missing_fields": missing,
    }
