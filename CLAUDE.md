# CLAUDE.md — Zocux Protocol
> Instrucciones para el agente constructor autónomo de Zocux

---

## Qué es Zocux

Zocux es infraestructura de mercado donde agentes IA de distintos orígenes pueden anunciarse, descubrirse, negociar y cerrar acuerdos económicos sobre producto físico — sin intervención humana en el loop central.

No es un marketplace con interfaz. Es un **protocolo + entorno de ejecución** para agentes.

El sector primario (agroalimentario, ganadería, pesca) es el mercado piloto. El protocolo es universal.

**Posicionamiento estratégico**: Zocux es la capa que se sienta encima de los protocolos de pago (Visa/AWS, Google AP2) y debajo de los agentes verticales. Infraestructura neutral, no aplicación. Objetivo a 18 meses: ser adquirible por Mirakl, SAP Ariba, AWS o cooperativas grandes.

---

## Arquitectura del sistema

```
AGENTES EXTERNOS (cualquier LLM)
        │
        ▼
SERVIDOR MCP DE TROCA          ← Lo que construyes
├── announce_offer()
├── discover_offers()
├── propose_deal()
├── counter_propose()
├── accept_deal()
├── reject_deal()
├── dispute_deal()
└── get_market_stats()
        │
        ▼
MOTOR DE MERCADO
├── Motor de matching
├── Registro de acuerdos (append-only)
└── Sistema de reputación
        │
        ▼
PERSISTENCIA
├── PostgreSQL (transacciones, registro inmutable)
└── Redis (estado de negociaciones en curso)
```

---

## Stack técnico

| Componente | Tecnología | Justificación |
|---|---|---|
| Servidor MCP | Python + MCP SDK (`mcp`) | SDK oficial; FastMCP es opcional como wrapper ergonómico |
| API REST | FastAPI | Simple, bien documentado |
| Base de datos | PostgreSQL | Append-only para registro de mensajes |
| Estado en tiempo real | Redis | Negociaciones en curso, rápido |
| Orquestación workflows | n8n (ya instalado) | Post-acuerdo, notificaciones |
| Infraestructura | Contabo VPS Ubuntu | Ya disponible |
| Modelo IA agentes | Claude Sonnet 4.6 | Coste/rendimiento óptimo |
| Modelo IA tareas simples | Claude Haiku 4.5 | Matching y clasificación |

---

## Protocolo de mensajes v0.1

Estos son los únicos mensajes válidos entre agentes. No añadir más sin actualizar esta especificación.

**Idempotencia**: cualquier llamada mutadora (ANNOUNCE, PROPOSE, COUNTER, ACCEPT, REJECT, DISPUTE) acepta opcionalmente `idempotency_key: string` (≤100 chars). El servidor garantiza que dos llamadas con el mismo `(agent_id, type, idempotency_key)` producen el mismo efecto: la segunda devuelve el resultado de la primera sin crear un duplicado.

### ANNOUNCE
Un agente anuncia disponibilidad de producto.
```json
{
  "type": "ANNOUNCE",
  "offer_id": "uuid",
  "agent_id": "string",
  "product": "string",
  "quantity": "float",
  "unit": "string (kg|ton|unit|liter)",
  "price_min": "float",
  "price_currency": "string (EUR|USD)",
  "location": "string",
  "available_from": "ISO8601",
  "available_until": "ISO8601",
  "certifications": ["string"],
  "notes": "string|null",
  "created_at": "ISO8601"
}
```

### DISCOVER
Un agente busca ofertas que cumplan criterios.
```json
{
  "type": "DISCOVER",
  "agent_id": "string",
  "product": "string",
  "quantity_needed": "float",
  "unit": "string",
  "max_price": "float|null",
  "location_radius_km": "int|null",
  "location_center": "string|null",
  "needed_by": "ISO8601|null",
  "certifications_required": ["string"]
}
```

