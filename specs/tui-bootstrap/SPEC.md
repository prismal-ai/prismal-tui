# prismal-tui — Technical Specification (TUI Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-19 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`TASKS.md`](./TASKS.md) |

Requirement IDs are `SPEC-TUI-<AREA>-NNN`. Priority follows RFC 2119
(`MUST`/`SHOULD`/`MAY`). Each maps back to an `RF-TUI-*` in `PLAN.md`. Where
a requirement leans on a sibling contract, the sibling's ID is cited
(`SPEC-CSB-*` from `prismal-sdk`, `SPEC-RHB-*` from `prismal-server`).

---

## 1. Application & construction

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-APP-001 | The process MUST expose one console-script entrypoint (`prismal-tui`, `python -m prismal_tui`) that constructs `PrismalTuiSettings`, a single `AsyncPrismalClient`, a single `ConversationStore`, and mounts a single `PrismalTuiApp` (Textual). | `MUST` |
| SPEC-TUI-APP-002 | The repo MUST NOT import `prismal` or `prismal_server`, and MUST NOT use `httpx` (or any HTTP client) directly against `prismal-server` — all upstream traffic goes through `prismal_sdk`. Enforced by an AST boundary-guard test. | `MUST` |
| SPEC-TUI-APP-003 | The SDK client MUST be a process-wide `AsyncPrismalClient` built lazily from `PrismalTuiSettings` (`client.py::get_client()`), closed on app shutdown (Textual `on_unmount` / `finally`). | `MUST` |
| SPEC-TUI-APP-004 | On startup the app MUST call `healthz()` (and MAY call `readyz()`) against the configured server and surface the result on the status bar before accepting the first message; a failed check MUST NOT prevent the app from starting (it degrades to a visible "disconnected" state, retried on the next send). | `MUST` |
| SPEC-TUI-APP-005 | Widget modules (`widgets/*`) MUST NOT import `prismal_sdk` transport internals directly (`httpx`, `_sse`, `_transport`) — they consume only `ConversationSession` and the typed models re-exported by `prismal_sdk` (keeps the UI layer testable without knowledge of the wire format). | `MUST` |

