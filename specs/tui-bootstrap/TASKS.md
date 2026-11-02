# prismal-tui — Task Breakdown (TUI Bootstrap)

| Field | Value |
|---|---|
| **Status** | `DRAFT` |
| **Version** | 1.0 |
| **Date** | 2026-07-19 |
| **Companion** | [`PLAN.md`](./PLAN.md) · [`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`SPEC.md`](./SPEC.md) |

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED`. Every task is **test-first
(TDD)** — write the failing test, watch it fail, minimal code to green. Tasks
map to `SPEC-TUI-*` IDs and the `M0…M5` milestones in `PLAN.md`.

---

## Phase 0 — Seed & scaffold (M0/M1)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-00-01 | SDD set (`PLAN`/`ARCHITECTURE`/`SPEC`/`TASKS`) + `CLAUDE.md` + `README.md` | 0.5 d | — | — | `DONE` |
| TUI-00-02 | `pyproject.toml` (`prismal-sdk>=0.2,<1`, `textual`, `platformdirs`, `pydantic-settings`; console script `prismal-tui`; dev extras `pytest`, `pytest-asyncio`, `ruff`, `mypy`) | 0.4 d | 00-01 | NFR-005 | `DONE` |
| TUI-00-03 | `settings.py`: `PrismalTuiSettings` (prefix, `SecretStr` token, URL/store-path/cancel-key validation, fail-fast) | 0.5 d | 00-02 | CFG-001..003, AUT-001/003 | `DONE` |
| TUI-00-04 | Boundary-guard test: AST scan — no `prismal`/`prismal_server` import, no direct `httpx` use, no `prismal_sdk` transport internals imported from `widgets/` | 0.3 d | 00-02 | APP-002/005 | `DONE` |
| TUI-00-05 | `tests/conftest.py`: `FakeAsyncPrismalClient` (scripted event streams), tmp `ConversationStore` fixture | 0.5 d | 00-02 | NFR-001 | `DONE` |
| TUI-00-06 | CI (`.github/workflows/ci.yml`): ruff + mypy + pytest (unit + ui); opt-in `contract` job | 0.3 d | 00-02 | NFR-002 | `DONE` |

## Phase 1 — Session core (M2)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-01-01 | `client.py`: lazy process-wide `AsyncPrismalClient` from settings; closed on shutdown | 0.3 d | 00-03 | APP-003 | `DONE` |
| TUI-01-02 | `store/conversation_store.py`: SQLite `ConversationStore` (WAL, auto-create schema), `list`/`create`/`get`/`put`/`rename`/`delete` | 0.6 d | 00-02 | STO-001/002/004/005 | `DONE` |
| TUI-01-03 | Restart-continuity test: real temp SQLite file, same conversation resolves to same `thread_id` across two `ConversationStore` instances | 0.3 d | 01-02 | STO-003 | `DONE` |
| TUI-01-04 | `session/conversation_session.py`: `ConversationSession.stream()` — thread resolution before first send, event translation (Token/ToolCall/Done), cancellation hook | 0.8 d | 01-01, 01-02, 00-05 | SES-001/002/004 | `DONE` |
| TUI-01-05 | Per-conversation in-flight guard (reject a new send while a turn is active on the same conversation) | 0.4 d | 01-04 | SES-003 | `DONE` |
| TUI-01-06 | Independent per-conversation session state (a background turn on a non-active conversation is unaffected by switching) | 0.4 d | 01-04 | SES-005 | `DONE` |
| TUI-01-07 | Cancellation: `ConversationSession.cancel()` breaks the stream cleanly, no content loss on already-yielded events | 0.5 d | 01-04 | ERR-003 (partial), UX-002 (session half) | `DONE` |
| TUI-01-08 | `errors.py`: SDK exception → friendly-text mapping table + unit tests for each mapped type | 0.4 d | 01-04 | ERR-001..005 | `DONE` |

## Phase 2 — Transcript & composer UX (M3)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-02-01 | `app.py`: `PrismalTuiApp` skeleton — mounts, calls `healthz()` on startup, wires settings/client/store, shutdown closes the client | 0.6 d | 01-01 | APP-001/004 | `DONE` |
| TUI-02-02 | `widgets/transcript.py`: `TranscriptView` — frame-coalesced token feed, tool-call activity line, Markdown finalize render | 0.8 d | 02-01 | REN-001..004 | `DONE` |
| TUI-02-03 | Redraw-count UI test: scripted fast token stream produces a bounded number of redraws, final text matches full concatenation | 0.5 d | 02-02 | REN-005 | `DONE` |
| TUI-02-04 | `widgets/composer.py` + `commands.py`: message entry, slash-command parsing/dispatch (`/new /switch /rename /delete /cancel /quit /help`) | 0.7 d | 02-01 | UX-001/004/005 | `DONE` |
| TUI-02-05 | `widgets/sidebar.py`: `ConversationList` — list ordered by `last_active_at`, keyboard switch, backed by `ConversationStore` | 0.6 d | 01-02, 02-01 | UX-003 | `DONE` |
| TUI-02-06 | Cancel key binding wired end-to-end (`Esc` default, `PRISMAL_TUI_CANCEL_KEY`), active only during an in-flight turn | 0.4 d | 01-07, 02-04 | UX-002 | `DONE` |
| TUI-02-07 | `Pilot`-driven UI tests: send a message, see streamed tokens render, switch conversations, run each slash command | 0.8 d | 02-02..06, 00-05 | NFR-001 | `DONE` |

## Phase 3 — Error UX & polish (M4)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-03-01 | `widgets/statusbar.py`: connection status, error toasts, key-binding hints | 0.5 d | 02-01 | ERR-001/002, APP-004 | `DONE` |
| TUI-03-02 | Error-path UI tests: connection error, budget-exceeded, policy-denied each render the mapped friendly text, never a code/traceback | 0.5 d | 01-08, 03-01 | ERR-001/002/004/005 | `DONE` |
| TUI-03-03 | Mid-stream error/cancel preserves partial transcript text + system note (unit + UI test) | 0.4 d | 01-07, 02-02 | ERR-003 | `DONE` |
| TUI-03-04 | `/help` screen: key-binding cheatsheet + slash-command list | 0.3 d | 02-04 | UX-004 | `DONE` |
| TUI-03-05 | Manual verification checklist against a real `prismal-server` (server down, budget exceeded, policy denied, normal turn, cancel) — [`docs/manual-verification.md`](../../docs/manual-verification.md); live cancel, budget and policy items still need a non-fake host | 0.4 d | 03-02 | — | `DONE` |

## Phase D — Usage readout (DELTA-2026-10, folded into v0.1.0)

Source: [`DELTA-2026-10-usage-agui.md`](./DELTA-2026-10-usage-agui.md).
Runs after Phase 3 (TUI-D-05 needs the status bar from TUI-03-01) and
before the `v0.1.0` tag (TUI-04-06).

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-D-01 | Verify before build: pin the `budget_exceeded` fixture (RH2 §11 / CS2 §7); document the `Usage`/`UsageReport` fields the TUI shows (in `docs/configuration.md`, shared with TUI-04-04) | 0.2 d | — | ERR-002, USG-006 | `DONE` |
| TUI-D-02 | SDK pin bump (done in TUI-00-02); extend `FakeAsyncPrismalClient` with `DoneEvent.usage` + `usage()` scripts (incl. 404, `InvalidRequestError`) | 0.3 d | D-01 | NFR-005 | `DONE` |
| TUI-D-03 | `session/usage_tally.py`: `UsageTally` + formatting helpers | 0.4 d | D-02 | USG-001, -003, -004, -005 | `DONE` |
| TUI-D-04 | `ConversationSession` passes `DoneEvent.usage` to the tally | 0.2 d | D-03, 01-04 | SES-002 | `DONE` |
| TUI-D-05 | `widgets/statusbar.py` usage segment + `PRISMAL_TUI_SHOW_USAGE` | 0.4 d | D-03, 03-01 | USG-002, -009 | `DONE` |
| TUI-D-06 | `/usage` and `/usage all` + `widgets/usage_modal.py` | 0.6 d | D-02, 02-04 | UX-004, USG-006, -007 | `DONE` |
| TUI-D-07 | Error paths: 404/connection toasts, `budget_exceeded` copy | 0.3 d | D-06, 01-08 | USG-008, ERR-002 | `DONE` |
| TUI-D-08 | Pilot UI tests: readout after turn, `n/a`, `/usage` modal, no polling during stream | 0.5 d | D-05..07 | USG-002, -005, -006, -010 | `DONE` |
| TUI-D-09 | Contract test vs `prismal-server` 0.2 `host_fake_llm_mode` | 0.3 d | D-08, 04-02 | USG-006 | `DONE` |

## Phase 4 — Hardening & release (M5)

| ID | Task | Est. | Dep | SPEC | Status |
|---|---|---|---|---|---|
| TUI-04-01 | Secret-leak test: token absent from rendered widget text, `ConversationStore` file contents, logs, and exception text | 0.4 d | 01-01, 03-01 | AUT-002, NFR-003 | `DONE` |
| TUI-04-02 | `tests/contract/`: opt-in suite — `ConversationSession` vs a running `prismal-server` (thread reuse, streamed turn, cancel, error path) | 0.5 d | all Phase 1 | NFR-001 | `DONE` |
| TUI-04-03 | Responsiveness check: app accepts input / redraws status bar while a turn streams (no event-loop blocking) — scripted slow-stream UI test | 0.4 d | 02-07 | NFR-004 | `DONE` |
| TUI-04-04 | `docs/configuration.md` (`PRISMAL_TUI_*` reference) | 0.3 d | 00-03 | — | `DONE` |
| TUI-04-05 | `ruff` + `mypy` clean; coverage baseline recorded (97.0%, `fail_under = 97` ratchet in `pyproject.toml`) | 0.3 d | all | NFR-002 | `DONE` |
| TUI-04-06 | Tag `v0.1.0`; release workflow | 0.2 d | 04-01..05, D-01..09 | — | `DONE` |

## Future (out of scope for v0.1, tracked only)

| ID | Task | Trigger |
|---|---|---|
| TUI-FUTURE-01 | PyPI publication (`uvx prismal-tui` zero-install entrypoint) | The ecosystem's front-ends stabilize and a published package is worth maintaining |
| TUI-FUTURE-02 | Local TOML config file (theme, keybinding overrides beyond `PRISMAL_TUI_CANCEL_KEY`) | Real demand for persisted, non-secret preferences beyond env vars |
| TUI-FUTURE-03 | Multi-server / in-app server switching without restart | A user regularly needs to point the same running TUI at more than one `prismal-server` |
| TUI-FUTURE-04 | File/media attachments to the multimodal layer | Host specs a media upload route (same trigger as `prismal-webchat` WCB-FUTURE-04 / `prismal-chatbot` CHB-FUTURE-04) |
| TUI-FUTURE-05 | Per-conversation transcript export and full-text search across local conversations | Real demand once the local conversation list grows large |
| TUI-FUTURE-06 | Background per-turn timeout in addition to manual cancel | A real "walked away from the terminal mid-turn" scenario is reported |

---

## Definition of Done (v0.1)

- `uv pip install -e ".[dev]"` + `prismal-tui` boots, checks `healthz()`,
  and shows a connection status; `ruff check .` and `mypy prismal_tui` are
  clean.
- Typing a message in the composer and pressing Enter produces a streamed,
  Markdown-rendered reply in the transcript — verified offline via
  `Pilot` + fake client and manually against a real `prismal-server`.
- A conversation's `thread_id` survives a process restart (`ConversationStore`
  round-trip test with a real SQLite file).