### PROPOSE
Un agente comprador propone condiciones sobre una oferta existente.
```json
{
  "type": "PROPOSE",
  "proposal_id": "uuid",
  "offer_id": "string",
  "buyer_agent_id": "string",
  "proposed_price": "float",
  "proposed_quantity": "float",
  "proposed_delivery": "ISO8601",
  "notes": "string|null",
  "expires_at": "ISO8601"
}
```

### COUNTER
Un agente modifica una propuesta existente.
```json
{
  "type": "COUNTER",
  "counter_id": "uuid",
  "proposal_id": "string",
  "agent_id": "string",
  "counter_price": "float",
  "counter_quantity": "float",
  "counter_delivery": "ISO8601",
  "notes": "string|null",
  "expires_at": "ISO8601"
}
```

### ACCEPT
Cierre de acuerdo. Irreversible salvo DISPUTE posterior.
```json
{
  "type": "ACCEPT",
  "deal_id": "uuid",
  "proposal_id": "string",
  "accepting_agent_id": "string",
  "final_price": "float",
  "final_quantity": "float",
  "final_delivery": "ISO8601",
  "accepted_at": "ISO8601"
}
```

### REJECT
Rechazo de propuesta o cancelación de oferta.
```json
{
  "type": "REJECT",
  "proposal_id": "string",
  "rejecting_agent_id": "string",
  "reason": "string",
  "rejected_at": "ISO8601"
}
```

### DISPUTE
Señal de incumplimiento post-acuerdo.
```json
{
  "type": "DISPUTE",
  "deal_id": "string",
  "disputing_agent_id": "string",
  "reason": "string",
  "evidence": "string|null",
  "created_at": "ISO8601"
}
```

---

## Estructura del repositorio

```
zocux-protocol/
├── CLAUDE.md                  ← Este archivo
├── README.md                  ← Documentación pública
├── PROTOCOL.md                ← Especificación formal del protocolo
├── LICENSE                    ← MIT
│
├── server/
│   ├── zocux_server.py        ← Servidor MCP principal
│   ├── matching_engine.py     ← Motor de matching oferta/demanda
│   ├── registry.py            ← Registro append-only de mensajes
│   └── reputation.py          ← Sistema de reputación de agentes
│
├── db/
│   ├── schema.sql             ← Schema PostgreSQL
│   └── migrations/            ← Migraciones numeradas
│
├── sdk/
│   ├── python/                ← SDK cliente Python
│   └── javascript/            ← SDK cliente JavaScript
│
├── examples/
│   ├── seller_agent.py        ← Agente vendedor de referencia
│   ├── buyer_agent.py         ← Agente comprador de referencia
│   └── negotiation_demo.py    ← Demo de negociación completa
│
├── tests/
│   ├── test_protocol.py       ← Tests del protocolo
│   ├── test_matching.py       ← Tests del motor de matching
│   └── test_e2e.py            ← Tests end-to-end
│
└── docs/
    ├── quickstart.md          ← Tutorial 15 minutos
    ├── architecture.md        ← Arquitectura detallada
    └── api_reference.md       ← Referencia completa de herramientas MCP
```

---

## Schema de base de datos

