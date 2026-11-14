"""Plain-English glossary for the help assistant (British English, no jargon)."""

TERMS = {
    "on order": "Flour on its way. The supplier has confirmed it, but it isn't on your shelf yet. We only count it as in stock once it arrives and you check it in.",
    "on hand": "Flour on your shelf right now.",
    "shortage": "How much flour is missing for tomorrow's bakes, after counting what you have and what's still on its way.",
    "bake slot": "A time a batch goes in the oven, for example 06:00. Flour has to arrive at least an hour before.",
    "spending limit": "The most Crumbly can spend on one problem without asking you. You can change it on the Rules page.",
    "auto-order": "When an offer passes every one of your rules, Crumbly can place the order for you. If anything is outside your rules, it asks you first.",
    "approved supplier": "A supplier you already buy from and trust. New suppliers can be asked for prices, but you always decide before we buy from them.",
    "quote": "A supplier's offer: how many bags, the price, delivery charge, VAT and when it will arrive.",
    "follow-up": "A short email asking a supplier for the details they left out, so we can compare offers fairly.",
    "confirmation": "The supplier's reply agreeing to an order. We check every detail against what was agreed before accepting it.",
    "linkup": "A web research service Crumbly uses to find and double-check new suppliers. It only ever searches for the ingredient and your area, never your customers.",
    "incident": "One problem with a delivery, from the moment we spot it until it's sorted.",
}


def explain(term: str) -> dict:
    """Best-match definition, or a polite 'don't know'."""
    t = term.lower().strip()
    for k, v in TERMS.items():
        if k in t or t in k:
            return {"term": k, "meaning": v}
    return {"term": term, "meaning": None}
