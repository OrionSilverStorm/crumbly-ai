"""Pydantic schemas for everything an LLM extracts. Models only interpret text; code validates and decides.

Money is a float here (JSON-schema friendly) and converted to Decimal by code immediately after validation.
Every field is optional: a model must return null rather than guess, and null fields trigger a follow-up.
"""
from typing import Literal

from pydantic import BaseModel, Field


class TriggerExtract(BaseModel):
    """What a possibly-problematic supplier email says about an existing order."""

    is_supply_problem: bool = Field(description="True if the email cancels, shortens or delays a delivery")
    kind: Literal["cancelled", "shortened", "delayed", "other"] | None = None
    supplier_name: str | None = None
    po_reference: str | None = Field(None, description="Purchase order reference exactly as written, e.g. PO-0079")
    ingredient: str | None = None
    quantity_kg_lost: float | None = Field(None, description="Kg that will no longer arrive, if stated or computable from packs")


class QuoteOffer(BaseModel):
    """One offer inside a supplier reply. A reply may hold several (e.g. a standard van and a limited early van)."""

    label: str | None = Field(None, description="Short name, e.g. 'standard van' or 'early van'")
    packs: int | None = Field(None, description="Number of packs offered")
    max_packs: int | None = Field(None, description="Upper limit if the offer is capacity-limited ('up to N bags')")
    pack_size_kg: float | None = None
    unit_price: float | None = Field(None, description="Price per pack in GBP, if stated")
    goods_price: float | None = Field(None, description="Price for the goods in GBP, excluding delivery")
    delivery_charge: float | None = Field(None, description="Delivery charge in GBP; 0 only if delivery is explicitly free or included")
    delivery_included: bool | None = Field(None, description="True if the email says delivery is included")
    vat_rate: float | None = Field(None, description="VAT as a fraction (0.2 = 20%), only if stated")
    total: float | None = Field(None, description="Total in GBP, only if stated")
    arrival_time: str | None = Field(None, description="Specific local arrival time as HH:MM; null if vague like 'tomorrow'")
    arrival_text: str | None = Field(None, description="The arrival wording exactly as written")


class QuoteExtract(BaseModel):
    """A supplier's reply to an enquiry or follow-up."""

    declined: bool = Field(False, description="True if the supplier says they cannot supply")
    offers: list[QuoteOffer] = Field(default_factory=list)


class ConfirmationExtract(BaseModel):
    """A supplier's order confirmation."""

    po_reference: str | None = None
    product: str | None = None
    packs: int | None = None
    pack_size_kg: float | None = None
    unit_price: float | None = None
    delivery_charge: float | None = None
    total: float | None = None
    arrival_time: str | None = Field(None, description="Confirmed arrival time as HH:MM")
