# transcripts/

Canonical sequences. Each `.jsonl` file is a self-contained negotiation an agent can ingest as an example. Optimized for LLM consumption, not human reading.

## File format

JSONL. The first line is metadata; the rest are ordered steps.

```
{"_meta": {"name": "<slug>", "purpose": "<one-line>", "tags": ["..."]}}
{"step": 1, "actor": "<agent_id>", "tool": "<mcp_tool>", "args": {...}, "result": {...}}
{"step": 2, ...}
```

## Placeholders

Server-generated identifiers appear in results as `$offer_id`, `$proposal_id`, `$deal_id`. The first occurrence in a `result` BINDS the placeholder; later occurrences in `args` REFERENCE the bound value. Example:

```
{"step": 1, "tool": "announce_offer", "args": {...}, "result": {"status": "announced", "offer_id": "$offer_id"}}
{"step": 2, "tool": "propose_deal",   "args": {"offer_id": "$offer_id", ...}, "result": {"status": "proposed", "proposal_id": "$proposal_id"}}
```

Timestamps and timestamp-derived fields use `$now+<n>h` to indicate "now plus N hours" relative to replay time.

## Result matching

The `result` object is a SUBSET match: every key listed must equal what the server returned. Keys NOT listed are not asserted. `$placeholder` values are bound on first occurrence and asserted equal on later occurrences.

## Catalogue

| File                          | Purpose                                                          |
|-------------------------------|------------------------------------------------------------------|
| `01_happy_close.jsonl`        | Full trade: announce → discover → propose → accept → stats.      |
| `02_buyer_rejects.jsonl`      | Announce → propose → buyer rejects own proposal; offer stays active. |
| `03_idempotent_retry.jsonl`   | Same announce twice with same `idempotency_key` → duplicate.     |
| `04_auth_denied_self_propose.jsonl` | Seller tries to propose against own offer → AUTH_DENIED.   |
| `05_seller_counters.jsonl`    | Buyer proposes; seller counters; seller then accepts original.   |
