"""Matching engine — pure module, no I/O.

Takes a list of candidate ANNOUNCE payloads and a DISCOVER query, returns the
candidates that pass hard filters, scored and ranked. Each result carries a
`match.reasons` array of structured tags so an LLM consumer can read off why
an offer matched.

Disqualifiers (return None for that candidate):
  - product score == 0 (no overlap)
  - price exceeds max_price
  - any required certification is missing

Soft signals (contribute to score):
  - product: exact > substring > trigram > token overlap
  - price: lower price relative to max_price → higher score
  - location: exact > substring > mismatch
  - certifications: bonus when all required present
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Iterable


PRODUCT_WEIGHT = 0.50
PRICE_WEIGHT = 0.20
LOCATION_WEIGHT = 0.15
CERT_WEIGHT = 0.15

_FUZZY_THRESHOLD = 0.55


@dataclass
class MatchResult:
    offer: dict
    score: float
    reasons: list[str]

    def to_dict(self) -> dict:
        enriched = dict(self.offer)
        enriched["match"] = {"score": round(self.score, 4), "reasons": self.reasons}
        return enriched


# ─── Per-field scorers ────────────────────────────────────────────────────────

def _product_score(offer_product: str, query_product: str) -> tuple[float, str]:
    op = (offer_product or "").lower().strip()
    qp = (query_product or "").lower().strip()
    if not op or not qp:
        return 0.0, ""
    if op == qp:
        return 1.0, "product:exact"
    if qp in op or op in qp:
        return 0.8, "product:substring"
    ratio = difflib.SequenceMatcher(None, qp, op).ratio()
    if ratio >= _FUZZY_THRESHOLD:
        return ratio, f"product:fuzzy({ratio:.2f})"
    q_tokens, o_tokens = set(qp.split()), set(op.split())
    if q_tokens and o_tokens:
        overlap = len(q_tokens & o_tokens) / len(q_tokens | o_tokens)
        if overlap > 0:
            return overlap * 0.6, f"product:tokens({overlap:.2f})"
    return 0.0, ""


def _price_score(offer_price: float, max_price: float | None) -> tuple[float, str]:
    if max_price is None:
        return 0.5, "price:no-cap"
    if offer_price > max_price:
        return -1.0, f"price:over-cap({offer_price}>{max_price})"
    headroom = (max_price - offer_price) / max_price if max_price > 0 else 0.0
    return min(1.0, 0.5 + headroom * 0.5), f"price:headroom({headroom:.2f})"


def _location_score(offer_location: str, query_location: str | None) -> tuple[float, str]:
    if not query_location:
        return 0.5, "location:any"
    ol = (offer_location or "").lower().strip()
    ql = query_location.lower().strip()
    if not ol:
        return 0.0, "location:unknown"
    if ol == ql:
        return 1.0, "location:exact"
    if ql in ol or ol in ql:
        return 0.7, "location:substring"
    return 0.2, "location:mismatch"


def _cert_score(offer_certs: list[str] | None,
                required: list[str] | None) -> tuple[float, str]:
    if not required:
        return 0.5, "cert:none-required"
    have = {c.lower() for c in (offer_certs or [])}
    need = {c.lower() for c in required}
    missing = need - have
    if missing:
        return -1.0, f"cert:missing({','.join(sorted(missing))})"
    return 1.0, f"cert:all({','.join(sorted(need))})"


# ─── Aggregator ───────────────────────────────────────────────────────────────

def score_offer(offer: dict, query: dict) -> MatchResult | None:
    """Score one offer against a query. Returns None if a hard filter rejects it."""
    p, p_reason = _product_score(offer.get("product", ""), query.get("product", ""))
    if p == 0.0:
        return None

    pr, pr_reason = _price_score(float(offer.get("price_min", 0.0)),
                                 query.get("max_price"))
    if pr < 0:
        return None

    l, l_reason = _location_score(offer.get("location", ""), query.get("location"))

    c, c_reason = _cert_score(offer.get("certifications", []),
                              query.get("certifications_required"))
    if c < 0:
        return None

    total = (p * PRODUCT_WEIGHT
             + pr * PRICE_WEIGHT
             + l * LOCATION_WEIGHT
             + c * CERT_WEIGHT)
    reasons = [r for r in (p_reason, pr_reason, l_reason, c_reason) if r]
    return MatchResult(offer=offer, score=total, reasons=reasons)


def rank(offers: Iterable[dict], query: dict) -> list[MatchResult]:
    """Score and sort. Disqualified offers are dropped. Stable on ties via offer_id."""
    scored = [r for r in (score_offer(o, query) for o in offers) if r is not None]
    scored.sort(key=lambda r: (-r.score, r.offer.get("offer_id", "")))
    return scored
