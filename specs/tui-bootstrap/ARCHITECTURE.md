# prismal-tui — Architecture (TUI Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-19 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`SPEC.md`](./SPEC.md) · [`TASKS.md`](./TASKS.md) |

---

## 1. Guiding principle — a face, not a brain

> **intelligence → engine (`prismal`); transport → `prismal-sdk`; serving
> the engine → `prismal-server`; rendering a conversation in a terminal,
> local conversation↔thread mapping, and keybindings → this repo. Nothing
> else lives here.**

`prismal-tui` talks to exactly **one** upstream surface — a running
`prismal-server`, and only **through `prismal_sdk`**. It never imports
`prismal` (engine) or `prismal_server` (host), never opens a raw HTTP
connection to the host (no direct `httpx` use against it), never parses
SSE, never maps wire error codes, and never builds a prompt. Its whole job
is:

| Concern | Owner |
|---|---|
| Agent reasoning, RAG, tools, security | `prismal` (engine), server-side |
| Wire contract (REST/SSE, errors, auth headers) | `prismal-server` (SPEC-RHB-*) |
| Typed transport, SSE parsing, exceptions | `prismal-sdk` (SPEC-CSB-*) |
| Terminal rendering, keybindings, local conversation↔thread mapping | **this repo** (SPEC-TUI-*) |

Any pull toward importing `prismal.*` / `prismal_server.*`, calling the
host with `httpx` directly, re-implementing event parsing, or adding
prompt/agent/business logic is a design smell — see the `CLAUDE.md` review
checklist. This is the same "face, not a brain" boundary `prismal-webchat`
(browser BFF) and `prismal-chatbot` (external bots) already draw one hop
over; here the face is a terminal instead of a browser tab or a chat
platform message.

---

## 2. C4 — Context

```
   Developer's terminal
  ┌───────────────────────┐
  │ keyboard in / ANSI out │
  └───────────┬─────────────┘
              │ stdin / stdout (Textual)
              ▼
  ┌─────────────────────────┐
  │   PrismalTuiApp           │   this repo — single local process,
  │   (Textual application)   │   prismal_tui
  └────────────┬──────────────┘
               │ import prismal_sdk
               │ (AsyncPrismalClient, HTTP + SSE)
               ▼
  ┌─────────────────────────┐
  │      prismal-server       │   sibling repo
  └────────────┬──────────────┘
               │ 4 seams
               ▼
  ┌─────────────────────────┐
  │      prismal (engine)     │
  └─────────────────────────┘
```

`prismal-tui` is single-user and single-process: one developer, one
terminal, one `AsyncPrismalClient`, talking to one `prismal-server` chosen
at startup. There is no browser, no CORS concern, and no external platform
event source — input arrives as keystrokes, output renders as ANSI in the
same terminal. The trust boundary is the local machine plus whatever
bearer credential the user configures for the target `prismal-server`.

---

## 3. C4 — Container / module layout

```
prismal-tui/
├── pyproject.toml                  # deps: prismal-sdk, textual, platformdirs; NO prismal/prismal-server/httpx dep
├── CLAUDE.md                       # boundary rule + review checklist
├── README.md
├── prismal_tui/
│   ├── __init__.py
│   ├── __main__.py                 # console-script entrypoint `prismal-tui`: builds settings + App, runs it
│   ├── app.py                      # PrismalTuiApp(textual.app.App): screens, key bindings, lifecycle (client open/close)
│   ├── settings.py                 # PrismalTuiSettings (pydantic-settings, PRISMAL_TUI_ prefix, SecretStr token)
│   ├── client.py                   # get_client(): lazily built, process-wide AsyncPrismalClient from settings
│   ├── session/
│   │   ├── conversation_session.py # ConversationSession: thread resolution, streaming turn, cancellation, error mapping
│   │   └── models.py                # Conversation, TurnOutcome, CancelledTurn
│   ├── store/
│   │   └── conversation_store.py   # ConversationStore (SQLite, WAL): conversation name <-> thread_id, CRUD
│   ├── widgets/
│   │   ├── transcript.py           # TranscriptView: renders TokenEvent/ToolCallEvent/DoneEvent as Markdown, coalesced redraw
│   │   ├── sidebar.py              # ConversationList: list/switch/rename/delete, backed by ConversationStore
│   │   ├── composer.py             # Input widget: message entry + slash-command parsing (commands.py)
│   │   └── statusbar.py            # connection/health status, error toasts, key-binding hints
│   ├── commands.py                 # slash-command registry: /new /switch /rename /delete /cancel /quit /help
│   └── errors.py                   # SDK exception -> friendly-text mapping (mirrors prismal-webchat/prismal-chatbot)
├── docs/
│   └── configuration.md            # PRISMAL_TUI_* reference
└── tests/
    ├── conftest.py                 # FakeAsyncPrismalClient, tmp ConversationStore fixture
    ├── unit/                       # session, store, commands, errors (offline, no Textual event loop)
    ├── ui/                         # Textual Pilot-driven widget/app tests (offline)
    └── contract/                   # opt-in: real prismal-server round-trip via ConversationSession
```