```sql
-- Registro inmutable de todos los mensajes del protocolo
-- NUNCA se modifica ni elimina una fila. Solo INSERT.
CREATE TABLE protocol_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(20) NOT NULL CHECK (type IN (
        'ANNOUNCE','DISCOVER','PROPOSE','COUNTER',
        'ACCEPT','REJECT','DISPUTE'
    )),
    payload JSONB NOT NULL,
    agent_id VARCHAR(100) NOT NULL,
    idempotency_key VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Dedup: dos llamadas con el mismo (agent_id, type, idempotency_key)
    -- son la misma operación. NULL en idempotency_key se trata como distinto
    -- (semántica por defecto de UNIQUE en PostgreSQL).
    UNIQUE (agent_id, type, idempotency_key)
);

-- Índices para queries frecuentes
CREATE INDEX idx_messages_type ON protocol_messages(type);
CREATE INDEX idx_messages_agent ON protocol_messages(agent_id);
CREATE INDEX idx_messages_created ON protocol_messages(created_at DESC);
CREATE INDEX idx_messages_payload ON protocol_messages USING GIN(payload);

-- Vista (no materializada — refleja estado actual sin REFRESH manual)
-- de ofertas activas: ANNOUNCE no expirado y sin ACCEPT que lo cierre.
CREATE VIEW active_offers AS
SELECT
    payload->>'offer_id' as offer_id,
    payload->>'agent_id' as agent_id,
    payload->>'product' as product,
    (payload->>'quantity')::float as quantity,
    payload->>'unit' as unit,
    (payload->>'price_min')::float as price_min,
    payload->>'price_currency' as currency,
    payload->>'location' as location,
    (payload->>'available_until')::timestamptz as available_until,
    created_at
FROM protocol_messages m
WHERE type = 'ANNOUNCE'
  AND (payload->>'available_until')::timestamptz > NOW()
  AND NOT EXISTS (
        SELECT 1 FROM protocol_messages a
        WHERE a.type = 'ACCEPT'
          AND a.payload->>'offer_id' = m.payload->>'offer_id'
  );

-- Registro de acuerdos cerrados
CREATE TABLE closed_deals (
    deal_id UUID PRIMARY KEY,
    offer_id VARCHAR(100) NOT NULL,
    proposal_id VARCHAR(100) NOT NULL,
    seller_agent_id VARCHAR(100) NOT NULL,
    buyer_agent_id VARCHAR(100) NOT NULL,
    final_price DECIMAL(12,2) NOT NULL,
    final_quantity DECIMAL(12,4) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    product VARCHAR(200) NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_deals_seller ON closed_deals(seller_agent_id);
CREATE INDEX idx_deals_buyer ON closed_deals(buyer_agent_id);
CREATE INDEX idx_deals_product ON closed_deals(product);

-- Reputación de agentes (calculada, no modificable manualmente)
CREATE VIEW agent_reputation AS
WITH participants AS (
    SELECT seller_agent_id AS agent_id, accepted_at FROM closed_deals
    UNION ALL
    SELECT buyer_agent_id AS agent_id, accepted_at FROM closed_deals
)
SELECT
    agent_id,
    COUNT(*)         AS deals_completed,
    MIN(accepted_at) AS first_deal,
    MAX(accepted_at) AS last_deal
FROM participants
GROUP BY agent_id;
```

---

## Servidor MCP — implementación completa

