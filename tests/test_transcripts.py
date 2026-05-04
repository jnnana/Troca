"""Replay every transcripts/*.jsonl file against the live server.

Each transcript is a canonical sequence with placeholder bindings ($offer_id,
$proposal_id, ...). On the first occurrence in a `result` the placeholder is
bound to whatever the server returned; on later occurrences in `args` it is
substituted, and on later occurrences in `result` it is asserted equal.

Result matching is SUBSET: only keys listed in the transcript are asserted;
extra keys returned by the server are tolerated.

If you add a transcript, drop it in transcripts/ and it will be picked up.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server import zocux_server as z

TRANSCRIPTS = Path(__file__).resolve().parent.parent / "transcripts"

_PLACEHOLDER = re.compile(r"^\$([a-z_][a-z0-9_]*)$")
_NOW_OFFSET = re.compile(r"^\$now\+(\d+)h$")


def _parse(result):
    return json.loads(result[0].text)


def _resolve(value, bindings: dict):
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value)
        if m and m.group(1) in bindings:
            return bindings[m.group(1)]
        m2 = _NOW_OFFSET.match(value)
        if m2:
            return (datetime.now(timezone.utc) + timedelta(hours=int(m2.group(1)))).isoformat()
        return value
    if isinstance(value, list):
        return [_resolve(v, bindings) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, bindings) for k, v in value.items()}
    return value


def _match(actual, expected, bindings: dict, path: str = "$"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__}: {actual!r}"
        for k, v in expected.items():
            assert k in actual, f"{path}.{k}: missing from server result; got keys={list(actual.keys())}"
            _match(actual[k], v, bindings, f"{path}.{k}")
        return
    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__}"
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != expected {len(expected)}"
        for i, (a, e) in enumerate(zip(actual, expected)):
            _match(a, e, bindings, f"{path}[{i}]")
        return
    if isinstance(expected, str):
        m = _PLACEHOLDER.match(expected)
        if m:
            key = m.group(1)
            if key in bindings:
                assert actual == bindings[key], (
                    f"{path}: placeholder ${key} previously bound to {bindings[key]!r}, "
                    f"got {actual!r}"
                )
            else:
                bindings[key] = actual
            return
    assert actual == expected, f"{path}: expected {expected!r}, got {actual!r}"


def _load(path: Path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows and "_meta" in rows[0], f"{path}: first line must contain `_meta`"
    return rows[0]["_meta"], rows[1:]


_TRANSCRIPT_FILES = sorted(TRANSCRIPTS.glob("*.jsonl"))


@pytest.mark.parametrize("path", _TRANSCRIPT_FILES, ids=lambda p: p.name)
async def test_transcript_replays(path: Path):
    meta, steps = _load(path)
    bindings: dict = {}
    for step in steps:
        args = _resolve(step["args"], bindings)
        result = _parse(await z.call_tool(step["tool"], args))
        _match(result, step["result"], bindings, path=f"{meta['name']}.step{step['step']}")