**Why a session and not widget-embedded logic:** the entire
UI-independent part of a turn — resolve or create a `thread_id`, stream
`send_message()`, coalesce render updates, map errors, honor cancellation —
is identical regardless of which widget is currently focused or which
screen is visible. `ConversationSession` owns it once (the TUI's analogue
of `prismal-chatbot`'s `ConversationBridge`, without the platform-adapter
concept since there is exactly one "platform": the terminal itself); the
`widgets/` layer only renders `ConversationSession` events and turns user
input (keystrokes, slash commands) into session calls. This keeps the
session unit-testable with a fake SDK client and no Textual event loop at
all, and keeps the widgets testable via Textual's `Pilot` harness with a
fake session.

---

## 4. Data flow

### 4.1 Streaming conversation turn (RF-TUI-001/003/004)

```
user submits text in the composer (Enter, or after a slash command resolves to a message)
  └─ await app.send(text):
        thread_id = await store.get(active_conversation.id)
        if thread_id is None:
            thread = await client.create_thread()
            await store.put(active_conversation.id, thread.thread_id)   # persist BEFORE first send
            thread_id = thread.thread_id
        session = ConversationSession(client, thread_id)
        async for event in session.stream(text):     # wraps client.send_message()
            with cancellation scope (bound to the Esc key binding):
                TokenEvent(delta)        → transcript.feed(delta)              (coalesced redraw)
                ToolCallEvent(name,args) → transcript.activity(f"⚙ using {name}…")  (persistent, low-emphasis line)
                StateEvent(data)         → ignored in v0.1 (logged debug)
                DoneEvent(finish_reason) → transcript.finalize(); statusbar.idle()
        except PrismalSDKError as e:
            → statusbar.error(friendly_text(e))          (errors.py mapping)
        except SessionCancelled:
            → transcript.finalize(cancelled=True); statusbar.idle()
```