```python
# server/zocux_server.py

import asyncio
import json
import uuid
import os
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

app = Server("zocux-market")

# Conexiones globales (inicializadas perezosamente)
db_pool = None
redis_client = None

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://zocux:zocux@localhost/zocux")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ─── Helpers de conexión y utilidades ─────────────────────────────────────────

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

# ─── Registro append-only con idempotencia ────────────────────────────────────

async def log_message(msg_type: str, payload: dict, agent_id: str,
                      idempotency_key: str | None = None):
    """
    Inserta el mensaje. Si ya existe (agent_id, type, idempotency_key),
    devuelve el payload previamente almacenado y was_dup=True. Nunca UPDATE.
    """
    pool = await get_db()
    async with pool.acquire() as conn:
        if idempotency_key is not None:
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key
            )
            if existing:
                return json.loads(existing["payload"]), True
        try:
            await conn.execute(
                "INSERT INTO protocol_messages (type, payload, agent_id, idempotency_key) "
                "VALUES ($1, $2, $3, $4)",
                msg_type, json.dumps(payload), agent_id, idempotency_key
            )
        except asyncpg.exceptions.UniqueViolationError:
            # Carrera entre dos llamadas concurrentes con la misma idempotency_key
            existing = await conn.fetchrow(
                "SELECT payload FROM protocol_messages "
                "WHERE agent_id=$1 AND type=$2 AND idempotency_key=$3",
                agent_id, msg_type, idempotency_key
            )
            return json.loads(existing["payload"]), True
        return payload, False

# ─── Helpers de carga / autorización ──────────────────────────────────────────

async def _load_offer(conn, offer_id: str):
    row = await conn.fetchrow(
        "SELECT payload FROM protocol_messages "
        "WHERE type='ANNOUNCE' AND payload->>'offer_id'=$1",
        offer_id
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
        proposal_id
    )
    return json.loads(row["payload"]) if row else None

async def _proposal_resolved(conn, proposal_id: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM protocol_messages "
        "WHERE type IN ('ACCEPT','REJECT') AND payload->>'proposal_id'=$1 LIMIT 1",
        proposal_id
    )
    return row is not None

# ─── Definición de herramientas MCP ───────────────────────────────────────────

# Toda tool mutadora acepta opcionalmente `idempotency_key`. Llamar dos veces
# con la misma clave devuelve el resultado de la primera llamada.

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="announce_offer",
            description="Announce availability of a product to the Zocux market",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string", "enum": ["kg","ton","unit","liter","box"]},
                    "price_min": {"type": "number"},
                    "price_currency": {"type": "string", "default": "EUR"},
                    "location": {"type": "string"},
                    "available_from": {"type": "string"},
                    "available_until": {"type": "string"},
                    "certifications": {"type": "array", "items": {"type": "string"}, "default": []},
                    "notes": {"type": "string"},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["agent_id","product","quantity","unit","price_min","location","available_until"]
            }
        ),
        Tool(
            name="discover_offers",
            description="Search active offers in the Zocux market matching criteria",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "product": {"type": "string"},
                    "quantity_needed": {"type": "number"},
                    "max_price": {"type": "number"},
                    "location": {"type": "string"},
                    "certification_required": {"type": "string"},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["agent_id","product"]
            }
        ),
        Tool(
            name="propose_deal",
            description="Submit a deal proposal on an active offer",
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
                    "idempotency_key": {"type": "string"}
                },
                "required": ["offer_id","buyer_agent_id","proposed_price","proposed_quantity",
                             "proposed_delivery","expires_at"]
            }
        ),
        Tool(
            name="counter_propose",
            description="Counter an existing proposal with new terms (seller or buyer of that proposal)",
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
                    "idempotency_key": {"type": "string"}
                },
                "required": ["proposal_id","agent_id","counter_price","counter_quantity",
                             "counter_delivery","expires_at"]
            }
        ),
        Tool(
            name="accept_deal",
            description="Accept a proposal. Must be called by the seller of the underlying offer.",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "accepting_agent_id": {"type": "string"},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["proposal_id","accepting_agent_id"]
            }
        ),
        Tool(
            name="reject_deal",
            description="Reject a proposal. Must be called by seller or buyer of the proposal.",
            inputSchema={
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string"},
                    "rejecting_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["proposal_id","rejecting_agent_id","reason"]
            }
        ),
        Tool(
            name="dispute_deal",
            description="Raise a dispute on a closed deal (seller or buyer of the deal).",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string"},
                    "disputing_agent_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["deal_id","disputing_agent_id","reason"]
            }
        ),
        Tool(
            name="get_market_stats",
            description="Get aggregated market statistics, optionally filtered by product",
            inputSchema={
                "type": "object",
                "properties": {"product": {"type": "string"}}
            }
        ),
    ]

# ─── Despachador de tools ─────────────────────────────────────────────────────

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
            "message": f"Offer {stored['offer_id']} is live in the Zocux market"
        })

    if name == "discover_offers":
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT payload FROM protocol_messages m
                WHERE type='ANNOUNCE'
                  AND payload->>'product' ILIKE $1
                  AND (payload->>'available_until')::timestamptz > NOW()
                  AND NOT EXISTS (
                        SELECT 1 FROM protocol_messages a
                        WHERE a.type='ACCEPT'
                          AND a.payload->>'offer_id' = m.payload->>'offer_id'
                  )
            """, f"%{arguments['product']}%")
            offers = [json.loads(r["payload"]) for r in rows]
            if arguments.get("max_price") is not None:
                offers = [o for o in offers if float(o.get("price_min", 9e18)) <= arguments["max_price"]]
            if arguments.get("location"):
                loc = arguments["location"].lower()
                offers = [o for o in offers if loc in o.get("location", "").lower()]
            if arguments.get("certification_required"):
                req = arguments["certification_required"].lower()
                offers = [o for o in offers
                          if any(req == c.lower() for c in o.get("certifications", []))]
        # Auditar la búsqueda en el registro append-only
        await log_message("DISCOVER",
                          {"created_at": now_iso(), **arguments},
                          arguments["agent_id"], idem)
        return text_result({"offers": offers, "count": len(offers),
                            "market": "zocux-protocol-v0.1"})

    if name == "propose_deal":
        async with pool.acquire() as conn:
            offer = await _load_offer(conn, arguments["offer_id"])
        if offer is None:
            return text_result({"error": "Offer not found"})
        proposal_id = str(uuid.uuid4())[:12]
        payload = {"proposal_id": proposal_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("PROPOSE", payload,
                                            arguments["buyer_agent_id"], idem)
        r = await get_redis()
        await r.setex(f"proposal:{stored['proposal_id']}", 86400, json.dumps(stored))
        return text_result({
            "status": "duplicate" if was_dup else "proposed",
            "proposal_id": stored["proposal_id"],
            "message": "Proposal submitted. Waiting for seller response."
        })

    if name == "counter_propose":
        async with pool.acquire() as conn:
            original = await _load_proposal(conn, arguments["proposal_id"])
            if original is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already accepted or rejected"})
            offer = await _load_offer(conn, original["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = original.get("buyer_agent_id")
        if arguments["agent_id"] not in (seller_id, buyer_id):
            return text_result({"error": "Counter must come from seller or buyer of the proposal"})
        counter_id = str(uuid.uuid4())[:12]
        payload = {"counter_id": counter_id, "created_at": now_iso(), **arguments}
        stored, was_dup = await log_message("COUNTER", payload, arguments["agent_id"], idem)
        return text_result({
            "status": "duplicate" if was_dup else "countered",
            "counter_id": stored["counter_id"]
        })

    if name == "accept_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already resolved"})
            offer = await _load_offer(conn, proposal["offer_id"])
            if offer is None:
                return text_result({"error": "Underlying offer not found"})
            if arguments["accepting_agent_id"] != offer.get("agent_id"):
                return text_result({"error": "Only the seller of the offer can accept"})

            deal_id = str(uuid.uuid4())[:12]
            accept_payload = {
                "deal_id": deal_id,
                "proposal_id": arguments["proposal_id"],
                "accepting_agent_id": arguments["accepting_agent_id"],
                "offer_id": proposal["offer_id"],
                "final_price": proposal["proposed_price"],
                "final_quantity": proposal["proposed_quantity"],
                "final_delivery": proposal["proposed_delivery"],
                "accepted_at": now_iso()
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
                    datetime.now(timezone.utc)
                )
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "deal_closed",
            "deal_id": stored["deal_id"],
            "agreement": stored,
            "message": "Deal recorded. Agreement is binding."
        })

    if name == "reject_deal":
        async with pool.acquire() as conn:
            proposal = await _load_proposal(conn, arguments["proposal_id"])
            if proposal is None:
                return text_result({"error": "Proposal not found"})
            if await _proposal_resolved(conn, arguments["proposal_id"]):
                return text_result({"error": "Proposal already resolved"})
            offer = await _load_offer(conn, proposal["offer_id"])
        seller_id = (offer or {}).get("agent_id")
        buyer_id = proposal.get("buyer_agent_id")
        if arguments["rejecting_agent_id"] not in (seller_id, buyer_id):
            return text_result({"error": "Only seller or buyer of the proposal can reject"})
        payload = {"rejected_at": now_iso(), **arguments}
        stored, was_dup = await log_message("REJECT", payload,
                                            arguments["rejecting_agent_id"], idem)
        r = await get_redis()
        await r.delete(f"proposal:{arguments['proposal_id']}")
        return text_result({
            "status": "duplicate" if was_dup else "rejected",
            "reason": arguments.get("reason")
        })

    if name == "dispute_deal":
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT seller_agent_id, buyer_agent_id FROM closed_deals WHERE deal_id=$1",
                arguments["deal_id"]
            )
        if row is None:
            return text_result({"error": "Deal not found"})
        if arguments["disputing_agent_id"] not in (row["seller_agent_id"], row["buyer_agent_id"]):
            return text_result({"error": "Only seller or buyer of the deal can dispute"})
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
                "active_offers": int(active_offers)
            }
        })

    return text_result({"error": f"Unknown tool: {name}"})

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Variables de entorno requeridas

```bash
# .env — nunca commitear este archivo
DATABASE_URL=postgresql://zocux:zocux_password@localhost:5432/zocux
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...
TROCA_ENV=development   # development | production
TROCA_VERSION=0.1.0
```

---

## Setup inicial en Contabo

```bash
# 1. Instalar dependencias del sistema
sudo apt update && sudo apt install -y python3.11 python3-pip postgresql redis-server

