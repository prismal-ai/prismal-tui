# CLAUDE.md — prismal-tui

Guidance for Claude Code (claude.ai/code) working in this repository.

## What this repo is

`prismal-tui` is the **terminal front-end** for the `prismal` ecosystem: a
[Textual](https://textual.textualize.io/)-based interactive application a
developer runs locally to talk to a running
[`prismal-server`](https://github.com/prismal-ai/prismal-server),
exclusively through [`prismal-sdk`](https://github.com/prismal-ai/prismal-sdk)
(`AsyncPrismalClient`). It is the sibling of `prismal-webchat` (browser BFF)
and `prismal-chatbot` (Slack/Discord bots) one surface further in: same
upstream contract, a terminal instead of a browser tab or a chat platform
message.

The full design lives in
[`specs/tui-bootstrap/`](./specs/tui-bootstrap/) (`PLAN.md` ·
`ARCHITECTURE.md` · `SPEC.md` · `TASKS.md`). Read those before implementing.

## The one hard rule — a face, not a brain

> **intelligence → engine (`prismal`); transport → `prismal-sdk`; serving →
> `prismal-server`; rendering a conversation in a terminal, local
> conversation↔thread mapping, and keybindings → this repo. Nothing else
> lives here.**

This repo imports **nothing** from `prismal` (engine) or `prismal_server`
(host), and never opens its own HTTP connection to the host (no direct
`httpx`). All upstream traffic goes through `prismal_sdk`'s typed client.
`textual`, `platformdirs` and `pydantic-settings` (already an SDK dependency,
declared because `settings.py` imports it) are the only other runtime
dependencies beyond the SDK. Adding agent/RAG/tool logic, prompt construction, SSE parsing,
wire error-code mapping, or a second copy of conversation history (the
engine's checkpointer already owns message content — this repo only
remembers *which* local conversation maps to *which* `thread_id`) is a bug.

| Concern | Owner |
|---|---|
| Agent reasoning, RAG, tools, security layers | `prismal` (engine, server-side) |
| Wire contract (REST/SSE, errors, auth) | `prismal-server` (`SPEC-RHB-*`) |
| Typed transport, SSE parsing, exceptions | `prismal-sdk` (`SPEC-CSB-*`) |
| Terminal rendering, keybindings, local conversation↔thread mapping | **this repo** (`SPEC-TUI-*`) |

## Review checklist (enforce on every PR)

- [ ] No import of `prismal` or `prismal_server`, and no direct `httpx` use
      against `prismal-server`, anywhere in `prismal_tui/` — the AST
      boundary-guard test must stay green (`SPEC-TUI-APP-002`).
- [ ] `widgets/*` never imports `prismal_sdk` transport internals
      (`httpx`, `_sse`, `_transport`) — only `ConversationSession` and the
      SDK's typed models (`SPEC-TUI-APP-005`).
- [ ] User-provided text reaches `send_message(content=…)` **unmodified** —
      no templating, prefixing, or prompt building anywhere
      (`SPEC-TUI-SES-004`). Sole exception: the `//` escape drops exactly
      its first `/` (`SPEC-TUI-UX-006`).
- [ ] `ConversationStore.put()` happens **before** the first
      `send_message()` call for a new conversation — never after, or a
      crash mid-turn loses the mapping (`SPEC-TUI-STO-001`, `ADR-002`).
- [ ] The bearer token (`PrismalTuiSettings.token`, `SecretStr`) never
      appears in rendered widget text, the `ConversationStore` file, a log
      line, or an exception message (`SPEC-TUI-AUT-002`).
- [ ] SDK exceptions are caught only at the `ConversationSession.stream()`
      call site in `app.py` and rendered as friendly text via `errors.py`;
      no codes, server messages, or tracebacks reach the transcript or
      status bar (`SPEC-TUI-ERR-001/002`).
- [ ] No auto-retry of a turn — retry is the user sending another message
      on the same, already-resolved `thread_id` (`SPEC-TUI-ERR-004`).
- [ ] Cancellation = breaking out of the event iterator on the cancel key
      binding (SDK closes the stream, host cancels the run) — never an
      invented cancel RPC, and never a blind per-turn timeout in v0.1
      (`SPEC-TUI-UX-002`, `ADR-004`).
- [ ] A mid-stream error or cancellation preserves whatever partial text
      was already rendered — never blank or delete a partially-rendered
      answer (`SPEC-TUI-ERR-003`).
- [ ] Render coalescing stays frame-based (at most one pending redraw),
      never a fixed time/char-interval throttle copied from
      `prismal-chatbot` — there is no external rate limit on a local
      terminal (`SPEC-TUI-REN-001`, `ADR-003`).
- [ ] The Textual event loop is never blocked by a synchronous call; the
      app stays responsive while a turn streams (`SPEC-TUI-NFR-004`).
- [ ] New behaviour is **test-first (TDD)**: failing test → minimal code →
      green. Session-layer unit tests use `FakeAsyncPrismalClient` (no
      Textual event loop); widget/app tests use Textual's `Pilot` harness
      (also offline); anything touching a live server goes in the opt-in
      `tests/contract/` suite (`SPEC-TUI-NFR-001`).
- [ ] Dep pins stay `prismal-sdk>=0.2,<1` (DELTA-2026-10; written
      `>=0.2.0.dev0` while 0.2 is unpublished and resolved from
      `../prismal-sdk`) plus a tested `textual` / `platformdirs` minor;
      bumps are deliberate PRs (`SPEC-TUI-NFR-005`).
- [ ] `ruff check .` and `mypy prismal_tui` are clean.
- [ ] New capability traces to a `SPEC-TUI-*` requirement — if the wire
      contract must change, that is negotiated in `prismal-server` /
      `prismal-sdk` first, never invented here.

## Common commands

```bash
uv sync --extra dev                  # needs ../prismal-sdk checked out (SDK 0.2 not on PyPI yet)
# or: uv pip install -e ".[dev]"
prismal-tui                          # launch the Textual app (or: python -m prismal_tui)
uv run pytest                        # unit + ui (offline, fake SDK client + Textual Pilot)
uv run pytest -m contract            # opt-in: ConversationSession against a running prismal-server
uv run ruff check . && uv run ruff format --check .
uv run mypy prismal_tui
```

Local end-to-end: start a `prismal-server`
(`uvicorn prismal_server.app:app`), point this repo at it via
`PRISMAL_TUI_SERVER_URL` (defaults to `http://localhost:8000`), and run
`prismal-tui`.

## Boundary examples

- Need the answer streamed to the transcript? **Already have it** —
  iterate `client.send_message(...)` inside `ConversationSession.stream()`
  and feed deltas to `TranscriptView`; never parse SSE yourself, never
  poll for updates.
- Need conversation history after a restart? **No TUI-side history DB** —
  message history lives in the engine's checkpointer under the resolved
  `thread_id`; this repo only persists *which* `thread_id` a local,
  user-named conversation maps to (`ConversationStore`), never the
  messages themselves.
- Want to improve answers with a system prompt or RAG tweak? **No** — that
  is engine configuration, server-side. This repo passes user text through
  unmodified.
- Need a "stop generating" affordance? **Already have it** — the cancel
  key binding (`Esc` default) breaks the stream the same way
  `prismal-webchat`'s stop button does; do not add a background timeout on
  top of it in v0.1 (`ADR-004`; revisit only as `TUI-FUTURE-06` if a real
  "walked away from the terminal" scenario shows up).
- Want to throttle fast token streams like `prismal-chatbot` does? **No**
  — that throttle exists because Slack/Discord rate-limit edits; a local
  terminal has no such limit. Use frame-based redraw coalescing instead
  (`ADR-003`).
- Want to add a config file for themes/keybindings? **Not in v0.1** — all
  configuration is `PRISMAL_TUI_*` env vars, matching every sibling
  front-end; a config file is `TUI-FUTURE-02`.
- Want to publish to PyPI so people can `uvx prismal-tui`? **Not yet** —
  v0.1 installs from source like `prismal-webchat` and `prismal-chatbot`;
  publication is `TUI-FUTURE-01`.