`store.put()` happens **before** the first token is requested, so a crash
mid-turn still leaves the mapping durable for the next message on the same
conversation — the engine's checkpointer is the source of truth for
message history, `ConversationStore` only remembers *which* thread a
locally-named conversation maps to (same principle as
`prismal-chatbot`'s `ThreadStore`, ADR-002 there).

### 4.2 Render coalescing (RF-TUI-003) — a performance guard, not a rate limit

```
TranscriptView.feed(delta):
    buffer += delta
    if not a redraw already scheduled for this frame:
        schedule_redraw()   # Textual's own frame scheduling (call_later / set_interval), not a fixed sleep
TranscriptView._redraw():
    render buffer as Markdown into the transcript log
    clear "redraw scheduled" flag
```

Unlike `prismal-chatbot`'s `StreamThrottle` (§4.2 there), which exists
because Slack/Discord themselves rate-limit message edits, there is no
external rate limit on a local terminal — the goal here is only to avoid
scheduling more redraws than Textual's own frame loop can usefully consume
on a very fast token stream (e.g. a short cached response arriving in a
tight burst). Coalescing is keyed to one pending redraw per frame, not to a
fixed time/char interval, and every `TokenEvent.delta` is always included
in the next redraw — no content is ever dropped or delayed past the
following frame.

### 4.3 Cancellation (RF-TUI-004)

```
Esc (default binding) during an in-flight turn
  → ConversationSession.cancel() sets a cancellation flag / cancels the
    asyncio task driving `async for event in session.stream(...)`
  → the SDK's iterator is closed (SPEC-CSB-CHT-006) → the host cancels the
    run (SPEC-RHB-CHT-004) → transcript keeps whatever text was already
    rendered, appends a "— cancelled —" marker, statusbar returns to idle
```

This is the direct terminal counterpart of `prismal-webchat`'s stop button
(§4.2 there) — a human-initiated, immediate cancel — rather than
`prismal-chatbot`'s blind per-turn timeout (§4.3 there), which exists
specifically because a chat platform has no equivalent to a keypress. v0.1
does not add a timeout on top of this; TUI-FUTURE tracks revisiting that
only if a real "walked away from the terminal" scenario demands it.

### 4.4 Conversation identity (RF-TUI-002)

```
Conversation = (id: local uuid4, name: str, thread_id: str | None,
                 created_at, last_active_at)

ConversationStore (SQLite, WAL mode), file path resolved via `platformdirs`
user-data-dir (override: PRISMAL_TUI_STORE_PATH):
  CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    thread_id TEXT,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
  );
```

Unlike `prismal-chatbot`'s `ThreadStore`, which keys on an
externally-derived `(platform, external_conversation_key)`, the TUI's
conversations are named and managed *by the user* (`/new`, `/rename`,
`/delete`, sidebar picker) — the mapping exists for the same durability
reason (a restart must not fork history) but the key is local and
user-facing rather than platform-derived.

### 4.5 Configuration & secret path (RF-TUI-007)

```
env (PRISMAL_TUI_*) ──▶ PrismalTuiSettings (pydantic-settings)
  ├─ server_url, token (SecretStr), org_id ──▶ client.py → AsyncPrismalClient
  ├─ store_path ──▶ ConversationStore
  └─ cancel_key (default "escape") ──▶ PrismalTuiApp key bindings
```

The credential is a `SecretStr`, read once at startup to construct the SDK
client; it is never rendered in any widget, never written to the
`ConversationStore`, and never appears in a log line or exception text
(enforced by the secret-leak test, mirroring `prismal-webchat`'s
`SPEC-WCB-AUT-002` and `prismal-chatbot`'s `SPEC-CHB-AUT-002`).

---

## 5. Architecture Decision Records

### ADR-001 — Textual as the TUI framework
**Decision:** Build `prismal-tui` on
[Textual](https://textual.textualize.io/) (async-native, Rich-based
rendering, official `Pilot` test harness for offline UI testing).
**Rationale:** the app needs a scrollable Markdown-capable transcript, a
sidebar, an input composer, and a status bar, all updating live from an
async SSE stream — Textual's async event loop maps directly onto
`AsyncPrismalClient`'s `async for`, and its `Pilot` harness gives the same
offline-testable seam the other front-ends get from fake HTTP/SSE.
**Alternatives:** a plain `prompt_toolkit`/`rich` REPL (rejected — no
multi-pane layout, no first-class async widget model, weaker test
harness); a Node-based TUI (rejected — the whole ecosystem is Python, and
`prismal-sdk` is a Python client). **Status:** Accepted.

### ADR-002 — Local `ConversationStore` (SQLite) keyed by a user-named conversation
**Decision:** Persist `conversation id -> thread_id` (plus a user-chosen
`name`) in a local SQLite file (via `platformdirs`), written before the
first `send_message()` call for a new conversation.
**Rationale:** mirrors `prismal-chatbot`'s ADR-002 durability argument (a
restart must not fork history) but the key is chosen by the user through
the UI (`/new <name>`) rather than derived from an external platform —
there is no "external conversation key" here, only what the developer
names their own session.
**Alternatives:** in-memory only (loses history on every restart —
rejected, same correctness argument as `prismal-chatbot`); relying on the
engine's checkpointer alone (rejected — the engine has no concept of a
human-readable local conversation name, and the TUI still needs to resolve
"which `thread_id` did I use last time for 'debugging RAG'" without asking
the user to remember a UUID). **Status:** Accepted.

### ADR-003 — Direct per-token rendering with frame-based coalescing, not a rate-limit throttle
**Decision:** `TranscriptView` renders every `TokenEvent.delta`, coalesced
to at most one redraw per Textual frame, instead of `prismal-chatbot`'s
time/char-interval `StreamThrottle`.
**Rationale:** there is no external rate limit on local terminal output;
the only real constraint is not scheduling redundant redraws faster than
the terminal can usefully show them. Frame-based coalescing (schedule at
most one pending redraw) is the natural Textual-idiomatic mechanism and
requires no tunable interval.
**Alternatives:** render on every single delta with no coalescing at all
(rejected — can visibly stutter on a very fast/cached response bursting
many deltas within one frame); reuse `prismal-chatbot`'s fixed-interval
throttle (rejected — it optimizes for an external rate limit that does not
exist here, and would add visible, unnecessary latency to normal-speed
streams). **Status:** Accepted.

