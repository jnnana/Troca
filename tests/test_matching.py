"""Unit tests for the pure matching engine. No DB or Redis touched."""

from __future__ import annotations

from server import matching_engine as me


def _offer(**overrides) -> dict:
    base = {
        "offer_id": overrides.pop("offer_id", "off-001"),
        "agent_id": "seller-1",
        "product": "Tomatoes",
        "quantity": 100,
        "unit": "kg",
        "price_min": 1.5,
        "location": "Almería, Spain",
        "certifications": [],
        "available_until": "2099-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ─── product scorer ───────────────────────────────────────────────────────────

def test_product_exact_match():
    s, reason = me._product_score("Tomatoes", "Tomatoes")
    assert s == 1.0
    assert reason == "product:exact"


def test_product_substring_match():
    s, reason = me._product_score("Cherry Tomatoes", "tomato")
    assert s == 0.8
    assert reason == "product:substring"


def test_product_fuzzy_match():
    s, reason = me._product_score("Tomatos", "Tomatoes")
    assert 0 < s < 1.0
    assert reason.startswith("product:fuzzy") or reason == "product:substring"


def test_product_no_match_returns_zero():
    s, _ = me._product_score("Olive Oil", "submarine")
    assert s == 0.0


# ─── price scorer ─────────────────────────────────────────────────────────────

def test_price_no_cap_is_neutral():
    s, _ = me._price_score(10.0, None)
    assert s == 0.5


def test_price_under_cap_scores_above_neutral():
    s, _ = me._price_score(5.0, 10.0)
    assert s > 0.5


def test_price_over_cap_is_disqualifier():
    s, reason = me._price_score(15.0, 10.0)
    assert s < 0
    assert reason.startswith("price:over-cap")


# ─── location scorer ──────────────────────────────────────────────────────────

def test_location_exact():
    s, reason = me._location_score("Vigo", "Vigo")
    assert s == 1.0
    assert reason == "location:exact"


def test_location_substring():
    s, reason = me._location_score("Almería, Spain", "almería")
    assert s == 0.7


def test_location_mismatch_still_passes():
    s, _ = me._location_score("Vigo", "Berlin")
    assert s == 0.2  # soft: low score but not a disqualifier


def test_location_query_omitted_is_neutral():
    s, _ = me._location_score("Vigo", None)
    assert s == 0.5


# ─── certification scorer ─────────────────────────────────────────────────────

def test_cert_none_required():
    s, _ = me._cert_score(["organic"], None)
    assert s == 0.5


def test_cert_all_present():
    s, reason = me._cert_score(["organic", "fairtrade"], ["organic"])
    assert s == 1.0
    assert "all" in reason


def test_cert_missing_is_disqualifier():
    s, reason = me._cert_score(["fairtrade"], ["organic"])
    assert s < 0
    assert "missing" in reason


# ─── score_offer integration ──────────────────────────────────────────────────

def test_score_offer_disqualifies_on_product_zero():
    assert me.score_offer(_offer(product="Olive Oil"), {"product": "submarine"}) is None


def test_score_offer_disqualifies_on_overprice():
    assert me.score_offer(_offer(price_min=5.0), {"product": "Tomato", "max_price": 2.0}) is None


def test_score_offer_disqualifies_on_missing_cert():
    result = me.score_offer(
        _offer(certifications=["fairtrade"]),
        {"product": "Tomato", "certifications_required": ["organic"]},
    )
    assert result is None


def test_score_offer_returns_match_with_reasons():
    result = me.score_offer(
        _offer(product="Tomatoes", price_min=1.5, location="Almería",
               certifications=["organic"]),
        {"product": "tomato", "max_price": 2.0, "location": "Almería",
         "certifications_required": ["organic"]},
    )
    assert result is not None
    assert 0 < result.score <= 1.0
    assert any(r.startswith("product:") for r in result.reasons)
    assert any(r.startswith("price:") for r in result.reasons)
    assert any(r.startswith("location:") for r in result.reasons)
    assert any(r.startswith("cert:") for r in result.reasons)


# ─── rank ─────────────────────────────────────────────────────────────────────

def test_rank_orders_by_score_desc():
    cheap = _offer(offer_id="o-cheap", price_min=1.0)
    pricey = _offer(offer_id="o-pricey", price_min=2.5)
    ranked = me.rank([pricey, cheap], {"product": "tomato", "max_price": 5.0})
    assert [r.offer["offer_id"] for r in ranked] == ["o-cheap", "o-pricey"]


def test_rank_drops_disqualified():
    keep = _offer(offer_id="o-keep", price_min=1.0)
    drop = _offer(offer_id="o-drop", price_min=10.0)  # over cap
    ranked = me.rank([keep, drop], {"product": "tomato", "max_price": 5.0})
    assert [r.offer["offer_id"] for r in ranked] == ["o-keep"]


def test_rank_to_dict_attaches_match_metadata():
    keep = _offer(offer_id="o-keep")
    [result] = me.rank([keep], {"product": "tomato"})
    enriched = result.to_dict()
    assert enriched["offer_id"] == "o-keep"
    assert "match" in enriched
    assert "score" in enriched["match"]
    assert isinstance(enriched["match"]["reasons"], list)
