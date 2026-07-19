# prismal-tui — Terminal UI (TUI Bootstrap)

## Strategic Plan / Product Requirements Document (PLAN)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo |
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-19 |
| **Phase** | TUI (Terminal UI Bootstrap) |
| **Repository** | `prismal-ai/prismal-tui` (this repo) |
| **Upstream contract** | `prismal-sdk >= 0.1, < 1` (typed client over the wire contract fixed by `prismal-server/specs/reference-host-bootstrap/SPEC.md`) |
| **Reviewers** | Tech Lead, AI Architect |
| **Priority** | P2 (front-end front-end, ships alongside `prismal-webchat` / `prismal-chatbot`) |
| **Related** | `prismal-ai/prismal` (engine, v3.10.1, 21/21 specs, 29 rutas de agentes); `prismal-ai/prismal-server` (host, v0.1 complete); `prismal-ai/prismal-sdk` (client, bootstrap complete); `prismal-ai/prismal-webchat` and `prismal-ai/prismal-chatbot` (sibling front-ends, SDD seeds — share the "face, not a brain" pattern); sibling `prismal-dashboard` (`PENDIENTE`) |

---

## 1. Executive Summary

`prismal` (the engine) is a pure LangGraph library — Prism-inspired
multi-agent orchestration, 29 agent routes, 7 RAG engines, 5-layer
security, published on PyPI as `prismal-ai` (v3.10.1, 21/21 specs
implemented, 0 pending in the engine). `prismal-server` put it on the
network with a fixed wire contract (REST + SSE chat, standard A2A v0.3.x
JSON-RPC). `prismal-sdk` wrapped that contract in a typed Python client
(`PrismalClient` / `AsyncPrismalClient`) so every front-end repo talks to
the engine the same narrow way. `prismal-webchat` proved the pattern for a
browser-embedded widget; `prismal-chatbot` proved it for external chat
platforms (Slack/Discord).