### ADR-004 — Keyboard cancel instead of a per-turn timeout
**Decision:** A single key binding (`Esc` by default,
`PRISMAL_TUI_CANCEL_KEY` overridable) cancels an in-flight turn
immediately; v0.1 ships no automatic per-turn timeout.
**Rationale:** unlike `prismal-chatbot` (no equivalent to a button click on
a chat platform, hence a hard timeout, ADR-005 there), the TUI always has
a human at the keyboard — the same assumption `prismal-webchat`'s stop
button relies on (there is a person who can click/press something). A
blind timeout would be redundant UX for the common case.
**Alternatives:** timeout only, no manual cancel (rejected — worse UX than
the sibling front-ends, which both give the user *some* way to stop a
runaway turn); both a manual cancel and a background timeout (deferred —
real feature if "walked away from the terminal mid-turn" turns out to
matter, tracked as a `TASKS.md` future item). **Status:** Accepted.

### ADR-005 — Fake SDK client + Textual `Pilot` as the unit-test seam
**Decision:** `ConversationSession` unit tests inject a
`FakeAsyncPrismalClient` (same shape as `prismal-webchat`'s and
`prismal-chatbot`'s) with no Textual dependency at all; widget/app tests
drive a real `PrismalTuiApp` through Textual's `Pilot` harness, backed by
the same fake client and a tmp `ConversationStore` — no live server, no
live terminal.
**Rationale:** mirrors the engine's factory-injection testing pattern and
every sibling front-end's fake-client pattern; separating the
session-layer tests (no event loop needed beyond `asyncio`) from the
UI-layer tests (need Textual's `Pilot`) keeps the fast unit suite fast.
**Status:** Accepted.

### ADR-006 — Single local process, single client, no multi-tenancy
**Decision:** One `PrismalTuiApp` process holds exactly one
`AsyncPrismalClient`, configured once at startup from `PrismalTuiSettings`;
no in-app server-switching or per-conversation tenancy in v0.1.
**Rationale:** the TUI is a local developer tool, not a multi-tenant
service — matching `prismal-webchat`'s ADR-006 (single-process deploy) and
`prismal-chatbot`'s ADR-004 (one process) in spirit, simplified further
because there is exactly one user. Switching servers or tenants without
restarting is real but deferred (TUI-FUTURE-03).
**Status:** Accepted.

---

## 6. Error handling

- Every `PrismalSDKError` raised during a turn is caught in exactly one
  place — `ConversationSession.stream()`'s caller in `app.py` — and mapped
  (`errors.py`) to a friendly string shown on the status bar / as a
  transcript system line, never as a raw exception.
- Mapping mirrors `prismal-webchat`'s and `prismal-chatbot`'s
  (`ARCHITECTURE.md` §6 in both): `PrismalConnectionError` /
  `PrismalTimeoutError` → "Can't reach `prismal-server` — check
  `PRISMAL_TUI_SERVER_URL` and try again."; `BudgetExceededError` → "The
  assistant is over capacity for now."; `PolicyDeniedError` /
  `PermissionDeniedError` → "That request can't be processed."; any other
  `PrismalAPIError` / `PrismalSDKError` → generic failure text. Codes,
  stack traces, and server messages go to the TUI's log file only (never
  the transcript).
- A mid-stream error or cancellation preserves whatever partial text was
  already rendered in the transcript, appending a short system note rather
  than replacing it — matching the "never blank a partial answer" rule
  from both sibling front-ends.
- There is no automatic retry; the user simply sends another message,
  which continues on the same (already-resolved) `thread_id`.

---

## 7. Observability

Structured logs (turn started/finished, conversation id, `thread_id`,
event counts, mapped error codes — never message content, never any token)
via standard `logging`, written to a local log file under the same
`platformdirs` data directory as the `ConversationStore`, mirroring
`prismal-webchat`'s and `prismal-chatbot`'s approach. The TUI does not
stand up its own OTel stack in v0.1; engine-side tracing (Langfuse/OTel)
already covers the interesting part of every turn.

---

## 8. Packaging & deploy (sketch)

`uv`-based project; a console-script entrypoint (`prismal-tui =
"prismal_tui.__main__:main"`) launches the Textual app for local dev and
for anyone installing from source. Not published to PyPI in v0.1 — install
from a checkout via `uv pip install -e ".[dev]"`, matching where
`prismal-webchat` and `prismal-chatbot` currently stand; PyPI publication
(enabling `uvx prismal-tui`) is TUI-FUTURE-01. Versioning follows the
org's `MAJOR.MINOR.PATCH`; `v0.1.0` targets the M5 exit criterion in
`PLAN.md`. Pins: `prismal-sdk>=0.1,<1`, `textual` and `platformdirs` to a
tested minor (bumped deliberately).

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-19 | Ernesto Crespo | Initial architecture: Textual app over prismal-sdk, ConversationSession turn lifecycle, local ConversationStore, frame-coalesced streaming render, keyboard cancellation |