- Pressing the cancel key mid-turn stops the stream and preserves the
  partial answer already rendered.
- A scripted fast token stream produces a bounded number of redraws, and
  the final text is never truncated relative to the full concatenation of
  deltas.
- The boundary-guard test proves no `prismal`/`prismal_server` import and
  no direct HTTP use against the host; the secret-leak test proves the
  token never reaches rendered text, the store file, or a log line.
- The `contract` suite passes against a locally running `prismal-server`.
- A fresh install (`uv pip install -e ".[dev]"`) followed by `prismal-tui`
  connects to a live `prismal-server` and completes a full conversation
  round-trip, including a restart that resumes the same conversation.

## Estimate roll-up

~**13.7 person-days** across M1–M5 (10.5 base + 3.2 for Phase D; excludes the M0 seed). Critical path is
Phase 0 → 1 → 2 → 3 → 4 (scaffold before session core before UI before
polish before hardening); within Phase 2, the transcript (TUI-02-02/03)
and the composer/sidebar (TUI-02-04/05) can proceed in parallel once
TUI-02-01 (app skeleton) is `DONE`, since neither depends on the other.
All phases (0–4 and D) are `DONE`; `v0.1.0` is tagged.

---

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-19 | Ernesto Crespo | Initial task breakdown for the terminal UI front-end |
| 1.1 | 2026-11-02 | Ernesto Crespo | Phase 0 done; DELTA-2026-10 folded in as Phase D; SDK pin `>=0.2,<1` |
| 1.2 | 2026-11-02 | Ernesto Crespo | Phase 1 (session core) done |
| 1.3 | 2026-11-02 | Ernesto Crespo | Phase 2 (transcript & composer UX) done |
| 1.4 | 2026-11-02 | Ernesto Crespo | Phase 3 (error UX & polish) done; manual checklist run against host 0.2 fake mode |
| 1.5 | 2026-11-02 | Ernesto Crespo | Phase 4 hardening (TUI-04-01..05) done; tag deferred until Phase D |
| 1.6 | 2026-11-02 | Ernesto Crespo | Phase D (usage readout, `/usage`, budget copy; TUI-D-01..09) done; contract suite 8/8 vs host 0.2 fake mode |
| 1.7 | 2026-11-02 | Ernesto Crespo | TUI-04-06 done: version 0.1.0, CHANGELOG, release workflow (tag → gates → build → smoke → GitHub Release); `v0.1.0` tagged |
| 1.8 | 2026-11-02 | Ernesto Crespo | `DELTA-2026-11-slash-escape` (TUI-E-01..02): `//text` sends `/text`; ships in 0.1.1 |
