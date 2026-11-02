"""Wire payloads pinned from the sibling specs (TUI-D-01).

Sources (verified 2026-11-02 against the checked-out repos):

- ``FAKE_USAGE``: ``prismal-server/docs/fake-mode.md`` (SPEC-RH2-FAK-002) — the
  usage every fake-LLM turn ends with.
- ``USAGE_REPORT``: ``prismal-server`` SPEC (host-v0.2) §4 ``GET /v1/usage``
  example, with the elided per-turn usage filled in.
- ``BUDGET_402``: SPEC-RH2 §11 — 402 body before a turn starts.
- ``BUDGET_STREAM_ERROR``: SPEC-RH2 §11 — terminal ``error`` event mid-stream
  carrying the partial usage (mapped by SPEC-CS2-ERR-002).
"""

from __future__ import annotations

from typing import Any

FAKE_USAGE: dict[str, Any] = {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "reasoning_tokens": 0,
    "total_tokens": 15,
    "calls": 1,
    "cost_usd": 0.0,
    "cost_source": "none",
    "estimated": True,
    "served_model": "fake/echo",
    "gateway": None,
}

GATEWAY_USAGE: dict[str, Any] = {  # usage_wire.json example (priced by gateway)
    "prompt_tokens": 1200,
    "completion_tokens": 300,
    "cache_read_tokens": 800,
    "cache_write_tokens": 0,
    "reasoning_tokens": 40,
    "total_tokens": 1500,
    "calls": 2,
    "cost_usd": 0.004321,
    "cost_source": "gateway",
    "estimated": False,
    "served_model": "anthropic/claude-sonnet-4.5",
    "gateway": "openrouter",
}

USAGE_REPORT: dict[str, Any] = {
    "org_id": "acme",
    "thread_id": None,
    "since": "2026-10-03T12:00:00Z",
    "until": "2026-10-04T12:00:00Z",
    "totals": {
        "prompt_tokens": 52000,
        "completion_tokens": 9100,
        "cache_read_tokens": 39000,
        "cache_write_tokens": 4000,
        "reasoning_tokens": 1200,
        "total_tokens": 61100,
        "calls": 140,
        "cost_usd": 0.412345,
        "cost_source": "mixed",
        "estimated": True,
        "served_model": None,
        "gateway": None,
    },
    "cache_hit_ratio": 0.75,
    "by_model": [
        {
            "prompt_tokens": 40000,
            "completion_tokens": 7000,
            "cache_read_tokens": 32000,
            "cache_write_tokens": 3000,
            "reasoning_tokens": 1200,
            "total_tokens": 47000,
            "calls": 90,
            "cost_usd": 0.39,
            "cost_source": "gateway",
            "estimated": False,
            "served_model": "anthropic/claude-sonnet-4.5",
            "gateway": "openrouter",
        }
    ],
    "turns": [
        {
            "thread_id": "t-42",
            "turn_id": "01JTURN",
            "finished_at": "2026-10-04T11:59:58Z",
            "finish_reason": "stop",
            "usage": GATEWAY_USAGE,
        }
    ],
    "next_cursor": None,
}

BUDGET_402: dict[str, Any] = {
    "error": {
        "code": "budget_exceeded",
        "message": "tenant acme hard cap reached",
        "scope": "tenant",
        "limit": {"tokens": 2000000, "cost_usd": 50.0},
        "consumed": {"tokens": 2000100, "cost_usd": 50.01},
    }
}

BUDGET_STREAM_ERROR: dict[str, Any] = {
    "code": "budget_exceeded",
    "message": "turn budget exhausted",
    "usage": {**FAKE_USAGE, "completion_tokens": 3, "total_tokens": 13},
}