# 2. Crear base de datos
sudo -u postgres psql -c "CREATE USER zocux WITH PASSWORD 'zocux_password';"
sudo -u postgres psql -c "CREATE DATABASE zocux OWNER zocux;"

# 3. Aplicar schema
psql $DATABASE_URL < db/schema.sql

# 4. Instalar dependencias Python
pip install mcp asyncpg redis anthropic python-dotenv

# 5. Verificar que el servidor arranca
python server/zocux_server.py

# 6. Test rápido (en otra terminal)
python examples/negotiation_demo.py
```

---

## Configuración Claude Desktop (para desarrolladores externos)

```json
{
  "mcpServers": {
    "zocux": {
      "command": "python",
      "args": ["/ruta/a/zocux-protocol/server/zocux_server.py"],
      "env": {
        "DATABASE_URL": "postgresql://zocux:zocux_password@localhost:5432/zocux",
        "REDIS_URL": "redis://localhost:6379"
      }
    }
  }
}
```

---

## Reglas de desarrollo para el agente constructor

Estas reglas son absolutas. Seguirlas en cada decisión técnica.

### Lo que SIEMPRE debes hacer
- **Append-only en `protocol_messages`**: nunca UPDATE, nunca DELETE. Solo INSERT.
- **Validar el schema JSON** de cada mensaje antes de persistir (más allá de la validación MCP de input — hay que comprobar la integridad del payload almacenado).
- **Tests antes de merge**: cada nueva herramienta MCP debe tener al menos un test e2e.
- **Logging estructurado**: cada operación debe loggear tipo, agent_id, timestamp y resultado.
- **Idempotencia vía `idempotency_key`**: toda tool mutadora la acepta como campo opcional y la respeta vía `UNIQUE (agent_id, type, idempotency_key)`. El cliente que reintente con la misma clave debe recibir el mismo resultado, no un duplicado.
- **Verificar autorización antes de cerrar/cancelar**:
  - `accept_deal` → solo el `agent_id` vendedor de la `offer_id` referenciada.
  - `reject_deal` → solo seller o buyer involucrados en la propuesta.
  - `counter_propose` → solo seller o buyer de la propuesta original.
  - `dispute_deal` → solo seller o buyer del deal cerrado.
- **Auditar también las DISCOVER**: cada búsqueda se persiste en `protocol_messages` para reconstruir patrones de demanda.

### Lo que NUNCA debes hacer
- Modificar o eliminar registros en `protocol_messages`.
- Añadir lógica de negocio fuera de las herramientas MCP definidas en el protocolo.
- Cambiar el schema de un mensaje existente sin crear una versión nueva del protocolo.
- Exponer datos de un agente a otro agente sin que medie una transacción.
- Aceptar un deal sin verificar (a) que la propuesta existe, (b) que no tiene ya ACCEPT o REJECT previos, y (c) que el caller es el vendedor del offer original.
- Confiar en `agent_id` como identidad sin más en endpoints públicos (ver sección "Seguridad y autenticación").

### Principios de diseño
- **Neutral**: el servidor no favorece a compradores ni vendedores.
- **Integrable**: cualquier agente, independientemente del LLM subyacente, debe poder conectarse.
- **Auditable**: cada acción queda registrada con suficiente contexto para reconstruir el estado completo del mercado.
- **Recuperable**: si el servidor se cae y se reinicia, el estado se reconstruye desde `protocol_messages`.

---

## Seguridad y autenticación

**v0.1 (transporte stdio MCP)**: el servidor confía en el `agent_id` que el cliente declara. El modelo de amenaza es "una sola organización confía en sus propios agentes locales". Aceptable solo para desarrollo y demos.

**Antes de exponer la API REST pública (Paso 5 / Fase 2)**, son requisitos bloqueantes:
- **Identidad de agente verificable**: cada agente recibe un `agent_id` ligado a una credencial (API key firmada por Zocux o JWT vía OIDC). El servidor rechaza cualquier mensaje cuyo `agent_id` no coincida con la credencial presentada.
- **Rate limiting** por `agent_id` (token bucket; defaults sugeridos: 60 ANNOUNCE/h, 600 DISCOVER/h, 120 PROPOSE/h).
- **TLS obligatorio** en todos los endpoints HTTP.
- **CORS restrictivo**: solo orígenes de SDKs registrados.
- **Auditoría de errores de autorización** en `protocol_messages` con type especial `AUTH_DENIED` (requiere bump del enum).

Hasta que esto esté implementado, los endpoints REST **no se exponen al internet público** — solo dentro de la VPN o tras un proxy con auth a nivel de plataforma.

---

## Limitaciones conocidas v0.1

Documentadas explícitamente para evitar que el agente constructor las "arregle" como si fueran bugs. Cada una requiere un cambio de protocolo (bump a v0.2).

- **Cantidades indivisibles por oferta**: un único ACCEPT cierra la oferta entera, aunque la propuesta sea por una cantidad parcial. Quantities parciales requieren un mecanismo de reserva/lote.
- **Sin escrow**: el protocolo registra el acuerdo, no mueve dinero. La integración con rails de pago (AP2, Visa) es Fase 2+.
- **Sin geolocalización**: `location` es texto libre; el matching es ILIKE substring. `location_radius_km` y `location_center` están en el schema DISCOVER pero no se evalúan.
- **Reputación trivial**: `agent_reputation` cuenta deals; no incorpora disputas, ni ratings, ni recencia ponderada.
- **Sin contrapropuestas encadenadas**: el protocolo permite COUNTER → COUNTER → ..., pero el motor de matching no las visualiza como un hilo. Los agentes deben rastrear el `proposal_id` original.
- **Redis como caché, no como verdad**: si Redis está caído, las propuestas siguen funcionando vía Postgres pero más lentas. Si Postgres está caído, el sistema rechaza todo.

---

## Orden de construcción por prioridad

Construye en este orden exacto. No avanzar al siguiente paso sin que el anterior tenga tests pasando.

```
PASO 1 — Fundamentos (Fase 0)
  [ ] db/schema.sql completo con todos los índices
  [ ] server/zocux_server.py con las 6 herramientas MCP
  [ ] tests/test_protocol.py con casos básicos
  [ ] README.md con tutorial de instalación