`prismal-tui` is the ecosystem's **terminal front-end**: a
[Textual](https://textual.textualize.io/)-based interactive application
that a developer runs locally (`prismal-tui` on the command line) to talk
to a running `prismal-server` — exclusively through `prismal-sdk` — without
a browser, without a chat platform, and without touching the engine or the
wire contract directly. Unlike the webchat (one thread per browser tab) or
the chatbot (one thread per external conversation, potentially many users),
the TUI is single-user and local: it renders a scrollable, Markdown-capable
transcript that streams tokens as the engine produces them, lets the user
switch between several **named local conversations** (each backed by one
engine `thread_id`), and persists that mapping across restarts so history
is never silently forked.

This PLAN scopes **v0.1**: a single-process Textual application, a
`ConversationSession` that owns the `prismal-sdk` turn lifecycle
(mirroring `prismal-chatbot`'s `ConversationBridge`, without the
platform-adapter layer), a local `ConversationStore` (SQLite) mapping
user-named conversations to `thread_id`s, direct token-streamed rendering
with keyboard-driven cancellation, and a small set of slash commands.
`ARCHITECTURE.md`, `SPEC.md`, and `TASKS.md` in this folder refine it into
a buildable, test-first plan.

---

## 2. Context and Problem

- Per the `prismal-ai` ecosystem presentation (2026-07-07, v3.10.1): 8
  repositories. `prismal` and `prisma-notebooks` are `LISTO`; `prismal-server`
  v0.1 is complete; `prismal-sdk` bootstrap is complete. `prismal-tui`,
  `prismal-webchat`, `prismal-dashboard`, and `prismal-chatbot` are
  `PENDIENTE`. The ecosystem architecture diagram places `prismal-tui` at
  the same layer as `prismal-webchat`, `prismal-dashboard`, and
  `prismal-chatbot`, all four feeding into a single `prismal-sdk` box
  ("cliente REST / WS / SSE") that alone talks to `prismal-server`. The
  "Estado del ecosistema" slide labels `prismal-tui` explicitly:
  **"Terminal UI."** The "Próximos pasos" slide groups it with the other
  three under item 3, "Clientes front-end."
- `prismal-webchat` and `prismal-chatbot` already established the reusable
  shape for a front-end in this ecosystem: a thin client that owns *no*
  agent/business logic, talks to `prismal-server` only via `prismal_sdk`,
  and translates the SDK's typed streaming events into a surface-specific
  rendering. This repo reuses that shape but the surface is a **terminal**,
  not a browser or a chat platform: no HTML/CSS/embedding, no Socket
  Mode/Gateway, no platform rate limits — but a comparable "one
  conversation → one `thread_id`" mapping and the same
  streaming-turn → typed-events → UI-update pipeline (§4.1,
  `ARCHITECTURE.md`).
- Three problems specific to a terminal surface that neither sibling's
  design solves outright:
  1. **No browser tab, no external platform message — just a process the
     user starts and stops.** History must survive the user closing the
     terminal and reopening `prismal-tui` later, the same durability
     problem `prismal-chatbot`'s `ThreadStore` solves for a Slack channel,
     but here the "conversation key" is something the *user* names and
     picks from a list, not a platform-derived key.
  2. **No rate limit, but a real terminal render budget.** Unlike Slack/
     Discord (`prismal-chatbot`'s throttle exists because the *platform*
     rate-limits edits), a local terminal can render every token — the
     only constraint is not flooding the event loop with more redraws than
     the terminal can usefully show per frame. This is a performance
     concern, not a correctness one, and is handled differently (§4.2,
     `ARCHITECTURE.md`).
  3. **A human is always at the keyboard.** Unlike the chatbot (no "stop"
     affordance, hence a hard per-turn timeout), the TUI can offer the same
     immediate cancel affordance the webchat's stop button gives, via a
     single key binding — no blind timeout needed for the common case.
- Without `prismal-tui`, the only way to interact with a running
  `prismal-server` from a terminal is `curl` against the raw SSE contract
  or a throwaway script — nothing a developer would reach for daily, and
  nothing that exercises `prismal-sdk`'s ergonomics the way a real
  application does.

---

## 3. Target Users

- **`prismal` engine developers and operators** who want a fast, local,
  keyboard-driven way to exercise a running `prismal-server` without
  standing up a browser or a chat platform — the natural "first client"
  for anyone iterating on the engine or the host.
- **Developers evaluating or demoing `prismal`** who want a polished,
  installable CLI experience (`prismal-tui`) rather than raw `curl`/SSE.
- **`prismal-dashboard` maintainers** — the local conversation↔`thread_id`
  persistence pattern and the direct-streaming-render pattern established
  here are reusable wherever a front-end is single-user and long-lived.
- **The `prismal-ai` org itself** — a third reference front-end proving the
  `prismal-sdk` contract generalizes beyond a browser BFF and a platform
  bot to a plain terminal process.

---

## 4. Goals and Success Metrics

| Goal | Metric | Target |
|---|---|---|
| Reach the engine from a terminal | Running `prismal-tui` and typing a message produces a streamed, rendered reply | End-to-end against a local `prismal-server`, no manual `curl` |
| Multiple durable local conversations | The user can create, list, switch, rename, and delete named conversations; each keeps its own engine thread | `ConversationStore` round-trip test: same conversation name → same `thread_id` after app restart |
| Immediate, reliable cancellation | Pressing the cancel key mid-stream stops the turn without corrupting the transcript | Unit test: cancel mid-stream leaves the partial answer intact and the app responsive |
| Zero wire-contract code | No SSE parsing, error-code mapping, or JSON-RPC framing in this repo | All transport goes through `prismal_sdk`; enforced by an AST import/usage-guard test |
| Offline-testable | Unit and UI suites run with no live server | `FakeAsyncPrismalClient` + Textual's `Pilot` harness; opt-in `contract` suite hits a real host |
| Installable via uv | `uv pip install -e ".[dev]"` + one console-script entrypoint (`prismal-tui`) launches the app | Process starts, lints, type-checks, tests green |
| Pleasant terminal ergonomics | Markdown rendering (code blocks, lists), visible tool-call activity, responsive redraw under fast token streams | Manual verification checklist + a scripted-fast-stream UI test |

---

## 5. Scope

### In scope (v0.1 — the minimal viable terminal client)

- `prismal_tui` package: a [Textual](https://textual.textualize.io/)
  application (`PrismalTuiApp`) with a scrollable transcript, a sidebar
  listing local conversations, a composer input, and a status bar.
- `ConversationSession`: owns the entire `prismal-sdk` turn lifecycle
  (thread resolution, streaming consumption, cancellation, error mapping)
  independent of the widget layer — the TUI analogue of
  `prismal-chatbot`'s `ConversationBridge`, minus the platform-adapter
  concept.
- `ConversationStore`: local SQLite persistence mapping a user-chosen
  conversation name to an engine `thread_id`, so conversations survive an
  app restart; list/create/rename/delete operations.
- Direct token-streamed rendering: `TokenEvent` deltas append straight to
  the transcript (Markdown-rendered on flush), `ToolCallEvent`s render as a
  distinct low-emphasis activity line, `DoneEvent` finalizes the turn;
  light render-coalescing bounds terminal redraw frequency for very fast
  streams (a performance guard, not a rate-limit throttle — §4.2,
  `ARCHITECTURE.md`).
- Keyboard-driven cancellation: a dedicated key binding (`Esc` by default)
  breaks the stream mid-turn, mirroring `prismal-webchat`'s stop button;
  no blind per-turn timeout is required in v0.1 because a human is always
  present.
- A small slash-command set typed into the composer: `/new`, `/switch`,
  `/rename`, `/delete`, `/cancel`, `/quit`, `/help`.
- Error UX: typed SDK exceptions mapped to a friendly status-bar/toast
  message; the transcript preserves whatever partial answer already
  streamed.
- Configuration via `PRISMAL_TUI_` environment variables (server
  connection, credential, tenancy) — no secret is ever rendered on screen
  or written to the `ConversationStore`.
- Unit test suite offline (fake SDK client, tmp `ConversationStore`); UI
  tests via Textual's `Pilot` test harness (also offline); opt-in
  `contract` suite against a running `prismal-server`.
- `uv`-based dev foundation: `pyproject.toml` with a `prismal-tui` console
  script, `ruff`, `mypy`, `pytest` (+ `pytest-asyncio`), CI workflow.

### Out of scope (deferred)

- **PyPI publication / `uvx prismal-tui`** — v0.1 targets install-from-
  source (`uv pip install -e ".[dev]"`); a published package with a
  zero-install `uvx` entrypoint is TUI-FUTURE-01, once the ecosystem's
  front-ends stabilize (the presentation's "Próximos pasos" only lists
  `prismal-server`/`prismal-sdk` publication as immediate next steps).
- **A local config file** (TOML for theme/keybinding overrides) — v0.1
  configures everything via `PRISMAL_TUI_*` environment variables, matching
  every sibling front-end; a config file is TUI-FUTURE-02.
- **Multiple simultaneous connections / multi-server switching** — v0.1
  targets one `prismal-server` per running instance, configured at
  startup; switching servers without restarting is TUI-FUTURE-03.
- **File/media attachments** — the engine's multimodal layer is opt-in and
  the chat contract carries text `content` only in v0.1, matching
  `prismal-webchat`'s and `prismal-chatbot`'s same deferral
  (TUI-FUTURE-04).
- **A2A surface** — like the webchat and the chatbot, this repo is a chat
  consumer; it does not expose or consume A2A. Generic A2A peers already
  talk to `prismal-server` directly.
- **Per-conversation export/search** (exporting a transcript to a file,
  full-text search across local conversations) — real feature, deferred to
  TUI-FUTURE-05.
- **Mouse-driven interaction beyond Textual's defaults** — v0.1 is
  keyboard-first; Textual's built-in mouse support (scrolling, clicking a
  sidebar item) is accepted as-is, no custom mouse UX is designed.

---

## 6. Functional Requirements (summary; refined in `SPEC.md`)

| ID | Requirement | Priority |
|---|---|---|
| RF-TUI-001 | A `ConversationSession` owning the `prismal-sdk` turn lifecycle (thread resolution, streaming consumption, cancellation, error mapping), independent of the widget layer | `MUST` |
| RF-TUI-002 | `ConversationStore`: durable local `conversation name -> thread_id` mapping surviving app restarts, with list/create/rename/delete | `MUST` |
| RF-TUI-003 | Direct token-streamed transcript rendering (Markdown), visible tool-call activity, bounded terminal redraw frequency under fast streams | `MUST` |
| RF-TUI-004 | Keyboard-driven mid-turn cancellation with no content loss on the already-rendered partial answer | `MUST` |
| RF-TUI-005 | A slash-command set for conversation management (`/new`, `/switch`, `/rename`, `/delete`, `/cancel`, `/quit`, `/help`) | `MUST` |
| RF-TUI-006 | All `prismal-server` communication goes through `prismal_sdk`; zero wire-contract code and zero `prismal`/`prismal_server` imports here | `MUST` |
| RF-TUI-007 | Configuration via `PRISMAL_TUI_*` environment variables; all secrets as `SecretStr`, never rendered or persisted in plaintext | `MUST` |
| RF-TUI-008 | Error UX: typed SDK exceptions mapped to a friendly status message; the app never crashes on a turn-level failure | `MUST` |
| RF-TUI-009 | Offline unit + UI test suites (fake SDK client + Textual `Pilot`) + opt-in `contract` suite against a live host | `MUST` |

---

## 7. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Scope creep — the TUI grows agent/business logic (prompting, retries, local RAG) | `CLAUDE.md` hard rule + review checklist: terminal rendering, keybindings, and local conversation mapping only; the engine owns intelligence, the SDK owns transport |
| Wire-contract drift reaches the TUI | The SDK absorbs contract changes; this repo pins `prismal-sdk>=0.1,<1` and upgrades deliberately; `contract` suite catches breakage |
| Fast token streams flood the terminal with redraws, causing visible lag | Render coalescing at the widget layer (§4.2, `ARCHITECTURE.md`); a scripted-fast-stream UI test asserts a bounded redraw count |
| Lost conversation continuity on restart | `ConversationStore` (SQLite) persists the mapping before the first `create_thread()` call returns to the UI |
| Credential leaks (`prismal-server` token) on screen or in the store | Token stays `SecretStr`, used only by the SDK client constructor; a dedicated test asserts it never appears in rendered widget text or the SQLite file |
| Mid-turn cancellation leaves the transcript or `ConversationSession` in an inconsistent state | Cancellation is implemented as breaking the `async for` (SDK closes the stream, host cancels the run — same chain `prismal-webchat`'s stop button uses); unit-tested for transcript integrity |
| Textual version drift breaks the UI test suite | Pin `textual` to a tested minor; bump deliberately, `contract`/UI suites catch regressions in CI |

---

## 8. Dependencies

- `prismal-sdk` — the **only** path to `prismal-server`. Typed models,
  streaming events, exception hierarchy. No other prismal dependency.
- `textual` — the TUI framework (widgets, screens, async event loop,
  `Pilot` test harness).
- `platformdirs` — cross-platform user-data directory resolution for the
  `ConversationStore` SQLite file.
- Dev-only: `pytest`, `pytest-asyncio`, `ruff`, `mypy`.
- A running `prismal-server` for `contract` tests and manual dev (local
  `uvicorn` or Docker; see that repo's docs).
- **Not** dependencies: `prismal` (engine), `prismal_server` (host),
  `httpx` as a direct dep against `prismal-server` (it arrives
  transitively via the SDK and must not be used directly here — enforced
  by the boundary test).

---

## 9. Milestones

| Milestone | Content | Exit criterion |
|---|---|---|
| M0 — Seed | This SDD set (`PLAN`/`ARCHITECTURE`/`SPEC`/`TASKS`) + repo `CLAUDE.md` + `README.md` | Reviewed & merged |
| M1 — App skeleton | `uv` scaffold, `PrismalTuiSettings`, boundary guard test, `ConversationStore` schema, CI, empty `PrismalTuiApp` boots and connects `healthz()` | Process boots, shows connection status; guards green |
| M2 — Session core | `ConversationSession` turn lifecycle against a fake SDK client; thread resolution/persistence, cancellation | Unit-tested turn: conversation reuse across a simulated restart, cancel leaves partial text intact, done/error terminal states |
| M3 — Transcript & composer UX | Transcript widget (Markdown render, tool-call activity, render coalescing), composer + slash commands, sidebar (list/switch/rename/delete) | `Pilot`-driven UI tests green; manual verification against a real `prismal-server` |
| M4 — Error UX & polish | Friendly error surfaces, status bar, keybinding cheatsheet (`/help`), theming defaults | Manual verification checklist against real failure modes (server down, budget exceeded, policy denied) |
| M5 — Hardening & release | `contract` suite vs a real host, secret-leak test, packaging (console script), docs, `v0.1.0` tag | CI green; a fresh `uv pip install -e ".[dev]"` + `prismal-tui` answers against a live `prismal-server` |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-19 | Ernesto Crespo | Initial PLAN for the terminal UI front-end, derived from the ecosystem presentation (v3.10.1), the `prismal-server` wire contract, the `prismal-sdk` client surface, and the patterns established in `prismal-webchat` and `prismal-chatbot` |