## 2. Conversation session & threading

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-SES-001 | `ConversationSession` MUST resolve `thread_id` via `ConversationStore.get(conversation_id)`; on miss it MUST call `create_thread()` exactly once and persist the mapping via `ConversationStore.put(conversation_id, thread_id)` **before** issuing `send_message()`. | `MUST` |
| SPEC-TUI-SES-002 | `ConversationSession.stream()` MUST consume `send_message()`'s typed events and yield UI-facing updates: `TokenEvent.delta` for transcript feed, `ToolCallEvent` for activity display, `DoneEvent` as the terminal success marker. `StateEvent` MAY be ignored (logged at debug). | `MUST` |
| SPEC-TUI-SES-003 | At most one in-flight turn per conversation MUST be active at a time; submitting a new message while a turn is in flight on the active conversation MUST be rejected by the composer with a friendly inline note ("still answering — press Esc to cancel first") rather than queued. | `MUST` |
| SPEC-TUI-SES-004 | User-provided text MUST be passed to `send_message(content=…)` unmodified — no templating, prefixing, or prompt construction anywhere in this repo (`SPEC-CSB-CHT-007`; the engine's security layers apply server-side). Sole exception: the `//` escape slash is removed (`DELTA-2026-11-slash-escape`, `SPEC-TUI-UX-006`). | `MUST` |
| SPEC-TUI-SES-005 | Switching the active conversation while a turn is in flight on a *different* conversation MUST NOT cancel that turn; each conversation's session state is independent (a background turn may finish while the user is viewing another conversation). | `SHOULD` |

## 3. Streaming render

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-REN-001 | `TranscriptView` MUST render `TokenEvent.delta`s as they arrive, with content committed via at most one scheduled redraw per Textual frame (frame-coalesced, not time/char-interval throttled, `ADR-003`). | `MUST` |
| SPEC-TUI-REN-002 | The final rendered text after `DoneEvent` MUST equal the full concatenation of all `TokenEvent.delta`s for that turn, regardless of coalescing (no content loss). | `MUST` |
| SPEC-TUI-REN-003 | `ToolCallEvent`s MUST render as a distinct, visually de-emphasized line (e.g. dimmed, prefixed `⚙`) inserted in transcript order relative to surrounding tokens. | `MUST` |
| SPEC-TUI-REN-004 | Completed assistant turns MUST render as Markdown (headings, lists, fenced code blocks with syntax highlighting) once `DoneEvent` is received; in-flight streaming text MAY render as plain text and re-render as Markdown only on finalize, if incremental Markdown re-parsing proves costly. | `SHOULD` |
| SPEC-TUI-REN-005 | A scripted fast token stream (unit/UI test) MUST produce a bounded number of redraw calls proportional to rendered frames, not to token count. | `MUST` |

## 4. Persistence (`ConversationStore`)

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-STO-001 | `ConversationStore` MUST persist `(id, name, thread_id, created_at, last_active_at)` in SQLite with WAL mode enabled, at a path from `PRISMAL_TUI_STORE_PATH` (default: a `platformdirs` user-data directory). | `MUST` |
| SPEC-TUI-STO-002 | `ConversationStore` MUST support `list()`, `create(name)`, `get(id)`, `put(id, thread_id)`, `rename(id, name)`, `delete(id)`, all safe for the app's single-process, async-serialized access pattern. | `MUST` |
| SPEC-TUI-STO-003 | A process restart MUST resolve a previously-seen conversation to the same `thread_id` (round-trip unit test using a real temp SQLite file, not a fake). | `MUST` |
| SPEC-TUI-STO-004 | The store schema MUST be created automatically on first run if the file/table does not exist (no manual migration step for v0.1). | `MUST` |
| SPEC-TUI-STO-005 | `delete(id)` MUST remove only the local name↔thread mapping; it MUST NOT call any engine/host API to delete conversation history (out of scope — the engine's checkpointer is the source of truth for message content). | `MUST` |

## 5. Terminal UX & keybindings

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-UX-001 | The composer MUST support the slash commands `/new [name]`, `/switch <name>`, `/rename <name>`, `/delete [name]`, `/cancel`, `/quit`, `/help`; unrecognized `/`-prefixed input MUST show a friendly "unknown command" hint rather than being sent as a message; `//text` is a message sent as `/text` (`SPEC-TUI-UX-006`, `DELTA-2026-11-slash-escape`). | `MUST` |
| SPEC-TUI-UX-002 | The cancel key binding (default `Esc`, overridable via `PRISMAL_TUI_CANCEL_KEY`) MUST be active only while a turn is in flight and MUST invoke `ConversationSession.cancel()` for the active conversation's turn. | `MUST` |
| SPEC-TUI-UX-003 | The sidebar MUST list all conversations from `ConversationStore.list()`, ordered by `last_active_at` descending, and support switching the active conversation via keyboard navigation. | `MUST` |
| SPEC-TUI-UX-004 | `/help` (or a dedicated key binding) MUST display the current key-binding cheatsheet and slash-command list without leaving the app. | `MUST` |
| SPEC-TUI-UX-005 | `/quit` (and the app's default quit binding, e.g. `Ctrl+Q`) MUST close the `AsyncPrismalClient` cleanly before the process exits (no dangling connections, no unflushed `ConversationStore` writes). | `MUST` |

## 6. Error UX

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-ERR-001 | Every `PrismalSDKError` raised during a turn MUST be caught at the `app.py` call site of `ConversationSession.stream()` and mapped to friendly text (`errors.py`), shown on the status bar and as a transcript system line. | `MUST` |
| SPEC-TUI-ERR-002 | Error codes, server messages, and stack traces MUST NOT render in the transcript or status bar; they go to the local log file only (mirrors `SPEC-RHB-ERR-002` / `SPEC-WCB-ERR-002` / `SPEC-CHB-ERR-002`). | `MUST` |
| SPEC-TUI-ERR-003 | A mid-stream error or cancellation MUST preserve whatever partial text was already rendered, appending a short system note rather than replacing it. | `MUST` |
| SPEC-TUI-ERR-004 | There is no automatic retry of a failed turn; the next user message is treated as a new turn on the same (already-resolved) `thread_id`. | `MUST` |
| SPEC-TUI-ERR-005 | An unhandled exception in one conversation's turn MUST NOT crash the app or affect other conversations' state; it is caught, logged, and surfaced as `SPEC-TUI-ERR-001`. | `MUST` |

## 7. Auth, tenancy & secret hygiene

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-AUT-001 | The app authenticates to `prismal-server` with a single credential from `PrismalTuiSettings.token` (`SecretStr`), passed only to the SDK client constructor. | `MUST` |
| SPEC-TUI-AUT-002 | The token MUST NOT appear in any rendered widget text, the `ConversationStore` file, a log line, or an exception message. A dedicated test MUST assert its absence from all of these. | `MUST` |
| SPEC-TUI-AUT-003 | When `org_id` is configured it MUST be applied client-wide via the SDK (`X-Org-Id`, `SPEC-CSB-AUT-002`); the app MUST NOT invent any other header or tenancy mechanism. | `MUST` |

## 8. Configuration

`PrismalTuiSettings` (pydantic-settings, prefix `PRISMAL_TUI_`); the token
is a backend-only `SecretStr`.

| Key | Env var | Default | Meaning |
|---|---|---|---|
| `server_url` | `PRISMAL_TUI_SERVER_URL` | `http://localhost:8000` | Target `prismal-server` |
| `token` | `PRISMAL_TUI_TOKEN` | `None` | Bearer credential (`SecretStr`) |
| `org_id` | `PRISMAL_TUI_ORG_ID` | `None` | Tenant for all TUI traffic |
| `store_path` | `PRISMAL_TUI_STORE_PATH` | `platformdirs` user-data dir / `conversations.db` | `ConversationStore` SQLite file |
| `cancel_key` | `PRISMAL_TUI_CANCEL_KEY` | `escape` | Key binding that cancels an in-flight turn (§4.3, `ARCHITECTURE.md`) |
| `log_level` | `PRISMAL_TUI_LOG_LEVEL` | `INFO` | Local log file verbosity |

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-CFG-001 | `server_url` MUST be validated as an absolute `http(s)://` URL at startup, failing fast with a readable error before the Textual app mounts. | `MUST` |
| SPEC-TUI-CFG-002 | `store_path`'s parent directory MUST be created if missing (first-run convenience); a permissions failure MUST surface a clear startup error, not a silent crash. | `MUST` |
| SPEC-TUI-CFG-003 | `cancel_key` MUST be validated against Textual's known key-name set at startup; an invalid value MUST fail fast with a clear error. | `MUST` |

## 9. Non-functional

| ID | Requirement | Prio |
|---|---|---|
| SPEC-TUI-NFR-001 | The unit suite MUST run with no network, using `FakeAsyncPrismalClient` and a tmp `ConversationStore` (`ADR-005`); UI tests use Textual's `Pilot` harness (also offline); a separate opt-in `contract` suite exercises a live `prismal-server`. | `MUST` |
| SPEC-TUI-NFR-002 | `ruff check .` and `mypy` on `prismal_tui/` MUST be clean in CI. | `MUST` |
| SPEC-TUI-NFR-003 | Logs MUST NOT contain message content or any secret; they MAY contain conversation id, `thread_id`, event counts, mapped error codes, and redraw counts. | `MUST` |
| SPEC-TUI-NFR-004 | The app MUST remain responsive (accepts input, redraws) while a turn is streaming — no blocking calls on the Textual event loop. | `MUST` |
| SPEC-TUI-NFR-005 | Version pins: `prismal-sdk>=0.2,<1` (modified by DELTA-2026-10); `textual` and `platformdirs` pinned to a tested minor; bumps are deliberate PRs, not drive-by. | `MUST` |

---

## 10. Traceability (RF → SPEC)

| RF | Covered by |
|---|---|
| RF-TUI-001 | SPEC-TUI-SES-001..005 |
| RF-TUI-002 | SPEC-TUI-STO-001..005 |
| RF-TUI-003 | SPEC-TUI-REN-001..005 |
| RF-TUI-004 | SPEC-TUI-UX-002, SPEC-TUI-ERR-003 |
| RF-TUI-005 | SPEC-TUI-UX-001, SPEC-TUI-UX-003/004/005 |
| RF-TUI-006 | SPEC-TUI-APP-002/003/005 |
| RF-TUI-007 | SPEC-TUI-CFG-001..003, SPEC-TUI-AUT-001..003 |
| RF-TUI-008 | SPEC-TUI-ERR-001..005 |
| RF-TUI-009 | SPEC-TUI-NFR-001 |

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-19 | Ernesto Crespo | Initial technical spec for the terminal UI front-end |
