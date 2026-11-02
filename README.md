# prismal-tui

Terminal UI for the [prismal](https://github.com/prismal-ai/prismal)
ecosystem — an interactive [Textual](https://textual.textualize.io/)
application you run locally to talk to a running
[`prismal-server`](https://github.com/prismal-ai/prismal-server),
exclusively through [`prismal-sdk`](https://github.com/prismal-ai/prismal-sdk)
(`AsyncPrismalClient`).

There is no browser and no chat platform here: keystrokes go straight into
a `ConversationSession` that resolves or creates one engine `thread_id` per
locally-named conversation, persists that mapping in a local SQLite
`ConversationStore` (so restarting the app never forks an ongoing
conversation), streams the reply through `prismal-sdk`, and renders it as
Markdown in a scrollable transcript — with a single key press (`Esc` by
default) to cancel mid-turn.

> **Status: pre-release (`0.1.0.dev0`).** Phases TUI-00…04 are implemented
> (see [`specs/tui-bootstrap/TASKS.md`](./specs/tui-bootstrap/TASKS.md)); the
> usage readout (Phase D, `DELTA-2026-10`) lands before the `v0.1.0` tag.

## Ecosystem position

```
developer's terminal ── keyboard/ANSI ──▶ prismal-tui (this repo)
                                               │  prismal_sdk (HTTP + SSE)
                                               ▼
                                          prismal-server ──▶ prismal (engine)
```

| Repo | Role | Status |
|---|---|---|
| [`prismal`](https://github.com/prismal-ai/prismal) | Engine (LangGraph supervisor, 29 routes, RAG, security) | v3.10.1 — 21/21 specs |
| [`prismal-server`](https://github.com/prismal-ai/prismal-server) | FastAPI host (REST + SSE + A2A) | v0.1 complete |
| [`prismal-sdk`](https://github.com/prismal-ai/prismal-sdk) | Typed Python client (sync + async) | bootstrap complete |
| [`prismal-webchat`](https://github.com/prismal-ai/prismal-webchat) | Embeddable browser chat widget | SDD seed |
| [`prismal-chatbot`](https://github.com/prismal-ai/prismal-chatbot) | External bots — Slack, Discord | SDD seed |
| `prismal-tui` | Terminal UI (this repo) | **pre-release** |

## What v0.1 delivers

A single-process Textual app: a scrollable, Markdown-rendered transcript
that streams tokens as the engine produces them, visible tool-call
activity, a sidebar to create/switch/rename/delete named local
conversations (each backed by its own durable engine thread), a small
slash-command set (`/new`, `/switch`, `/rename`, `/delete`, `/cancel`,
`/quit`, `/help`), immediate keyboard cancellation of an in-flight turn,
and friendly error messages on failure. See `specs/tui-bootstrap/PLAN.md`
§5 for the full in/out-of-scope list.

## Quickstart (dev)

Requires Python 3.13, [`uv`](https://docs.astral.sh/uv/), a checkout of
[`prismal-sdk`](https://github.com/prismal-ai/prismal-sdk) next to this repo
(`../prismal-sdk` — the SDK 0.2 line isn't on PyPI yet) and a running
`prismal-server` (defaults to `http://localhost:8000`).

```bash
uv sync --extra dev

export PRISMAL_TUI_SERVER_URL="http://localhost:8000"
export PRISMAL_TUI_TOKEN="…"           # service credential, optional locally

prismal-tui
# or: python -m prismal_tui
```

Inside the app: type a message and press Enter to send, `Esc` to cancel a
streaming reply, `/new <name>` to start a new conversation, `/help` for the
full key-binding and command list.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PRISMAL_TUI_SERVER_URL` | `http://localhost:8000` | Target `prismal-server` |
| `PRISMAL_TUI_TOKEN` | — | Bearer credential (never rendered or persisted) |
| `PRISMAL_TUI_ORG_ID` | — | Tenant for all TUI traffic (`X-Org-Id`) |
| `PRISMAL_TUI_STORE_PATH` | `platformdirs` user-data dir | Local `ConversationStore` SQLite file |
| `PRISMAL_TUI_CANCEL_KEY` | `escape` | Key binding that cancels an in-flight turn |
| `PRISMAL_TUI_LOG_LEVEL` | `INFO` | Local log file verbosity |

Full reference: [`docs/configuration.md`](./docs/configuration.md).

## Development

```bash
uv run pytest                       # unit + ui suite — offline, fake SDK client + Textual Pilot
uv run pytest -m contract           # opt-in — against a running prismal-server
                                    # (PRISMAL_TUI_SERVER_URL; fake-LLM mode recommended)
uv run ruff check . && uv run mypy prismal_tui
```

Boundary rules (no `prismal`/`prismal_server` imports, no direct HTTP to
the host, no secret ever rendered, logged, or persisted) are enforced by
tests — see [`CLAUDE.md`](./CLAUDE.md) for the review checklist. Before a
release, run [`docs/manual-verification.md`](./docs/manual-verification.md)
against a real host.

## License

[MIT](./LICENSE)