PASO 2 — Motor de matching (Fase 1a)
  [ ] server/matching_engine.py
      - Match por producto (fuzzy)
      - Match por precio (rango)
      - Match por ubicación (texto por ahora, geo después)
      - Ranking de resultados por relevancia
  [ ] tests/test_matching.py

PASO 3 — Agente de referencia (Fase 1b)
  [ ] examples/seller_agent.py
      - Lee inventario desde CSV
      - Anuncia ofertas automáticamente
      - Evalúa propuestas según reglas configurables
      - Acepta o rechaza con razonamiento
  [ ] examples/buyer_agent.py
      - Descubre ofertas según criterios
      - Propone deals con lógica de negociación
      - Gestiona contrapropuestas
  [ ] examples/negotiation_demo.py
      - Demo completa vendedor↔comprador en una sola ejecución

PASO 4 — SDK cliente (Fase 2)
  [ ] sdk/python/zocux_client.py
      - Wrapper sobre las herramientas MCP
      - Instalable via pip
  [ ] sdk/javascript/index.js
      - Wrapper para Node.js
      - Instalable via npm

PASO 5 — API REST pública (Fase 2)
  [ ] Endpoints REST además del servidor MCP
      - GET  /offers          → active offers
      - POST /offers          → announce
      - POST /proposals       → propose
      - PUT  /proposals/{id}  → accept/reject
      - GET  /deals           → closed deals (public stats)
      - GET  /stats           → market statistics
