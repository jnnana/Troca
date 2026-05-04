"""Zocux Protocol — reference MCP server (v0.1).

Append-only ledger of protocol messages plus a derived view of closed deals.
Schema lives in db/schema.sql. Authorisation rules and idempotency semantics
are documented in PROTOCOL.md and CLAUDE.md.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from server import matching_engine

app = Server("zocux-market")

db_pool = None
redis_client = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zocux:zocux@localhost/zocux")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "manifest.json"


# ─── Connection helpers ───────────────────────────────────────────────────────

async def get_db():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL)
    return db_pool


async def get_redis():
    global redis_client
    if redis_client is None:
        redis_client = await aioredis.from_url(REDIS_URL)
    return redis_client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_result(obj: dict) -> list:
    return [TextContent(type="text", text=json.dumps(obj))]


# ─── Canonical error vocabulary ───────────────────────────────────────────────
# Closed enum. Agents branch on `code`, never on `hint`. `retryable=true` means
# the same call may succeed later without a state change on the agent side
# (e.g. a transient infra error — none of the v0.1 codes are retryable).

class ErrorCode:
    OFFER_NOT_FOUND = "OFFER_NOT_FOUND"
    PROPOSAL_NOT_FOUND = "PROPOSAL_NOT_FOUND"
    DEAL_NOT_FOUND = "DEAL_NOT_FOUND"
    PROPOSAL_ALREADY_RESOLVED = "PROPOSAL_ALREADY_RESOLVED"
    AUTH_DENIED = "AUTH_DENIED"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"


def _err(code: str, hint: str | None = None, retryable: bool = False) -> list:
    body: dict = {"error": {"code": code, "retryable": retryable}}
    if hint:
        body["error"]["hint"] = hint
    return text_result(body)


# ─── Tool descriptions (RFC-style, agent-readable) ────────────────────────────
# Format is fixed: each line is `KEY: value`. Agents may parse this directly.
# Keys: EFFECT, AUTH, IDEMPOTENT, FILTERS, RETURNS, ERRORS, NOTE.

ANNOUNCE_DESC = (
    "EFFECT: append ANNOUNCE to ledger; offer is active until `available_until`.\n"
    "AUTH: any agent; caller becomes seller of the new offer.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: agent_id+ANNOUNCE).\n"
    "RETURNS: {status, offer_id, message}; status ∈ {announced, duplicate}.\n"
    "ERRORS: none."
)

DISCOVER_DESC = (
    "EFFECT: rank active offers against the query; appends DISCOVER to ledger as search audit.\n"
    "AUTH: any agent.\n"
    "IDEMPOTENT: yes via `idempotency_key` for the audit row (scope: agent_id+DISCOVER).\n"
    "MATCHING: hard filters reject when product score is 0, max_price is exceeded, "
    "or a required certification is missing. Soft signals contribute to the score: "
    "product (exact > substring > trigram > token overlap), price headroom, location "
    "(exact > substring > mismatch), certifications.\n"
    "FILTERS: `product` (required); `max_price` upper bound; `location` text; "
    "`certification_required` exact match.\n"
    "RETURNS: {offers, count, market}; each offer carries `match: {score, reasons}`. "
    "Sorted by score desc; ties broken by offer_id.\n"
    "ERRORS: none."
)

PROPOSE_DESC = (
    "EFFECT: append PROPOSE; cache proposal 24h in redis; await seller decision.\n"
    "AUTH: any agent except the seller of the offer.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: buyer_agent_id+PROPOSE).\n"
    "RETURNS: {status, proposal_id, message}; status ∈ {proposed, duplicate}.\n"
    "ERRORS: OFFER_NOT_FOUND, AUTH_DENIED."
)

COUNTER_DESC = (
    "EFFECT: append COUNTER on an open proposal; the proposal stays open with new terms tracked alongside it.\n"
    "AUTH: seller of the underlying offer OR buyer that originated the proposal.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: agent_id+COUNTER).\n"
    "RETURNS: {status, counter_id}; status ∈ {countered, duplicate}.\n"
    "ERRORS: PROPOSAL_NOT_FOUND, PROPOSAL_ALREADY_RESOLVED, AUTH_DENIED."
)

ACCEPT_DESC = (
    "EFFECT: append ACCEPT; insert closed_deals; offer becomes inactive; agreement is binding.\n"
    "AUTH: only the seller of the offer underlying the proposal.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: accepting_agent_id+ACCEPT).\n"
    "RETURNS: {status, deal_id, agreement, message}; status ∈ {deal_closed, duplicate}.\n"
    "ERRORS: PROPOSAL_NOT_FOUND, OFFER_NOT_FOUND, PROPOSAL_ALREADY_RESOLVED, AUTH_DENIED."
)

REJECT_DESC = (
    "EFFECT: append REJECT; proposal is closed; underlying offer remains active.\n"
    "AUTH: seller of the offer OR buyer that originated the proposal.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: rejecting_agent_id+REJECT).\n"
    "RETURNS: {status, reason}; status ∈ {rejected, duplicate}.\n"
    "ERRORS: PROPOSAL_NOT_FOUND, PROPOSAL_ALREADY_RESOLVED, AUTH_DENIED."
)

DISPUTE_DESC = (
    "EFFECT: append DISPUTE on a closed deal; flag for off-protocol resolution; affects reputation.\n"
    "AUTH: seller or buyer of the deal.\n"
    "IDEMPOTENT: yes via `idempotency_key` (scope: disputing_agent_id+DISPUTE).\n"
    "RETURNS: {status}; status ∈ {disputed, duplicate}.\n"
    "ERRORS: DEAL_NOT_FOUND, AUTH_DENIED.\n"
    "NOTE: does not reverse the agreement; resolution is off-protocol."
)

STATS_DESC = (
    "EFFECT: read aggregate market stats (deals_closed, total_volume_eur, active_offers).\n"
    "AUTH: any agent.\n"
    "IDEMPOTENT: n/a (read-only, no audit row).\n"
    "FILTERS: optional `product` ILIKE substring.\n"
    "RETURNS: {market, stats}.\n"
    "ERRORS: none."
)

MANIFEST_DESC = (
    "EFFECT: read the canonical protocol manifest. Call this once at session start.\n"
    "AUTH: any agent.\n"
    "IDEMPOTENT: n/a (read-only, no audit row).\n"
    "RETURNS: full manifest object covering envelope, error_vocabulary, idempotency, "
    "authorization, state_machine, invariants, limitations_v0_1.\n"
    "ERRORS: none.\n"
    "NOTE: tool catalogue itself is not duplicated here; use MCP tools/list."
)


# ─── Append-only ledger with idempotency ──────────────────────────────────────

async def log_message(msg_type: str, payload: dict, agent_id: str,
                      idempotency_key: str | None = None):
    """Insert a message; if (agent_id, type, idempotency_key) already exists,
    return the prior payload and was_dup=True. Never UPDATE."""
    pool = await get_db()
    async with pool.acquire() as conn:
        if idempotency_key is not None:
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key,
            )
            if existing:
                return json.loads(existing["payload"]), True
        try:
            await conn.execute(
                "INSERT INTO protocol_messages (type, payload, agent_id, idempotency_key) "
                "VALUES ($1, $2, $3, $4)",
                msg_type, json.dumps(payload), agent_id, idempotency_key,
            )
        except asyncpg.exceptions.UniqueViolationError:
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key,
            )
            return json.loads(existing["payload"]), True
        return payload, False


# ─── Loaders / authorisation helpers ──────────────────────────────────────────

async def _load_offer(conn, offer_id: str):
    row = await conn.fetchrow(
        "SELECT payload FROM protocol_messages "
        "WHERE type='ANNOUNCE' AND payload->>'offer_id'=$1",
        offer_id,
    )
    return json.loads(row["payload"]) if row else None


async def _load_proposal(conn, proposal_id: str):
    r = await get_redis()
    cached = await r.get(f"proposal:{proposal_id}")
    if cached:
        return json.loads(cached)
    row = await conn.fetchrow(
        "SELECT payload FROM protocol_messages "
        "WHERE type='PROPOSE' AND payload->>'proposal_id'=$1",
        proposal_id,
    )
    return json.loads(row["payload"]) if row else None


async def _proposal_resolved(conn, proposal_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM protocol_messages "
        "WHERE type IN ('ACCEPT','REJECT') AND payload->>'proposal_id'=$1 LIMIT 1",
        proposal_id,
    )
    return row is not None


# ─── Tool catalogue ───────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="announce_offer",
            description=ANNOUNCE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": ["kg", "ton", "unit", "liter", "box"]},
                    "price_min": {"type": "number"},
                    "price_currency": {"type": "string", "default": "EUR"},
                    "location": {"type": "string"},
                    "available_from": {"type": "string"},
                    "available_until": {"type": "string"},
                    "certifications": {"type": "array", "items": {"type": "string"}, "default": []},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["agent_id", "product", "quantity", "unit", "price_min", "location", "available_until"],
            },
        ),
        Tool(
            name="discover_offers",
            description=DISCOVER_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity_needed": {"type": "number"},
                    "max_price": {"type": "number"},
                    "location": {"type": "string"},
                    "certification_required": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["agent_id", "product"],
            },
        ),
        Tool(
            name="propose_deal",
            description=PROPOSE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "offer_id": {"type": "string"},
                    "buyer_agent_id": {"type": "string"},
                    "proposed_price": {"type": "number"},
                    "proposed_quantity": {"type": "number"},
                    "proposed_delivery": {"type": "string"},
                    "expires_at": {"type": "string", "description": "ISO8601 deadline for seller response"},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["offer_id", "buyer_agent_id", "proposed_price", "proposed_quantity",
                             "proposed_delivery", "expires_at"],
            },
        ),
        Tool(
            name="counter_propose",
            description=COUNTER_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "counter_price": {"type": "number"},
                    "counter_quantity": {"type": "number"},
                    "counter_delivery": {"type": "string"},
                    "expires_at": {"type": "string"},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "agent_id", "counter_price", "counter_quantity",
                             "counter_delivery", "expires_at"],
            },
        ),
        Tool(
            name="accept_deal",
            description=ACCEPT_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "accepting_agent_id": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "accepting_agent_id"],
            },
        ),
        Tool(
            name="reject_deal",
            description=REJECT_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "rejecting_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["proposal_id", "rejecting_agent_id", "reason"],
            },
        ),
        Tool(
            name="dispute_deal",
            description=DISPUTE_DESC,
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "disputing_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"},
                    "idempotency_key": {"type": "string"},
                },
                "required": ["deal_id", "disputing_agent_id", "reason"],
            },
        ),
        Tool(
            name="get_market_stats",
            description=STATS_DESC,
            inputSchema={
                "type": "object",
                "properties": {"product": {"type": "string"}},
            },
        ),
        Tool(
            name="get_protocol_manifest",
            description=MANIFEST_DESC,
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    pool = await get_db()
    idem = arguments.pop("idempotency_key", None)

    if name == "announce_offer":
        offer_id = str(uuid.uuid4())[:12]
        payload = {"offer_id": offer_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("ANNOUNCE", payload, arguments["agent_id"], idem)
        return text_result({
            "status": "duplicate" if was_dup else "announced",
            "offer_id": stored["offer_id"],
            "message": f"Offer {stored['offer_id']} is live in the Zocux market",
        })

    if name == "discover_offers":
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT payload FROM protocol_messages m
                WHERE type='ANNOUNCE'
                  AND (payload->>'available_until')::timestamptz > NOW()
                  AND NOT EXISTS (
                        SELECT 1 FROM protocol_messages a
                        WHERE a.type='ACCEPT'
                          AND a.payload->>'offer_id' = m.payload->>'offer_id'
                  )
            """)
            candidates = [json.loads(r["payload"]) for r in rows]
        # Map the wire field name to the engine's canonical key.
        query = dict(arguments)
        if query.get("certification_required"):
            query["certifications_required"] = [query["certification_required"]]
        ranked = matching_engine.rank(candidates, query)
        offers = [r.to_dict() for r in ranked]
        await log_message("DISCOVER",
                          {"created_at": now_iso(), **arguments},
                          arguments["agent_id"], idem)
        return text_result({"offers": offers, "count": len(offers),
                            "market": "zocux-protocol-v0.1"})

    if name == "propose_deal":
        async with pool.acquire() as conn:
            offer = await _load_offer(conn, arguments["offer_id"])
        if offer is None:
            return _err(ErrorCode.OFFER_NOT_FOUND,
                        hint=f"offer_id={arguments['offer_id']}")
        if arguments["buyer_agent_id"] == offer.get("agent_id"):
            return _err(ErrorCode.AUTH_DENIED,
                        hint="seller cannot propose against their own offer")
        proposal_id = str(uuid.uuid4())[:12]
        payload = {"proposal_id": proposal_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("PROPOSE", payload,
                                            arguments["buyer_agent_id"], idem)
        r = await get_redis()
        await r.setex(f"proposal:{stored['proposal_id']}", 86400, json.dumps(stored))
        return text_result({
            "status": "duplicate" if was_dup else "proposed",
            "proposal_id": stored["proposal_id"],
            "message": "Proposal submitted. Waiting for seller response.",
        })

    if name == "counter_propose":
        async with pool.acquire() as conn:
            original = await _load_proposal(conn, arguments["proposal_id"])
            if original is None:
                return _err(ErrorCode.PROPOSAL_NOT_FOUND,
                            hint=f"proposal_id={arguments['proposal_id']}")
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return _err(ErrorCode.PROPOSAL_ALREADY_RESOLVED,
                            hint=f"proposal_id={arguments['proposal_id']}")
            offer = await _load_offer(conn, original["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = original.get("buyer_agent_id")
        if arguments["agent_id"] not in (seller_id, buyer_id):
            return _err(ErrorCode.AUTH_DENIED,
                        hint=f"caller={arguments['agent_id']}; allowed=seller({seller_id}) or buyer({buyer_id})")
        counter_id = str(uuid.uuid4())[:12]
        payload = {"counter_id": counter_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("COUNTER", payload, arguments["agent_id"], idem)
        return text_result({
            "status": "duplicate" if was_dup else "countered",
            "counter_id": stored["counter_id"],
        })

    if name == "accept_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return _err(ErrorCode.PROPOSAL_NOT_FOUND,
                            hint=f"proposal_id={arguments['proposal_id']}")
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return _err(ErrorCode.PROPOSAL_ALREADY_RESOLVED,
                            hint=f"proposal_id={arguments['proposal_id']}")
            offer = await _load_offer(conn, proposal["offer_id"])
            if offer is None:
                return _err(ErrorCode.OFFER_NOT_FOUND,
                            hint=f"offer_id={proposal['offer_id']}")
            if arguments["accepting_agent_id"] != offer.get("agent_id"):
                return _err(ErrorCode.AUTH_DENIED,
                            hint=f"caller={arguments['accepting_agent_id']}; allowed=seller({offer.get('agent_id')})")

            deal_id = str(uuid.uuid4())[:12]
            accept_payload = {
                "deal_id": deal_id,
                "proposal_id": arguments["proposal_id"],
                "accepting_agent_id": arguments["accepting_agent_id"],
                "offer_id": proposal["offer_id"],
                "final_price": proposal["proposed_price"],
                "final_quantity": proposal["proposed_quantity"],
                "final_delivery": proposal["proposed_delivery"],
                "accepted_at": now_iso(),
            }
            stored, was_dup = await log_message("ACCEPT", accept_payload,
                                                arguments["accepting_agent_id"], idem)
            if not was_dup:
                await conn.execute("""
                    INSERT INTO closed_deals
                    (deal_id, offer_id, proposal_id, seller_agent_id, buyer_agent_id,
                     final_price, final_quantity, currency, product, accepted_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (deal_id) DO NOTHING
                """,
                    stored["deal_id"], proposal["offer_id"], arguments["proposal_id"],
                    offer["agent_id"], proposal["buyer_agent_id"],
                    proposal["proposed_price"], proposal["proposed_quantity"],
                    offer.get("price_currency", "EUR"), offer["product"],
                    datetime.now(timezone.utc),
                )
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "deal_closed",
            "deal_id": stored["deal_id"],
            "agreement": stored,
            "message": "Deal recorded. Agreement is binding.",
        })

    if name == "reject_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return _err(ErrorCode.PROPOSAL_NOT_FOUND,
                            hint=f"proposal_id={arguments['proposal_id']}")
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return _err(ErrorCode.PROPOSAL_ALREADY_RESOLVED,
                            hint=f"proposal_id={arguments['proposal_id']}")
            offer = await _load_offer(conn, proposal["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = proposal.get("buyer_agent_id")
        if arguments["rejecting_agent_id"] not in (seller_id, buyer_id):
            return _err(ErrorCode.AUTH_DENIED,
                        hint=f"caller={arguments['rejecting_agent_id']}; allowed=seller({seller_id}) or buyer({buyer_id})")
        payload = {"rejected_at": now_iso(), **arguments}
        stored, was_dup = await log_message("REJECT", payload,
                                            arguments["rejecting_agent_id"], idem)
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "rejected",
            "reason": arguments.get("reason"),
        })

    if name == "dispute_deal":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT seller_agent_id, buyer_agent_id FROM closed_deals WHERE deal_id=$1",
                arguments["deal_id"],
            )
        if row is None:
            return _err(ErrorCode.DEAL_NOT_FOUND,
                        hint=f"deal_id={arguments['deal_id']}")
        if arguments["disputing_agent_id"] not in (row["seller_agent_id"], row["buyer_agent_id"]):
            return _err(ErrorCode.AUTH_DENIED,
                        hint=(f"caller={arguments['disputing_agent_id']}; "
                              f"allowed=seller({row['seller_agent_id']}) or buyer({row['buyer_agent_id']})"))
        payload = {"created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("DISPUTE", payload,
                                            arguments["disputing_agent_id"], idem)
        return text_result({"status": "duplicate" if was_dup else "disputed"})

    if name == "get_market_stats":
        async with pool.acquire() as conn:
            if arguments.get("product"):
                pf = f"%{arguments['product']}%"
                total_deals = await conn.fetchval(
                    "SELECT COUNT(*) FROM closed_deals WHERE product ILIKE $1", pf)
                total_volume = await conn.fetchval(
                    "SELECT COALESCE(SUM(final_price * final_quantity), 0) "
                    "FROM closed_deals WHERE product ILIKE $1", pf)
                active_offers = await conn.fetchval(
                    "SELECT COUNT(*) FROM active_offers WHERE product ILIKE $1", pf)
            else:
                total_deals = await conn.fetchval("SELECT COUNT(*) FROM closed_deals")
                total_volume = await conn.fetchval(
                    "SELECT COALESCE(SUM(final_price * final_quantity), 0) FROM closed_deals")
                active_offers = await conn.fetchval("SELECT COUNT(*) FROM active_offers")
        return text_result({
            "market": "zocux-protocol-v0.1",
            "stats": {
                "deals_closed": int(total_deals),
                "total_volume_eur": float(total_volume),
                "active_offers": int(active_offers),
            },
        })

    if name == "get_protocol_manifest":
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return text_result(manifest)

    return _err(ErrorCode.UNKNOWN_TOOL, hint=f"name={name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
