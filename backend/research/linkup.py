"""Supplier discovery and claim verification with Linkup (/search structured + sources, /fetch).

Privacy rule: queries are built ONLY from ingredient, pack size and postcode area (see build_query). Customer names,
order ids and recipes never reach Linkup; tests/test_privacy.py enforces this.
"""
import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from backend.config import ROOT, settings
from backend.demo import clock
from backend.tracing import traced

CACHE = ROOT / ".linkup_cache"
FIXTURES = Path(__file__).parent / "fixtures"


class Product(BaseModel):
    name: str | None = None
    pack_size_kg: float | None = None


class FoundSupplier(BaseModel):
    """One supplier as described by search results (the discovery schema)."""

    supplier_name: str
    website: str | None = None
    location: str | None = None
    delivery_areas: list[str] = []
    products: list[Product] = []
    next_day_cutoff: str | None = None
    earliest_delivery_time: str | None = None
    trade_minimum: str | None = None
    contact_email: str | None = None
    phone: str | None = None


class Discovery(BaseModel):
    suppliers: list[FoundSupplier] = []


class Claims(BaseModel):
    """Key claims re-checked against a second source."""

    delivers_to_area: bool | None = None
    sells_pack_size: bool | None = None
    earliest_delivery_time: str | None = None
    trade_minimum: str | None = None


def build_query(ingredient: str, pack_size_kg: float, area: str) -> str:
    """The only way a discovery query is built: ingredient/spec, pack size, postcode area."""
    return f"wholesale {ingredient} {pack_size_kg:g} kg bags next-day delivery {area} London"


def verify_query(supplier: str, ingredient: str, pack_size_kg: float, area: str) -> str:
    """Independent check on a (public) supplier name; same privacy rule."""
    return f"{supplier} {ingredient} {pack_size_kg:g} kg delivery {area} delivery times trade minimum order"


def domain(url: str | None) -> str | None:
    """'https://www.thamesgrain.example/trade' -> 'thamesgrain.example'."""
    m = re.search(r"(?:https?://)?(?:www\.)?([^/\s]+)", url or "")
    return m.group(1).lower() if m else None


class Linkup:
    """Thin wrapper adding disk caching (LINKUP_CACHE=1) and bundled fixtures (LINKUP_MODE=fixture)."""

    def __init__(self):
        self.queries: list[str] = []  # every outgoing query/URL, kept for the privacy test and the UI

    def _call(self, op: str, **kw) -> dict:
        """Run a search/fetch and return {'data': dict, 'sources': [{'name','url'}], 'retrieved_at': iso}."""
        self.queries.append(kw.get("query") or kw.get("url"))
        if settings.linkup_mode == "fixture":
            return self._fixture(op, kw)
        key = CACHE / (hashlib.sha256(json.dumps([op, kw], sort_keys=True, default=str).encode()).hexdigest()[:24] + ".json")
        if settings.linkup_cache and key.exists():
            return json.loads(key.read_text(encoding="utf-8"))
        from linkup import LinkupClient

        client = LinkupClient(api_key=settings.linkup_api_key)
        if op == "fetch":
            r = client.fetch(url=kw["url"], schema=kw["schema"])
            out = {"data": r.data or {}, "sources": [{"name": "supplier page", "url": kw["url"]}]}
        else:
            r = client.search(query=kw["query"], depth="standard", output_type="structured",
                              structured_output_schema=kw["schema"], include_sources=True,
                              exclude_domains=kw.get("exclude_domains"))
            out = {"data": r.data if isinstance(r.data, dict) else r.data.model_dump(),
                   "sources": [{"name": s.name, "url": s.url} for s in r.sources]}
        out["retrieved_at"] = clock.now().isoformat()
        if settings.linkup_cache:
            CACHE.mkdir(exist_ok=True)
            key.write_text(json.dumps(out, default=str), encoding="utf-8")
        return out

    def _fixture(self, op: str, kw: dict) -> dict:
        """Bundled fictional responses (Thames Grain Co.) so the scripted demo is repeatable offline."""
        fx = json.loads((FIXTURES / "thames_grain.json").read_text(encoding="utf-8"))
        name = "verify" if kw.get("exclude_domains") else op
        return {**fx[name], "retrieved_at": clock.now().isoformat()}

    @traced("linkup.discover", span_type="RETRIEVER")
    def discover(self, ingredient: str, pack_size_kg: float, area: str) -> tuple[list[FoundSupplier], list[dict], str]:
        """Find candidate suppliers. Returns (suppliers, sources, retrieved_at)."""
        r = self._call("discover", query=build_query(ingredient, pack_size_kg, area), schema=Discovery)
        return Discovery.model_validate(r["data"]).suppliers, r["sources"], r["retrieved_at"]

    @traced("linkup.verify", span_type="RETRIEVER")
    def verify(self, s: FoundSupplier, ingredient: str, pack_size_kg: float, area: str) -> list[dict]:
        """Cross-check key claims: the supplier's own page (/fetch) vs. an independent search excluding their domain."""
        own_url = f"https://{domain(s.website)}/trade" if s.website else None
        own = self._call("fetch", url=own_url, schema=Claims) if own_url else None
        ind = self._call("search", query=verify_query(s.supplier_name, ingredient, pack_size_kg, area),
                         schema=Claims, exclude_domains=[domain(s.website)] if s.website else None)
        own_c = Claims.model_validate(own["data"]) if own else Claims(
            delivers_to_area=area in s.delivery_areas or None, earliest_delivery_time=s.earliest_delivery_time,
            trade_minimum=s.trade_minimum, sells_pack_size=any(p.pack_size_kg == pack_size_kg for p in s.products) or None)
        ind_c = Claims.model_validate(ind["data"])
        own_src = [x["url"] for x in (own["sources"] if own else [])]
        ind_src = [x["url"] for x in ind["sources"]]
        labels = {
            "delivers_to_area": f"Delivers to {area}",
            "sells_pack_size": f"Sells {pack_size_kg:g} kg {ingredient}",
            "earliest_delivery_time": "Next-day delivery from",
            "trade_minimum": "Trade minimum",
        }
        return [_judge(labels[f], getattr(own_c, f), getattr(ind_c, f), own_src, ind_src, f) for f in labels]


def _norm(v):
    """Comparable form: HH:MM times, digits for money, bools as-is."""
    if isinstance(v, str):
        t = re.search(r"(\d{1,2}):(\d{2})", v)
        return f"{int(t.group(1)):02d}:{t.group(2)}" if t else re.sub(r"[^\d.]", "", v) or v.lower()
    return v


def _judge(claim: str, a, b, a_src: list[str], b_src: list[str], field: str) -> dict:
    """confirmed = two sources agree; conflicting = they disagree (keep both); unverified = only one source."""
    shown = lambda v: "yes" if v is True else "no" if v is False else str(v)  # noqa: E731
    if a is not None and b is not None:
        same = _norm(a) == _norm(b)
        return {"claim": claim, "field": field, "status": "confirmed" if same else "conflicting",
                "value": shown(a) if same else f"{shown(a)} vs {shown(b)}", "values": [shown(a), shown(b)],
                "source_urls": a_src + b_src}
    v, src = (a, a_src) if a is not None else (b, b_src)
    return {"claim": claim, "field": field, "status": "unverified", "value": None if v is None else shown(v),
            "values": [] if v is None else [shown(v)], "source_urls": src}