```

---

## Modelo de negocio (para contexto del agente)

Schedule validada contra comparables (Mirakl, SAP Ariba, Abastores, OpenSea, AP2, etc.) en mayo 2026. Source of truth en runtime: `fee_schedule.json` en raíz del repo, expuesto vía la tool `get_fee_schedule`.

### Comisión transaccional (Fase 2+)

Buyer-pays. Calculada y registrada por el server en el momento del ACCEPT — irreversible. El comprador la ve antes de aceptar términos.

| Tramo (volumen €) | Rate | Cap |
|---|---|---|
| < 1.000 | 1,5% | — |
| 1.000–10.000 | 1,0% | — |
| 10.000–100.000 | 0,5% | — |
| > 100.000 | 0,4% | **5.000 €/deal** |

Notas de diseño:
- **Buyer-only**: vendedores commodity no absorben fees con márgenes finos; cobrar al ANNOUNCE hundiría la densidad del dataset (activo estratégico).
- **El cap de 5.000 €/deal** en el top tier va explícito en `fee_schedule.json` como `max_fee_eur`, versionado, no como excepción ad-hoc.
- **Fase 0-1**: todo gratuito. La schedule queda registrada en cada deal (con `rate=0`) para que la migración a cobrar sea un cambio de configuración, no de schema.
- **No competimos en la capa de pagos**: AP2, Stripe ACP y x402 se van a 0 €. Zocux cobra por matching, negociación, dispute resolution y dataset — estrictamente *encima* de los rails.

### Servicios premium SaaS

| Tier | €/mes | Para |
|---|---|---|
| Free | 0 | Acceso protocolo + manifest + transcripts propios últimos 30 días |
| Operator | 99 | Analytics propias + export histórico propio completo |
| Trader | 499 | Operator + cuota API 10× + datos agregados anonimizados de mercado |
| Enterprise | 1.499 | Trader + SLA 99,9% + onboarding directo + dataset agregado completo (anonimizado) |

El tier Enterprise es la métrica que mira un acquirer (Mirakl, SAP, AWS) en DD: ARR de calidad, contratos plurianuales, dataset diferenciado.

El activo más valioso no es el código — es el dataset de negociaciones reales. Cada transacción registrada con su payload completo es propiedad intelectual de Zocux.

---

## Estrategia de adquisición (contexto estratégico)

El objetivo no es crecer indefinidamente de forma independiente. Es ser adquirible en 18-24 meses por:

1. **Mirakl / SAP Ariba / Coupa** — plataformas B2B que necesitan capa de agentes
2. **AWS / Google Cloud** — necesitan casos de uso verticales reales de agentic commerce
3. **Cooperativas o traders grandes** — Louis Dreyfus, Agrimp, operadores españoles

Lo que hace a Zocux adquirible: protocolo documentado públicamente, dataset de transacciones reales, arquitectura integrable en cualquier stack empresarial en menos de 3 meses.

---

## Issues prioritarias para empezar

Cuando arranques, crea estas issues en GitHub en este orden:

1. `[INFRA] Setup PostgreSQL schema y migraciones`
2. `[CORE] Implementar servidor MCP con herramientas ANNOUNCE y DISCOVER`
3. `[CORE] Implementar herramientas PROPOSE y ACCEPT`
4. `[TEST] Tests e2e de negociación completa vendedor↔comprador`
5. `[DOCS] Tutorial de instalación en 15 minutos`
6. `[EXAMPLE] Agente vendedor de referencia con CSV de inventario`
7. `[EXAMPLE] Agente comprador de referencia con criterios configurables`
8. `[INFRA] Deploy en Contabo con URL pública`

---

*Zocux Protocol v0.1 — MIT License*
*Repositorio: github.com/jnnan/Zocux*
